import time
from typing import List, Dict, Any, Optional
from app.core.config import get_settings
import hashlib
import json
import logging  # added

logger = logging.getLogger(__name__)  # added


def _json_preview(obj: Any, limit: int = 1000) -> str:
    """Minify and truncate JSON for debug logs."""
    try:
        s = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
        return s if len(s) <= limit else s[:limit] + "…[truncated]"
    except Exception:
        return "<unserializable>"

async def get_top_sales_svc(
    db,
    redis,
    version: str,
    limit: int = 20,
    brand: Optional[List[str]] = None,
    category_id: Optional[List[str]] = None,
) -> Dict[str, Any]:
    start_time = time.perf_counter()
    logger.info("top_sales start limit=%s brand=%s category_id=%s", limit, brand, category_id)
    settings = get_settings()

    # Build a cache key based on parameters (include version + shape to avoid mixing formats)
    cache_key_data = {
        "v": version,
        "shape": "items_pid_count_v1",
        "limit": limit,
        "brand": brand,
        "category_id": category_id,
    }
    cache_key = "top_sales:" + hashlib.md5(json.dumps(cache_key_data, sort_keys=True, default=str).encode()).hexdigest()
    logger.debug("top_sales cache_key=%s data=%s", cache_key, _json_preview(cache_key_data))

    # Try to get from cache
    try:
        cached = await redis.get(cache_key)
    except Exception as e:
        logger.warning("top_sales redis.get error key=%s err=%s", cache_key, e)
        cached = None

    if cached:
        try:
            cached_obj = json.loads(cached)
            # New shape already
            if isinstance(cached_obj, dict) and "items" in cached_obj and "count" in cached_obj:
                logger.info("top_sales cache_hit key=%s items=%s", cache_key, cached_obj.get("count"))
                return cached_obj
            # Legacy shape -> adapt: {"items":[{product_id, units, orders}], "_meta": {...}}
            if isinstance(cached_obj, dict) and "items" in cached_obj and isinstance(cached_obj["items"], list):
                items_simple = [{"product_id": it.get("product_id")} for it in cached_obj["items"] if it.get("product_id")]
                result_simple = {"items": items_simple, "count": len(items_simple)}
                logger.info("top_sales cache_hit(legacy) key=%s items=%s", cache_key, result_simple["count"])
                # Optionally upgrade cache
                try:
                    await redis.set(cache_key, json.dumps(result_simple), ex=settings.top_sales_cache_ttl)
                except Exception:
                    pass
                return result_simple
        except Exception as e:
            logger.warning("top_sales cache decode error key=%s err=%s", cache_key, e)

    logger.info("top_sales cache_miss key=%s", cache_key)

    pipeline: List[Dict[str, Any]] = [
        {"$match": {"event_type": "purchase"}},
        {"$addFields": {"q": {"$cond": [{"$ifNull": ["$metadata.quantity", False]}, "$metadata.quantity", 1]}}},
        {"$lookup": {
            "from": "products",
            "localField": "product_id",
            "foreignField": "product_id",
            "as": "prod"
        }},
        {"$unwind": {"path": "$prod", "preserveNullAndEmptyArrays": False}},
    ]

    post_lookup: Dict[str, Any] = {}
    if brand:
        post_lookup["prod.brand"] = {"$in": brand}
    if category_id:
        post_lookup["prod.category_id"] = {"$in": category_id}
    if post_lookup:
        pipeline.append({"$match": post_lookup})

    # Keep ordering by most units (then orders)
    pipeline += [
        {"$group": {
            "_id": {"product_id": "$product_id"},
            "units": {"$sum": "$q"},
            "orders": {"$sum": 1}
        }},
        {"$sort": {"units": -1, "orders": -1}},
        {"$limit": limit},
        {"$project": {
            "_id": 0,
            "product_id": "$_id.product_id",
            "units": 1,
            "orders": 1
        }}
    ]
    
    logger.debug("top_sales pipeline=%s", _json_preview(pipeline, limit=2000))

    db_t0 = time.perf_counter()
    docs = await db["events"].aggregate(pipeline).to_list(length=None)
    db_dt = time.perf_counter() - db_t0
    logger.info("top_sales db_ok items=%s db_time=%.3fs", len(docs), db_dt)

    # Transform to simple shape: keep only product_id, preserve order
    items = [{"product_id": d["product_id"]} for d in docs if d.get("product_id")]
    result = {"items": items, "count": len(items)}

    # Store in cache (TTL from settings)
    try:
        payload = json.dumps(result, default=str)
        await redis.set(cache_key, payload, ex=settings.top_sales_cache_ttl)
        logger.debug("top_sales cache_set key=%s ttl=%ds bytes=%s", cache_key, settings.top_sales_cache_ttl, len(payload))
    except Exception as e:
        logger.warning("top_sales redis.set error key=%s err=%s", cache_key, e)

    logger.info("top_sales done items=%s total_time=%.3fs", len(items), time.perf_counter() - start_time)
    return result


