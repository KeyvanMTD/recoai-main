import logging
import time
import json
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

def _json_preview(obj: Any, limit: int = 1000) -> str:
    """Minify and truncate JSON for debug logs."""
    try:
        s = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
        return s if len(s) <= limit else s[:limit] + "…[truncated]"
    except Exception:
        return "<unserializable>"

async def get_last_seen_products_svc(
    db,
    version,
    user_id: str,
    limit: int = 20,
) -> Dict[str, Any]:
    t0 = time.perf_counter()
    logger.info("last_seen start user_id=%s limit=%s", user_id, limit)

    # Return unique product_ids seen by the user, ordered by most recent view timestamp (desc)
    pipeline = [
        {"$match": {"event_type": "view", "user_id": user_id}},
        {"$addFields": {"ts": {"$toDate": "$timestamp"}}},
        {"$group": {"_id": "$product_id", "last_seen_at": {"$max": "$ts"}}},
        {"$sort": {"last_seen_at": -1}},
        {"$limit": limit},
        {"$project": {"_id": 0, "product_id": "$_id"}},
    ]
    logger.debug("last_seen pipeline=%s", _json_preview(pipeline, limit=2000))

    db_t0 = time.perf_counter()
    docs = await db["events"].aggregate(pipeline).to_list(length=limit)
    db_dt = time.perf_counter() - db_t0
    logger.info("last_seen db_ok items=%s db_time=%.3fs", len(docs), db_dt)

    # Preview product_ids
    ids = [d.get("product_id") for d in docs]
    logger.debug("last_seen product_ids=%s", ids[:50])

    # Shape result as {items: [{product_id}], count: N}
    items = [{"product_id": d.get("product_id")} for d in docs if d.get("product_id")]

    total_dt = time.perf_counter() - t0
    logger.info("last_seen done items=%s total_time=%.3fs", len(items), total_dt)
    return {"items": items, "count": len(items)}
