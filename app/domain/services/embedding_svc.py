# app/domain/services/embedding_svc.py

from __future__ import annotations
from typing import Optional, Callable, Dict
import logging
import time

from openai import AsyncOpenAI
from app.db.redis import get_redis
from app.core.config import get_settings
from app.domain.repositories.product_repo import ProductRepo
from app.domain.repositories.vector_cache_repo import VectorCacheRepo
from app.utils.locks import RedisLock
from app.domain.services.constants import KIND_COMPLEMENTARY, KIND_SIMILAR
from itertools import islice

logger = logging.getLogger(__name__)

# ---------- Text builders registry -------------------------------------------

def _text_for_sim(product) -> str:
    """Similarity/substitutability representation (same family/purpose)."""
    return " | ".join(filter(None, [
        product.name,
        product.brand,
        (product.description or "")[:220],
        " ".join(product.tags or []),
    ]))

def _text_for_comp(product) -> str:
    """
    Build a bidirectional complementarity description for embeddings.
    It does not assume the product is a base or an accessory.
    The phrasing targets items typically USED TOGETHER with this product.
    """
    parts = [
        f"Product name: {product.name or ''}",
        f"Brand: {product.brand}" if product.brand else None,
        f"Category: {product.category_id}" if product.category_id else None,
        f"Category Path: {product.category_path}" if product.category_path else None,
        f"Tags: {' '.join(product.tags)}" if getattr(product, 'tags', None) else None,
        # Role-agnostic instruction to bias the embedding toward co-usage
        "Find products commonly used, worn, or purchased together with this item (either as base or accessory).",
        # Short description to enrich the semantic signal without ballooning tokens
        (product.description or "")[:200],
    ]
    return " | ".join(filter(None, parts))

def _text_generic(product) -> str:
    """Fallback representation for unknown kinds."""
    return " | ".join(filter(None, [
        product.name,
        product.brand,
        (product.description or "")[:200],
        " ".join(product.tags or []),
        f"Category: {product.category_id}" if product.category_id else None,
        f"Category Path: {product.category_path}" if product.category_path else None,
    ]))

# You can extend this registry with future kinds (e.g., "brand", "tag", "bundle", etc.)
TEXT_BUILDERS: Dict[str, Callable] = {
    KIND_SIMILAR: _text_for_sim,
    KIND_COMPLEMENTARY: _text_for_comp,
    # "brand": _text_for_brand, ...
}

# ---------- Public API --------------------------------------------------------

