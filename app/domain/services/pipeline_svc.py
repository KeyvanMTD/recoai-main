# app/domain/services/pipeline_svc.py
import logging
from typing import Optional, Dict, List, Any
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
    """Requête texte de secours si pas de vecteur."""
    tags = " ".join(src.tags or [])
    base_info = f"{src.name} {src.brand or ''} {src.category_id or ''} {src.category_path or ''} {tags}".strip()

    if kind == KIND_COMPLEMENTARY:
        return f"products commonly used, worn, or bought together with {base_info}"
    if kind == KIND_SIMILAR:
        return f"products similar to {base_info}"

    raise ValueError(f"Unknown kind for text fallback: {kind}")


def _sanitize_filters(must_filters: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Atlas Search refuse `compound.filter: []`. Ici on supprime `filter` s'il est vide
    et on renvoie None si le dict est finalement vide.
    """
    if not must_filters:
        return None
    filt = dict(must_filters)  # shallow copy
    comp = filt.get("compound")
    if isinstance(comp, dict):
        # si filter existe mais vide -> on le retire
        if "filter" in comp and (not comp["filter"] or len(comp["filter"]) == 0):
            comp.pop("filter", None)
        # si compound devient vide -> on l’enlève
        if not comp:
            filt.pop("compound", None)
    return filt or None


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
    Pipeline de reco générique (sim/comp) avec cache final + tolérance embedding.
    """
    settings = get_settings()
    logger.info("Starting recommend pipeline: kind=%s, version=%s, product_id=%s", kind, version, product_id)

    prod_repo = ProductRepo(db)
    search_repo = ProductSearchRepo(db)

    # ---- 1) Cache final -----------------------------------------------------
    reco_cache = RecoProductsCacheRepo(redis, key_prefix=kind)

    def build_cache_key(with_llm: bool) -> str:
        cache_filters = {
            "_must": must_filters or {},
            "_rerank": with_llm,
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

    reco_cache_key = build_cache_key(with_llm=use_llm)
    if cached := await reco_cache.get(reco_cache_key):
        logger.info("Cache hit: product_id=%s kind=%s version=%s llm=%s", product_id, kind, version, use_llm)
        return RecoResult(source_product_id=product_id, items=cached, count=len(cached))

    # ---- 2) Produit source --------------------------------------------------
    src = await prod_repo.get_by_product_id(product_id)
    if not src:
        logger.warning("Product not found: %s", product_id)
        await reco_cache.set(reco_cache_key, [], ttl=settings.product_cache_ttl)
        return RecoResult(source_product_id=product_id, items=[], count=0)

    # ---- 3) Embedding (tolérant) -------------------------------------------
    try:
        vec = await get_or_create_embedding(
            db=db,
            cache=VectorCacheRepo(redis),
            product_id=product_id,
            kind=kind,
            use_db_fallback=True,
            write_back_db=False,
        )
    except Exception as e:
        logger.error("Error getting embedding for %s: %s", product_id, e)
        vec = None  # on bascule texte si autorisé

    # ---- 4) Filtres + texte fallback ---------------------------------------
    eff_filters = _sanitize_filters(must_filters or default_filters(kind, src))
    text_query = _text_fallback(kind, src) if use_text_fallback else ""
    logger.debug("Effective filters (sanitized): %s", eff_filters)
    logger.debug("Text fallback query: %s", text_query)

    # ---- 5) Retrieval -------------------------------------------------------
    try:
        items: List[RecoItem] = await retrieve_candidates(
            search_repo=search_repo,
            vec=vec,
            text_query=text_query,
            must_filters=eff_filters,
            retrieval_k=RETRIEVAL_K,
        )
        logger.info("Retrieved %d candidates for %s", len(items), product_id)
    except Exception as e:
        logger.error("Candidate retrieval error for %s: %s", product_id, e)
        items = []

    # ---- 6) (opt) Rerank LLM ------------------------------------------------
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
            logger.info("LLM reranking applied for %s (%d items)", product_id, len(items))
        except Exception as e:
            logger.error("LLM reranking failed for %s: %s", product_id, e)
            non_llm_key = build_cache_key(with_llm=False)
            if non_llm_cached := await reco_cache.get(non_llm_key):
                logger.info("Serving non-LLM cache fallback for %s", product_id)
                return RecoResult(source_product_id=product_id, items=non_llm_cached, count=len(non_llm_cached))

    # ---- 7) Troncature + caches -------------------------------------------
    items = items[:FINAL_K]
    final_key = build_cache_key(with_llm=llm_applied)
    await reco_cache.set(final_key, items, ttl=settings.product_cache_ttl)
    if use_llm and not llm_applied:
        await reco_cache.set(build_cache_key(with_llm=False), items, ttl=settings.product_cache_ttl)

    logger.info("Final result cached: product_id=%s items=%d llm_applied=%s", product_id, len(items), llm_applied)
    return RecoResult(source_product_id=product_id, items=items, count=len(items))
