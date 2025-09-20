# app/services/xsell_svc.py
import json
import time
import hashlib
import logging
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from app.core.config import get_settings
from app.domain.services.rag_svc import rag_answer
from app.domain.services.constants import KIND_XSELL
from app.domain.models.product import RecoItem, RecoResult  # <-- import RecoResult

logger = logging.getLogger(__name__)

# --- helpers ---------------------------------------------------------------

async def _get_user_purchased_product_ids(db, user_id: str) -> List[str]:
    """
    Return all product_ids the user has purchased (any order).
    Used to avoid recommending one-time purchases already bought.
    """
    t0 = time.perf_counter()
    try:
        # Motor supports distinct; fast and simple
        ids: List[str] = await db["events"].distinct(
            "product_id",
            {"event_type": "purchase", "user_id": user_id},
        )
        dt = time.perf_counter() - t0
        logger.info("xsell purchased_ids user_id=%s n=%s time=%.3fs", user_id, len(ids), dt)
        return ids or []
    except Exception as e:
        logger.warning("xsell purchased_ids error user_id=%s err=%s", user_id, e)
        return []

async def _get_user_cart_product_ids(db, user_id: str) -> List[str]:
    """
    Return all product_ids the user has added to cart.
    Used to avoid recommending items already in cart (optional).
    """
    t0 = time.perf_counter()
    try:
        ids: List[str] = await db["events"].distinct(
            "product_id",
            {"event_type": "add_to_cart", "user_id": user_id},
        )
        dt = time.perf_counter() - t0
        logger.info("xsell cart_ids user_id=%s n=%s time=%.3fs", user_id, len(ids), dt)
        return ids or []
    except Exception as e:
        logger.warning("xsell cart_ids error user_id=%s err=%s", user_id, e)
        return []

def _json_preview(obj: Any, limit: int = 1500) -> str:
    try:
        s = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
        return s if len(s) <= limit else s[:limit] + "…[truncated]"
    except Exception:
        return "<unserializable>"

def _make_prod_repo(db):
    """
    Create a minimal repo wrapper accepted by rag_svc (has .col or .get_many_by_product_ids).
    """
    class _Repo:
        def __init__(self, col):
            self.col = col
        async def get_many_by_product_ids(self, ids: List[str]) -> List[Dict[str, Any]]:
            cursor = self.col.find({"product_id": {"$in": ids}}, {
                "_id": 0,
                "product_id": 1,
                "name": 1,
                "brand": 1,
                "description": 1,
                "category_id": 1,
                "category_path": 1,
                "current_price": 1,
                "currency": 1,
                "tags": 1,
                "metadata": 1,
            })
            return await cursor.to_list(length=None)
    return _Repo(db["products"])

async def _get_src_product(db, product_id: str) -> Optional[SimpleNamespace]:
    doc = await db["products"].find_one(
        {"product_id": product_id},
        {
            "_id": 0,
            "product_id": 1,
            "name": 1,
            "brand": 1,
            "description": 1,
            "category_id": 1,
            "category_path": 1,
            "tags": 1,
            "metadata": 1,
        },
    )
    if not doc:
        return None
    # Minimal attribute bag used by rag_svc._compact_source
    return SimpleNamespace(
        product_id=doc.get("product_id"),
        name=doc.get("name"),
        brand=doc.get("brand"),
        description=doc.get("description"),
        category_id=doc.get("category_id"),
        category_path=doc.get("category_path"),
        tags=doc.get("tags") or [],
        metadata=doc.get("metadata") or {},
    )

async def _mine_xsell_candidates(db, *, product_id: str, user_id: Optional[str], prelimit: int) -> List[Dict[str, Any]]:
    """
    Return list of {product_id, count} co-purchased with the given product_id.
    Uses order key = metadata.order_id fallback session_id.
    """
    pipeline: List[Dict[str, Any]] = [
        {"$match": {"event_type": "purchase"}},
        # Optional user personalization (only this user's purchases)
    ]
    if user_id:
        pipeline.append({"$match": {"user_id": user_id}})
    pipeline += [
        {"$addFields": {"ok": {"$ifNull": ["$metadata.order_id", "$session_id"]}}},
        {"$group": {"_id": "$ok", "prods": {"$addToSet": "$product_id"}}},
        {"$match": {"$expr": {"$in": [product_id, "$prods"]}}},
        {"$project": {"_id": 0, "co": {"$setDifference": ["$prods", [product_id]]}}},
        {"$unwind": "$co"},
        {"$group": {"_id": "$co", "co_count": {"$sum": 1}}},
        {"$sort": {"co_count": -1}},
        {"$limit": prelimit},
        {"$project": {"_id": 0, "product_id": "$_id", "count": "$co_count"}},
    ]

    logger.debug("xsell pipeline=%s", _json_preview(pipeline))
    t0 = time.perf_counter()
    docs = await db["events"].aggregate(pipeline).to_list(length=None)
    dt = time.perf_counter() - t0
    logger.info("xsell mined candidates n=%s db_time=%.3fs", len(docs), dt)
    return docs

