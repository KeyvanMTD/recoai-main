# app/routers/xsell.py
from fastapi import APIRouter, HTTPException, Query, Depends
from typing import Annotated, List, Optional
from app.api.deps import mongo_db, redis_dep
from app.core.versioning import resolve_version
from app.domain.services.xsell_svc import get_xsell_products_cached_for_product
from app.domain.models.product import RecoResult  

router = APIRouter(tags=["xsell"])

VersionDep = Annotated[str, Depends(resolve_version)]

@router.get("/products/{product_id}/x-sell", response_model=RecoResult)
async def x_sell(
    version: VersionDep,
    product_id: str,
    user_id: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=200),
    use_llm_rerank: bool = Query(True),
    include_rationale: bool = Query(False),
    brand: Optional[str] = Query(None, description="Filter by product brand"),
    category_id: Optional[str] = Query(None, description="Filter by product category_id"),
    exclude_already_purchased: bool = Query(True, description="Ignore items user already purchased"),
    exclude_already_in_cart: bool = Query(True, description="Ignore items user already added to cart"),
    db = Depends(mongo_db),
    redis = Depends(redis_dep),
) -> RecoResult:
    result = await get_xsell_products_cached_for_product(
        db,
        redis,
        version=version,
        product_id=product_id,
        user_id=user_id,
        limit=limit,
        use_llm_rerank=use_llm_rerank,
        include_rationale=include_rationale,
        brand=brand,
        category_id=category_id,
        exclude_already_purchased=exclude_already_purchased,
        exclude_already_in_cart=exclude_already_in_cart,
    )
    return result
