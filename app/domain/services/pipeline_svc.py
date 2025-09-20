import logging
from typing import Optional, Dict, List
from app.core.config import get_settings
from app.domain.models.product import RecoItem, RecoResult
from app.domain.repositories.product_repo import ProductRepo
from app.domain.repositories.product_search_repo import ProductSearchRepo
from app.domain.repositories.vector_cache_repo import VectorCacheRepo
from app.domain.repositories.reco_product_cache_repo import RecoProductsCacheRepo
from app.domain.services.embedding_svc import get_or_create_embedding
from app.domain.services.constants import RETRIEVAL_K, FINAL_K, KIND_SIMILAR, KIND_COMPLEMENTARY
from app.domain.services.filters import default_filters
from app.domain.services.rag_svc import rag_answer
from app.domain.services.retrieval import retrieve_candidates

logger = logging.getLogger(__name__)

def _text_fallback(kind: str, src) -> str:
    """
    Generate a fallback text query for retrieval if no embedding is available.
    - KIND_COMPLEMENTARY: bidirectional complementary/co-usage phrasing.
    - KIND_SIMILAR: substitutable/similar phrasing.
    - Default: raise error — kind must be known to avoid silent misrouting.
    """
    tags = " ".join(src.tags or [])
    base_info = f"{src.name} {src.brand or ''} {src.category_id or ''} {src.category_path or ''} {tags}".strip()

    if kind == KIND_COMPLEMENTARY:
        # Bidirectional phrasing: works whether src is base or accessory
        return f"products commonly used, worn, or bought together with {base_info}"

    if kind == KIND_SIMILAR:
        return f"products similar to {base_info}"

    # Default: raise error kind should be known
    raise ValueError(f"Unknown kind for text fallback: {kind}")


