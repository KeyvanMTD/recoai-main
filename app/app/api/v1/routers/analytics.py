from fastapi import APIRouter, Query, Depends
from datetime import date, datetime, timezone, timedelta
from typing import List, Any, Dict

from app.api.v1.deps import get_db  # <- adapte si ton deps est ailleurs
from motor.motor_asyncio import AsyncIOMotorDatabase

router = APIRouter(prefix="/analytics", tags=["analytics"])

def _as_utc_day_end(d: date) -> datetime:
    # inclusif jusqu'à 23:59:59.999 du jour
    return datetime(d.year, d.month, d.day, 23, 59, 59, 999000, tzinfo=timezone.utc)

def _as_utc_day_start(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=timezone.utc)

@router.get("/health")
async def analytics_health():
    return {"ok": True}

# --- 1) KPIs synthèse (vues totales, ventes estimées, trend, latency p95) ---
@router.get("/summary")
async def analytics_summary(
    tenant: str = Query(...),
    date_from: date = Query(...),
    date_to: date = Query(...),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    start = _as_utc_day_start(date_from)
    end = _as_utc_day_end(date_to)

    # vues totales
    views = await db["events"].count_documents({
        "tenant": tenant,
        "type": "view",
        "ts": {"$gte": start, "$lte": end},
    })

    # ventes estimées (somme quantity * price)
    pipeline_sales = [
        {"$match": {
            "tenant": tenant, "type": "purchase",
            "ts": {"$gte": start, "$lte": end}
        }},
        {"$group": {
            "_id": None,
            "revenue": {"$sum": {"$multiply": ["$quantity", "$price"]}},
            "orders": {"$sum": "$quantity"}
        }},
    ]
    sales_agg = [x async for x in db["events"].aggregate(pipeline_sales)]
    revenue = float(sales_agg[0]["revenue"]) if sales_agg else 0.0
    orders = int(sales_agg[0]["orders"]) if sales_agg else 0

    # tendance simple = (vues 2e moitié - vues 1re moitié)
    span = end - start
    mid = start + timedelta(seconds=span.total_seconds() / 2)

    first_half = await db["events"].count_documents({
        "tenant": tenant, "type": "view",
        "ts": {"$gte": start, "$lte": mid},
    })
    second_half = await db["events"].count_documents({
        "tenant": tenant, "type": "view",
        "ts": {"$gt": mid, "$lte": end},
    })
    trend = second_half - first_half

    # latency p95 depuis runs (si tu les enregistres)
    run = await db["runs"].find_one(
        {"tenant": tenant},
        sort=[("created_at", -1)],
        projection={"latency_ms_p95": 1, "_id": 0},
    )
    latency_p95 = run.get("latency_ms_p95") if run else None

    return {
        "tenant": tenant,
        "date_from": start,
        "date_to": end,
        "views_total": views,
        "estimated_sales": revenue,
        "trend": trend,
        "latency_p95_ms": latency_p95,
        "orders": orders,
    }

# --- 2) Top vus ---
@router.get("/top-seen")
async def analytics_top_seen(
    tenant: str = Query(...),
    date_from: date = Query(...),
    date_to: date = Query(...),
    limit: int = Query(10, ge=1, le=100),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    start = _as_utc_day_start(date_from)
    end = _as_utc_day_end(date_to)

    pipeline = [
        {"$match": {
            "tenant": tenant,
            "type": "view",
            "ts": {"$gte": start, "$lte": end},
        }},
        {"$group": {"_id": "$product_id", "views": {"$sum": 1}}},
        {"$sort": {"views": -1}},
        {"$limit": limit},
        {"$lookup": {
            "from": "products",
            "let": {"pid": "$_id"},
            "pipeline": [
                {"$match": {"$expr": {
                    "$and": [
                        {"$eq": ["$tenant", tenant]},
                        {"$eq": ["$product_id", "$$pid"]},
                    ]
                }}},
                {"$project": {
                    "_id": 0, "product_id": 1, "name": 1,
                    "image_url": 1, "current_price": 1, "brand": 1,
                    "category_path": 1
                }},
            ],
            "as": "product"
        }},
        {"$unwind": {"path": "$product", "preserveNullAndEmptyArrays": True}},
        {"$project": {
            "_id": 0,
            "product_id": "$_id",
            "views": 1,
            "product": "$product"
        }},
    ]
    items = [x async for x in db["events"].aggregate(pipeline)]
    return {"items": items}

# --- 3) Top ventes ---
@router.get("/top-sales")
async def analytics_top_sales(
    tenant: str = Query(...),
    date_from: date = Query(...),
    date_to: date = Query(...),
    limit: int = Query(10, ge=1, le=100),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    start = _as_utc_day_start(date_from)
    end = _as_utc_day_end(date_to)

    pipeline = [
        {"$match": {
            "tenant": tenant,
            "type": "purchase",
            "ts": {"$gte": start, "$lte": end},
        }},
        {"$group": {
            "_id": "$product_id",
            "units": {"$sum": "$quantity"},
            "revenue": {"$sum": {"$multiply": ["$quantity", "$price"]}},
        }},
        {"$sort": {"revenue": -1}},
        {"$limit": limit},
        {"$lookup": {
            "from": "products",
            "let": {"pid": "$_id"},
            "pipeline": [
                {"$match": {"$expr": {
                    "$and": [
                        {"$eq": ["$tenant", tenant]},
                        {"$eq": ["$product_id", "$$pid"]},
                    ]
                }}},
                {"$project": {
                    "_id": 0, "product_id": 1, "name": 1,
                    "image_url": 1, "current_price": 1, "brand": 1,
                    "category_path": 1
                }},
            ],
            "as": "product"
        }},
        {"$unwind": {"path": "$product", "preserveNullAndEmptyArrays": True}},
        {"$project": {
            "_id": 0,
            "product_id": "$_id",
            "units": 1,
            "revenue": 1,
            "product": "$product"
        }},
    ]
    items = [x async for x in db["events"].aggregate(pipeline)]
    return {"items": items}

# --- 4) Vues par jour ---
@router.get("/trends/daily")
async def analytics_trends_daily(
    tenant: str = Query(...),
    date_from: date = Query(...),
    date_to: date = Query(...),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    start = _as_utc_day_start(date_from)
    end = _as_utc_day_end(date_to)

    pipeline = [
        {"$match": {
            "tenant": tenant,
            "type": "view",
            "ts": {"$gte": start, "$lte": end},
        }},
        {"$group": {
            "_id": {"$dateTrunc": {"date": "$ts", "unit": "day"}},
            "views": {"$sum": 1}
        }},
        {"$sort": {"_id": 1}},
        {"$project": {"_id": 0, "date": "$_id", "views": 1}}
    ]
    points = [x async for x in db["events"].aggregate(pipeline)]
    return {"points": points}

# --- 5) Part de marques & catégories (facultatif mais sexy) ---
@router.get("/share/brands")
async def analytics_brand_share(
    tenant: str = Query(...),
    date_from: date = Query(...),
    date_to: date = Query(...),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    start = _as_utc_day_start(date_from)
    end = _as_utc_day_end(date_to)

    pipeline = [
        {"$match": {
            "tenant": tenant,
            "type": "view",
            "ts": {"$gte": start, "$lte": end},
        }},
        {"$lookup": {
            "from": "products",
            "localField": "product_id",
            "foreignField": "product_id",
            "as": "p"
        }},
        {"$unwind": "$p"},
        {"$match": {"p.tenant": tenant}},
        {"$group": {"_id": "$p.brand", "views": {"$sum": 1}}},
        {"$sort": {"views": -1}},
        {"$limit": limit},
        {"$project": {"_id": 0, "brand": "$_id", "views": 1}}
    ]
    items = [x async for x in db["events"].aggregate(pipeline)]
    return {"items": items}
