from fastapi import APIRouter, Depends, Query
from app.api.deps import mongo_db, redis_dep
from typing import Annotated, List, Optional
from app.domain.services.top_sales_svc import get_top_sales_svc
from app.core.versioning import resolve_version

import logging
import time
logger = logging.getLogger(__name__)

router = APIRouter(tags=["top-sales"])

VersionDep = Annotated[str, Depends(resolve_version)]

@router.get("/top-sales")
async def get_top_sales(
    version: VersionDep,
    limit: int = Query(20, ge=1, le=200),
    brand: Optional[List[str]] = Query(None),
    category_id: Optional[List[str]] = Query(None),
    db = Depends(mongo_db),
    redis = Depends(redis_dep),
):
    t0 = time.perf_counter()
    result = await get_top_sales_svc(db, redis, version, limit, brand, category_id)
    dt = time.perf_counter() - t0

    items = result.get("items", [])
    count = result.get("count", len(items))
    logger.info(
        "Response: get_top_sales returned %s items (count=%s) in %.4fs with filters brand=%s, category_id=%s",
        len(items), count, dt, brand, category_id
    )
    return result