async def recommend(
    *,
    kind: str,
    version: str,
    product_id: str,
    db,
    redis,
    must_filters: Optional[Dict] = None,
    use_text_fallback: bool = True,
    use_llm: bool = True,
    include_rationale: bool = False,
) -> RecoResult:
    """
    End-to-end recommendation pipeline (generic for multiple kinds).

    High-level flow:
      1) Build a version- and kind-aware cache key and try to serve from Redis.
      2) Load the source product (hard stop if missing).
      3) Get an embedding for the (product_id, kind) pair:
           - First try Redis → then Mongo vectors.<kind> → else OpenAI (locked) → cache + persist.
      4) Decide retrieval filters:
           - Use caller's must_filters OR sensible defaults per kind (sim/comp).
      5) Retrieve a candidate pool from Atlas (vector first, optional text fallback) with K=RETRIEVAL_K.
      6) (Optional) Rerank candidates via LLM using a RAG prompt tailored to `kind`.
      7) Truncate to FINAL_K, cache the final list, and return a typed RecoResult.

    Notes:
      - Caching is applied at two layers:
          * Vector cache (inside get_or_create_embedding) to avoid repeated embeddings.
          * Final list cache here (RecoProductsCacheRepo) to avoid recomputing retrieval + LLM.
      - `version` is folded into the cache key so v1/v2 results never collide.
      - Be careful that document `vectors` should be stored in MongoDB Atlas only and not redis as it is an anti-pattern.
      - `kind` namespaces both the vector cache (e.g., "{product_id}:comp") and the final-list cache (key_prefix).
    """
    settings = get_settings()
    logger.info(f"Starting recommend pipeline: kind={kind}, version={version}, product_id={product_id}")

    prod_repo = ProductRepo(db)
    search_repo = ProductSearchRepo(db)

    # ---- 1) Final-list cache (fast path) -----------------------------------
    # Build separate cache keys for LLM vs non-LLM results
    reco_cache = RecoProductsCacheRepo(redis, key_prefix=kind)
    
    def build_cache_key(with_llm: bool) -> str:
        cache_filters = {
            "_must": must_filters or {},
            "_rerank": with_llm,  # Different cache keys for LLM vs non-LLM
            "_retrieval_k": RETRIEVAL_K,
            "_final_k": FINAL_K,
            "_kind": kind,
        }
        return reco_cache.key(
            version=version,
            product_id=product_id,
            limit=FINAL_K,
            filt=cache_filters,
            model=settings.OPENAI_EMBEDDING_MODEL,
        )

    # Try cache for requested mode first
    reco_cache_key = build_cache_key(with_llm=use_llm)
    logger.debug(f"Reco cache key generated: {reco_cache_key}")
    if cached := await reco_cache.get(reco_cache_key):
        logger.info(f"Cache hit for product_id={product_id}, kind={kind}, version={version}, llm={use_llm}")
        return RecoResult(source_product_id=product_id, items=cached, count=len(cached))

    # ---- 2) Load source product --------------------------------------------
    # If the product does not exist, cache an empty list briefly to prevent dogpiles.
    src = await prod_repo.get_by_product_id(product_id)
    logger.debug(f"Loaded source product: {src}")
    if not src:
        logger.warning(f"Product not found: product_id={product_id}")
        await reco_cache.set(reco_cache_key, [], ttl=settings.product_cache_ttl)
        return RecoResult(source_product_id=product_id, items=[], count=0)

    # ---- 3) Kind-aware embedding (vector cache + DB persistence) -----------
    # Redis key: "{product_id}:{kind}"
    # Mongo path: "vectors.<kind>"
    try:
        vec = await get_or_create_embedding(
            db=db,
            cache=VectorCacheRepo(redis),
            product_id=product_id,
            kind=kind,
            use_db_fallback=True,
            write_back_db=False,
        )
        logger.debug(f"Embedding vector for product_id={product_id}, kind={kind}")
    except Exception as e:
        logger.error(f"Error getting embedding for product_id={product_id}: {e}")
        vec = None

    # ---- 4) Filters & text fallback query ----------------------------------
    # If the caller provided filters, use them; otherwise compute sensible defaults per kind.
    eff_filters = must_filters or default_filters(kind, src)
    text_query = _text_fallback(kind, src) if use_text_fallback else ""
    logger.debug(f"Effective filters: {eff_filters}")
    logger.debug(f"Text fallback query: {text_query}")

    # ---- 5) Retrieval (Atlas Search) ---------------------------------------
    # Try vector search first with RETRIEVAL_K (e.g., 50) to give reranking headroom.
    # If vector search fails or returns nothing, use text fallback if allowed.
    try:
        items: List[RecoItem] = await retrieve_candidates(
            search_repo=search_repo,
            vec=vec,
            text_query=text_query,
            must_filters=eff_filters,
            retrieval_k=RETRIEVAL_K,
        )
        logger.info(f"Retrieved {len(items)} candidates for product_id={product_id}")
    except Exception as e:
        logger.error(f"Error during candidate retrieval for product_id={product_id}: {e}")
        items = []

    # ---- 6) Optional LLM RAG re-ranking ------------------------------------
    llm_applied = False
    if items and use_llm:
        try:
            items = await rag_answer(
                kind=kind,
                src=src,
                candidates=items,
                prod_repo=prod_repo,
                settings=settings,
                include_rationale=include_rationale,
            )
            llm_applied = True
            logger.info(f"LLM reranking applied for product_id={product_id}, candidates={len(items)}")
        except Exception as e:
            # LLM failed: try to serve from non-LLM cache as fallback
            logger.error(f"LLM reranking failed for product_id={product_id}: {e}")
            non_llm_cache_key = build_cache_key(with_llm=False)
            if non_llm_cached := await reco_cache.get(non_llm_cache_key):
                logger.info(f"LLM failed, serving from non-LLM cache for product_id={product_id}")
                return RecoResult(source_product_id=product_id, items=non_llm_cached, count=len(non_llm_cached))
            # No fallback cache available, continue with original items
            logger.warning(f"No non-LLM cache available for fallback, using original retrieval results")

    # ---- 7) Truncate, cache, return ----------------------------------------
    items = items[:FINAL_K]
    
    # Cache based on what actually happened (not what was requested)
    final_cache_key = build_cache_key(with_llm=llm_applied)
    await reco_cache.set(final_cache_key, items, ttl=settings.product_cache_ttl)
    
    # If LLM was requested but failed, also cache as non-LLM for future fallbacks
    if use_llm and not llm_applied:
        non_llm_cache_key = build_cache_key(with_llm=False)
        await reco_cache.set(non_llm_cache_key, items, ttl=settings.product_cache_ttl)
    
    logger.info(f"Final result cached for product_id={product_id}, items={len(items)}, llm_applied={llm_applied}")

    return RecoResult(source_product_id=product_id, items=items, count=len(items))