async def get_or_create_embedding(
    db, cache: VectorCacheRepo, product_id: str, *,
    kind: str, use_db_fallback: bool = True, write_back_db: bool = False
):
    """
    Retrieve an embedding for a product for ANY 'kind', with:
      - Redis cache key: "{product_id}:{kind}"
      - Mongo persistence path: "vectors.<kind> = { model, vector, updated_at }"

    Steps:
      1) Try Redis cache
      2) If enabled, try MongoDB vectors.<kind>.vector
      3) Compute under Redis lock to avoid duplicate OpenAI calls
      4) Cache in Redis and (if enabled) persist in Mongo under vectors.<kind>

    Notes:
      - For every 'kind', persistence is supported (if write_back_db=True).
      - Use TEXT_BUILDERS registry to specialize the embedding text per kind.
    """
    settings = get_settings()
    prod_repo = ProductRepo(db)

    # 1) Redis cache (namespaced by kind)
    cache_key = cache.key(f"{product_id}:{kind}", settings.OPENAI_EMBEDDING_MODEL)
    logger.debug(f"Trying Redis cache for key: {cache_key}")
    if vec := await cache.get(cache_key):
        logger.info(f"Embedding cache hit for product_id={product_id}, kind={kind}")
        return vec

    # 2) Mongo fallback (vectors.<kind>.vector)
    if use_db_fallback:
        logger.debug(f"Trying MongoDB fallback for product_id={product_id}, kind={kind}")
        if db_vec := await prod_repo.get_vector(product_id, kind):
            logger.info(f"Embedding found in MongoDB for product_id={product_id}, kind={kind}")
            await cache.set(cache_key, db_vec, ttl=settings.vector_cache_ttl)
            return db_vec

    # 3) Compute safely under a short Redis lock
    lock = RedisLock(get_redis(), cache_key, ttl=settings.vector_lock_ttl)
    logger.debug(f"Acquiring Redis lock for embedding computation: {cache_key}")
    acquired = await lock.acquire()
    try:
        if not acquired:
            logger.info(f"Lock not acquired, waiting for embedding to be available in cache for key: {cache_key}")
            await lock.wait(timeout=settings.vector_lock_ttl)
            return await cache.get(cache_key)

        # Double-check cache after acquiring the lock
        logger.debug(f"Lock acquired, double-checking cache for key: {cache_key}")
        if vec := await cache.get(cache_key):
            logger.info(f"Embedding cache hit after lock for product_id={product_id}, kind={kind}")
            return vec

        product = await prod_repo.get_by_product_id(product_id)
        logger.debug(f"Loaded product for embedding: {product}")
        if not product:
            logger.warning(f"Product not found for embedding: product_id={product_id}")
            return None

        # 3a) Build text using a specialized builder (or generic fallback)
        builder = TEXT_BUILDERS.get(kind, _text_generic)
        text = builder(product)
        logger.debug(f"Text for embedding (kind={kind}): {text}")

        # 3b) Embed via OpenAI
        logger.info(f"Requesting embedding from OpenAI for product_id={product_id}, kind={kind}")
        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        resp = await client.embeddings.create(model=settings.OPENAI_EMBEDDING_MODEL, input=text)
        vec = resp.data[0].embedding
        logger.info(f"Received embedding from OpenAI for product_id={product_id}, kind={kind}")

        # 4a) Cache in Redis
        await cache.set(cache_key, vec, ttl=settings.vector_cache_ttl)
        logger.debug(f"Embedding cached in Redis for key: {cache_key}")

        # 4b) Persist in Mongo under vectors.<kind>
        if write_back_db:
            logger.debug(f"Persisting embedding in MongoDB for product_id={product_id}, kind={kind}")
            await prod_repo.set_vector(product_id, kind, vec, model=settings.OPENAI_EMBEDDING_MODEL)

        return vec
    finally:
        if acquired:
            await lock.release()

