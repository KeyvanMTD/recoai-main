from fastapi import APIRouter, Query
from datetime import date

router = APIRouter(prefix="/analytics", tags=["analytics"])

@router.get("/health")
def analytics_health():
    return {"ok": True}

@router.get("/summary")
def analytics_summary(
    tenant: str = Query(...),
    date_from: date = Query(...),
    date_to: date = Query(...),
):
    # TODO: ajouter la logique réelle plus tard
    return {
        "tenant": tenant,
        "date_from": str(date_from),
        "date_to": str(date_to),
        "views_total": 0,
        "estimated_sales": 0,
        "trend": 0,
        "latency_p95_ms": 0
    }

@router.get("/top-seen")
def analytics_top_seen(
    tenant: str = Query(...),
    date_from: date = Query(...),
    date_to: date = Query(...),
    limit: int = Query(10),
):
    return {"items": []}

@router.get("/top-sales")
def analytics_top_sales(
    tenant: str = Query(...),
    date_from: date = Query(...),
    date_to: date = Query(...),
    limit: int = Query(10),
):
    return {"items": []}

@router.get("/trends/daily")
def analytics_trends_daily(
    tenant: str = Query(...),
    date_from: date = Query(...),
    date_to: date = Query(...),
):
    return {"points": []}