async def get_xsell_products_cached_for_product(
    db,
    redis,
    *,
    version: str,
    product_id: str,
    user_id: Optional[str] = None,
    limit: int = 10,
    use_llm_rerank: bool = True,
    include_rationale: bool = False,
    brand:  Optional[str] = None,
    category_id: Optional[str] = None,
    exclude_already_purchased: bool = True,   # ignore items user already purchased
    exclude_already_in_cart: bool = True,    # ignore items user already added to cart
    **kwargs,
) -> RecoResult:  # <-- return RecoResult
    """
    Cross-sell: products most often purchased together with `product_id`.
    Optionally personalized by user_id. Reranked by LLM (KIND_XSELL).
    Cached for 24h via settings.x_sell_cache_ttl.

    Returns a RecoResult with items: List[RecoItem].
    """
    t0 = time.perf_counter()  # track total service time
    settings = get_settings()
    ttl = settings.x_sell_cache_ttl
    cache_key_raw = {
        "v": version,
        "pid": product_id,
        "uid": user_id,
        "limit": limit,
        "llm": bool(use_llm_rerank),
        "r": bool(include_rationale),
        "excl_p": bool(exclude_already_purchased),
        "excl_c": bool(exclude_already_in_cart),
        "brand": brand,
        "category_id": category_id,
    }
    cache_key = "xsell:" + hashlib.md5(json.dumps(cache_key_raw, sort_keys=True, default=str).encode()).hexdigest()
    logger.debug("xsell cache_key=%s data=%s", cache_key, _json_preview(cache_key_raw))

    # Cache get (tries RecoResult JSON; falls back to legacy list format)
    try:
        cached = await redis.get(cache_key)
        if cached:
            try:
                result = RecoResult.model_validate_json(cached)  # preferred path
            except Exception:
                # Legacy cache was a JSON list of dicts -> adapt
                items_raw = json.loads(cached)
                items = [RecoItem(**it) for it in items_raw]
                result = RecoResult(
                    source_product_id=product_id,
                    count=len(items),
                    items=items,
                )
            total_dt = time.perf_counter() - t0
            logger.info("xsell cache_hit key=%s items=%s total_time=%.3fs", cache_key, len(result.items), total_dt)
            return result
    except Exception as e:
        logger.warning("xsell redis.get error key=%s err=%s", cache_key, e)

    logger.info(
        "xsell cache_miss product_id=%s user_id=%s limit=%s exclude_purchased=%s exclude_in_cart=%s brand=%s category_id=%s",
        product_id, user_id, limit, exclude_already_purchased, exclude_already_in_cart, brand, category_id
    )

    # 1) Fetch source product
    src = await _get_src_product(db, product_id)
    if not src:
        logger.info("xsell no source product found for product_id=%s", product_id)
        total_dt = time.perf_counter() - t0
        logger.info("xsell done items=0 total_time=%.3fs (no source)", total_dt)
        empty = RecoResult(source_product_id=product_id, count=0, items=[])
        try:
            await redis.set(cache_key, empty.model_dump_json(), ex=ttl)
        except Exception:
            pass
        return empty

    # 2) Mine co-purchase candidates (pre-limit > limit for rerank headroom)
    prelimit = max(limit * 4, limit)
    mined = await _mine_xsell_candidates(db, product_id=product_id, user_id=user_id, prelimit=prelimit)

    if not mined:
        logger.info("xsell no co-purchase candidates for product_id=%s", product_id)
        empty = RecoResult(source_product_id=product_id, count=0, items=[])
        try:
            await redis.set(cache_key, empty.model_dump_json(), ex=ttl)
        except Exception as e:
            logger.warning("xsell redis.set error key=%s err=%s", cache_key, e)
        total_dt = time.perf_counter() - t0
        logger.info("xsell done items=0 total_time=%.3fs (no candidates)", total_dt)
        return empty

    # 2b) Optionally exclude items already purchased and/or in cart for this user
    if user_id and (exclude_already_purchased or exclude_already_in_cart):
        exclusion_ids = set()
        if exclude_already_purchased:
            exclusion_ids.update(await _get_user_purchased_product_ids(db, user_id))
        if exclude_already_in_cart:
            exclusion_ids.update(await _get_user_cart_product_ids(db, user_id))

        before = len(mined)
        mined = [m for m in mined if m["product_id"] not in exclusion_ids and m["product_id"] != product_id]
        after = len(mined)
        logger.info(
            "xsell excluded history user_id=%s removed=%s -> %s (purchased=%s, cart=%s)",
            user_id, (before - after), after, exclude_already_purchased, exclude_already_in_cart
        )
        if not mined:
            logger.info("xsell nothing left after exclusion; caching empty.")
            empty = RecoResult(source_product_id=product_id, count=0, items=[])
            try:
                await redis.set(cache_key, empty.model_dump_json(), ex=ttl)
            except Exception as e:
                logger.warning("xsell redis.set error key=%s err=%s", cache_key, e)
            total_dt = time.perf_counter() - t0
            logger.info("xsell done items=0 total_time=%.3fs (excluded all)", total_dt)
            return empty

    # 2c) Optional filter by brand/category_id using products collection
    if brand or category_id:
        ids = [m["product_id"] for m in mined]
        proj = {"_id": 0, "product_id": 1, "brand": 1, "category_id": 1}
        t_f = time.perf_counter()
        docs = await db["products"].find({"product_id": {"$in": ids}}, proj).to_list(length=None)
        allowed = set()
        for d in docs:
            if brand and d.get("brand") != brand:
                continue
            if category_id and d.get("category_id") != category_id:
                continue
            allowed.add(d.get("product_id"))
        before = len(mined)
        mined = [m for m in mined if m["product_id"] in allowed]
        dt_f = time.perf_counter() - t_f
        logger.info(
            "xsell filter brand/category applied brand=%s category_id=%s kept=%s/%s filter_time=%.3fs",
            brand, category_id, len(mined), before, dt_f
        )
        if not mined:
            logger.info("xsell no candidates after brand/category filter; caching empty.")
            empty = RecoResult(source_product_id=product_id, count=0, items=[])
            try:
                await redis.set(cache_key, empty.model_dump_json(), ex=ttl)
            except Exception as e:
                logger.warning("xsell redis.set error key=%s err=%s", cache_key, e)
            total_dt = time.perf_counter() - t0
            logger.info("xsell done items=0 total_time=%.3fs (brand/category filter)", total_dt)
            return empty

    # 3) Normalize counts to [0,1] as initial scores
    max_count = max((m["count"] for m in mined), default=1)
    candidates = [
        RecoItem(product_id=m["product_id"], score=(m["count"] / max_count))
        for m in mined
        if m["product_id"] != product_id
    ]
    logger.debug("xsell candidates n=%s preview=%s", len(candidates), [c.product_id for c in candidates[:15]])

    # 4) Optional LLM rerank
    if use_llm_rerank:
        try:
            prod_repo = _make_prod_repo(db)
            t_llm = time.perf_counter()
            ranked = await rag_answer(
                kind=KIND_XSELL,
                src=src,
                candidates=candidates,
                prod_repo=prod_repo,
                settings=settings,
                include_rationale=include_rationale,
            )
            llm_dt = time.perf_counter() - t_llm
            logger.info("xsell rag_answer ok items=%s llm_time=%.3fs", len(ranked), llm_dt)
        except Exception as e:
            logger.warning("xsell rag_answer failed; falling back to counts. err=%s", e)
            ranked = candidates
    else:
        ranked = candidates

    # 5) Truncate to requested limit and build RecoResult
    items: List[RecoItem] = []
    for r in ranked[:limit]:
        items.append(
            RecoItem(
                product_id=r.product_id,
                score=float(r.score),
                rationale=(getattr(r, "rationale", None) if include_rationale else None),
            )
        )
    result = RecoResult(source_product_id=product_id, count=len(items), items=items)

    # 6) Cache set (24h)
    try:
        await redis.set(cache_key, result.model_dump_json(), ex=ttl)
        logger.debug("xsell cache_set key=%s ttl=%s items=%s", cache_key, ttl, len(result.items))
    except Exception as e:
        logger.warning("xsell redis.set error key=%s err=%s", cache_key, e)

    total_dt = time.perf_counter() - t0
    logger.info("xsell done product_id=%s items=%s total_time=%.3fs", product_id, len(result.items), total_dt)
    return result