'''
TODO:

## What “denormalize brand/category\_id onto purchase events” means

Right now your `/top-sales` pipeline does:

1. `$match` purchase events
2. **`$lookup` products** to get `brand` / `category_id` for filtering
3. `$group` to count units

That `$lookup` is a cross-collection join. At scale (millions of events), joins add latency and can blow the 100 ms budget.

**Denormalization** = copy the tiny bits of product metadata you filter on (here: `brand`, `category_id`) **into the purchase event document at write time**, so queries don’t need a join.

### Before (normalized event)

```json
{
  "event_type": "purchase",
  "product_id": "prod_abc",
  "timestamp": "...",
  "metadata": { "quantity": 2, "basket_id": "b_123" }
  // brand/category live ONLY in products collection
}
```

### After (denormalized event)

```json
{
  "event_type": "purchase",
  "product_id": "prod_abc",
  "product_brand": "Samsung",        // <- copied at write time
  "product_category_id": "cat_tv_audio",
  "timestamp": "...",
  "metadata": { "quantity": 2, "basket_id": "b_123" }
}
```

Now the query can be **single-collection** (events only), no `$lookup`.

---

## Why this hits <100 ms

* One collection scan with selective index → `$match` + `$group` only.
* Memory locality is better; less pipeline orchestration.
* Indexes on `{ event_type, product_category_id }` or `{ event_type, product_brand }` get you right to the slice.

---

## Minimal schema change (purchase only)

You don’t need to denormalize on every event type. Do it **only for `purchase`** (and optionally `add_to_cart` if you’ll filter it too).

Fields to add:

* `product_brand` (string)
* `product_category_id` (string)

Keep `product_id` as the source of truth.

---

## Write-path enrichment (FastAPI / backend)

When you receive a purchase event:

1. Read the product once (from cache ideally)
2. Stamp `product_brand` + `product_category_id` into the event
3. Insert the event

```python
# pseudo
prod = await db.products.find_one({"product_id": product_id}, {"brand":1, "category_id":1})
event = {
  "event_type": "purchase",
  "product_id": product_id,
  "product_brand": prod["brand"],
  "product_category_id": prod["category_id"],
  "timestamp": ts,
  "metadata": {...}
}
await db.events.insert_one(event)
```

Use a small in-process cache (LRU) for product facets to avoid round-trips per event.

---

## Migration / backfill (one-time)

Backfill existing purchases so the endpoint can drop `$lookup` immediately.

```javascript
// 1) Build a local map (server-side script) or do a $lookup + $merge
db.events.aggregate([
  { $match: { event_type: "purchase" } },
  { $lookup: {
      from: "products",
      localField: "product_id",
      foreignField: "product_id",
      as: "p"
  }},
  { $unwind: "$p" },
  { $set: {
      product_brand: "$p.brand",
      product_category_id: "$p.category_id"
  }},
  { $project: { p: 0 } },
  { $merge: { into: "events", on: "_id", whenMatched: "merge", whenNotMatched: "discard" } }
])
```

---

## New indexes (critical)

```javascript
db.events.createIndex({ event_type: 1, product_id: 1 })                   // always useful
db.events.createIndex({ event_type: 1, product_brand: 1 })                // brand-filtered top sales
db.events.createIndex({ event_type: 1, product_category_id: 1 })          // category-filtered top sales
```

---

## Endpoint without `$lookup`

```python
@router.get("/top-sales")
async def get_top_sales(
    db: AsyncIOMotorDatabase = Depends(get_db),
    limit: int = Query(20, ge=1, le=200),
    brand: Optional[List[str]] = Query(None),
    category_id: Optional[List[str]] = Query(None),
):
    match = {"event_type": "purchase"}
    if brand:
        match["product_brand"] = {"$in": brand}
    if category_id:
        match["product_category_id"] = {"$in": category_id}

    pipeline = [
        {"$match": match},
        {"$addFields": {
            "q": {"$cond": [{"$ifNull": ["$metadata.quantity", False]}, "$metadata.quantity", 1]}
        }},
        {"$group": {
            "_id": {"product_id": "$product_id"},
            "units": {"$sum": "$q"},
            "orders": {"$sum": 1}
        }},
        {"$sort": {"units": -1, "orders": -1}},
        {"$limit": limit},
        {"$project": {"_id": 0, "product_id": "$_id.product_id", "units": 1, "orders": 1}}
    ]
    return {"items": await db["events"].aggregate(pipeline).to_list(None)}
```

This is lean and fast.

---

## Trade-offs (the honest bits)

* **Pros**

  * Latency drops dramatically (no join).
  * Query code is simpler and more robust.
* **Cons**

  * **Redundancy**: brand/category are duplicated per purchase event.
  * **Drift**: if a product changes brand/category later, historical events won’t update (which is usually **what you want** for analytics—events are a historical fact). If you do want retro updates, rerun the backfill.

**Storage cost** is minimal: two short strings per purchase document.

---

## Alternatives if you don’t want denormalization

1. **Materialized view**: keep a `top_sales_daily` collection updated by a batch job or Change Streams; your GET reads pre-aggregated rows.
2. **Cached join**: maintain an in-memory map `product_id -> {brand, category}` in the service; still do an `$match` on events only, but you’ll lose server-side filtering by brand/category unless you also store those fields in events (which… is denormalization).

---

## Recommendation

For your stated goal (counting units and filtering by brand/category with **tight latency**), denormalize **just those two fields** onto **`purchase`** events and index them. It’s the cleanest design with the best performance/complexity ratio.


'''