async def batch_get_or_create_embeddings(
    db,
    cache: VectorCacheRepo,
    product_ids: list[str],
    *,
    kind: str,
    force: bool = False,
    write_back_db: bool = True,
    hydrate_cache: bool = True,
    openai_batch_size: int = 64,
    scan_batch_size: int = 500,
) -> dict:
    """
    High-volume variant of get_or_create_embedding for MANY product_ids.
    Efficiently:
      1. Skips products already in Redis (unless force=True)
      2. Falls back to MongoDB stored vectors (unless force=True)
      3. Batches remaining products into OpenAI embedding calls (list input)
      4. Persists & caches new vectors

    Parameters:
      product_ids        List of product ids (can be large; will be deduplicated)
      kind               Embedding kind (sim / comp / etc.)
      force              If True, recompute even if cache or DB present
      write_back_db      Persist newly computed vectors into Mongo
      hydrate_cache      Store DB-found vectors into Redis
      openai_batch_size  Max inputs per OpenAI embeddings.create() call
      scan_batch_size    How many product docs to load from Mongo per scan

    Returns stats dict:
      {
        'total_requested', 'unique_ids', 'cache_hits', 'db_hits',
        'embedded', 'missing_products', 'errors'
      }
    """
    start_ts = time.perf_counter()
    logger.info(
        f"[batch_embed] start kind={kind} total_ids={len(product_ids)} "
        f"force={force} openai_batch_size={openai_batch_size} scan_batch_size={scan_batch_size}"
    )

    settings = get_settings()
    prod_repo = ProductRepo(db)
    unique_ids = list(dict.fromkeys(product_ids))  # preserve order, dedupe
    if len(unique_ids) != len(product_ids):
        logger.debug(f"[batch_embed] deduplicated ids {len(product_ids)} -> {len(unique_ids)}")

    cache_hits = 0
    db_hits = 0
    embedded = 0
    missing_products: list[str] = []
    errors: list[str] = []

    # STEP 1: Determine which ids still need embedding
    to_check_db: list[str] = []
    to_embed: list[str] = []

    model_name = settings.OPENAI_EMBEDDING_MODEL

    # Fast pass: cache lookups
    logger.debug(f"[batch_embed] cache lookup pass kind={kind}")
    for pid in unique_ids:
        cache_key = cache.key(f"{pid}:{kind}", model_name)
        if not force:
            vec = await cache.get(cache_key)
            if vec:
                cache_hits += 1
                continue
        to_check_db.append(pid)
    logger.debug(
        f"[batch_embed] after cache pass kind={kind} cache_hits={cache_hits} "
        f"remaining_for_db={len(to_check_db)} force={force}"
    )

    # STEP 2: Mongo scan for remaining
    if to_check_db and not force:
        # Scan in batches to avoid loading everything
        logger.debug(f"[batch_embed] DB scan start batches={ (len(to_check_db)+scan_batch_size-1)//scan_batch_size }")
        for i in range(0, len(to_check_db), scan_batch_size):
            chunk = to_check_db[i:i + scan_batch_size]
            # Fetch only vectors.<kind>
            cursor = db["products"].find(
                {"product_id": {"$in": chunk}},
                {
                    "_id": 0,
                    "product_id": 1,
                    f"vectors.{kind}.vector": 1,
                },
            )
            found_map: dict[str, list[float]] = {}
            async for doc in cursor:
                v = doc.get("vectors", {}).get(kind, {}).get("vector")
                if v:
                    found_map[doc["product_id"]] = v
            # Classify
            for pid in chunk:
                if pid in found_map:
                    db_hits += 1
                    if hydrate_cache:
                        cache_key = cache.key(f"{pid}:{kind}", model_name)
                        await cache.set(cache_key, found_map[pid], ttl=settings.vector_cache_ttl)
                else:
                    to_embed.append(pid)
            logger.debug(
                f"[batch_embed] db_batch={i//scan_batch_size + 1} chunk={len(chunk)} "
                f"cumulative_db_hits={db_hits} cumulative_to_embed={len(to_embed)}"
            )
    else:
        # force=True -> all remaining go to embedding
        to_embed = to_check_db

    logger.debug(
        f"[batch_embed] post-db kind={kind} db_hits={db_hits} to_embed={len(to_embed)} "
        f"cache_hits={cache_hits}"
    )

    if not to_embed:
        elapsed = (time.perf_counter() - start_ts) * 1000
        logger.info(
            f"[batch_embed] done kind={kind} (no embedding needed) cache_hits={cache_hits} "
            f"db_hits={db_hits} embedded=0 ms={elapsed:.1f}"
        )
        return {
            "total_requested": len(product_ids),
            "unique_ids": len(unique_ids),
            "cache_hits": cache_hits,
            "db_hits": db_hits,
            "embedded": embedded,
            "missing_products": missing_products,
            "errors": errors,
        }

    # Helper: chunk iterator
    def _chunks(seq, n):
        it = iter(seq)
        while True:
            batch = list(islice(it, n))
            if not batch:
                break
            yield batch

    builder = TEXT_BUILDERS.get(kind, _text_generic)
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    # STEP 3: Fetch product docs & prepare texts in batches
    total_batches = (len(to_embed) + scan_batch_size - 1) // scan_batch_size
    logger.debug(f"[batch_embed] embedding fetch/prepare batches={total_batches}")
    for b_index, id_batch in enumerate(_chunks(to_embed, scan_batch_size), start=1):
        # Fetch docs for this batch
        docs_cursor = db["products"].find(
            {"product_id": {"$in": id_batch}},
            {
                "_id": 0,
                "product_id": 1,
                "name": 1,
                "brand": 1,
                "description": 1,
                "tags": 1,
                "category_id": 1,
                "category_path": 1,
                f"vectors.{kind}.vector": 1,
            },
        )
        docs_map: dict[str, any] = {}
        async for d in docs_cursor:
            docs_map[d["product_id"]] = d

        # Partition available vs missing
        present_ids = [pid for pid in id_batch if pid in docs_map]
        for pid in id_batch:
            if pid not in docs_map:
                missing_products.append(pid)
        if missing_products:
            logger.debug(
                f"[batch_embed] batch={b_index}/{total_batches} missing_in_db_increment={len([m for m in id_batch if m not in docs_map])}"
            )

        # Build texts for present_ids
        present_ids_sorted = present_ids  # keep order
        for embed_batch_ids in _chunks(present_ids_sorted, openai_batch_size):
            texts = []
            embed_batch_real_ids = []
            for pid in embed_batch_ids:
                prod_raw = docs_map[pid]
                # Quick guard: if vector appears now (race) skip
                if not force and prod_raw.get("vectors", {}).get(kind, {}).get("vector"):
                    # Already computed by another process
                    db_hits += 1
                    continue
                # Wrap raw dict into a lightweight object-like accessor if builder expects attributes
                class PObj:
                    __slots__ = ("name", "brand", "description", "tags", "category_id", "category_path")
                    def __init__(self, d):
                        self.name = d.get("name")
                        self.brand = d.get("brand")
                        self.description = d.get("description")
                        self.tags = d.get("tags")
                        self.category_id = d.get("category_id")
                        self.category_path = d.get("category_path")
                text = builder(PObj(prod_raw))
                if not text:
                    logger.debug(f"[batch_embed] skip empty text product_id={pid}")
                    continue
                texts.append(text)
                embed_batch_real_ids.append(pid)

            if not texts:
                continue

            logger.debug(
                f"[batch_embed] openai_call kind={kind} batch_size={len(texts)} "
                f"progress_embedded={embedded} remaining_to_embed={len(to_embed)-embedded}"
            )
            try:
                resp = await client.embeddings.create(model=model_name, input=texts)
                if len(resp.data) != len(embed_batch_real_ids):
                    msg = f"batch_mismatch expected={len(embed_batch_real_ids)} got={len(resp.data)}"
                    errors.append(msg)
                    logger.warning(f"[batch_embed] {msg}")
                    continue
                for pid, item in zip(embed_batch_real_ids, resp.data):
                    vec = item.embedding
                    cache_key = cache.key(f"{pid}:{kind}", model_name)
                    await cache.set(cache_key, vec, ttl=settings.vector_cache_ttl)
                    if write_back_db:
                        try:
                            await prod_repo.set_vector(pid, kind, vec, model=model_name)
                        except Exception as e:
                            err = f"mongo_set {pid}: {e}"
                            errors.append(err)
                            logger.error(f"[batch_embed] {err}")
                            continue
                    embedded += 1
            except Exception as e:
                err = f"openai_batch_error size={len(texts)}: {e}"
                errors.append(err)
                logger.error(f"[batch_embed] {err}")

    elapsed_ms = (time.perf_counter() - start_ts) * 1000.0
    logger.info(
        f"[batch_embed] done kind={kind} total_req={len(product_ids)} unique={len(unique_ids)} "
        f"cache_hits={cache_hits} db_hits={db_hits} embedded={embedded} "
        f"missing={len(missing_products)} errors={len(errors)} time_ms={elapsed_ms:.1f}"
    )
    return {
        "total_requested": len(product_ids),
        "unique_ids": len(unique_ids),
        "cache_hits": cache_hits,
        "db_hits": db_hits,
        "embedded": embedded,
        "missing_products": missing_products,
        "errors": errors,
    }
