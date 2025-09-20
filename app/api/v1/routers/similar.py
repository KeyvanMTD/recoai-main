# app/api/v1/routers/similar.py
from fastapi import APIRouter, Depends, Query
from typing import Annotated
import time
import logging

from app.api.deps import mongo_db, redis_dep
from app.core.versioning import resolve_version
from app.domain.services.similar_products_svc import get_similar_products_cached

logger = logging.getLogger(__name__)

router = APIRouter(tags=["similar"])

VersionDep = Annotated[str, Depends(resolve_version)]

@router.get("/products/{product_id}/similar")
async def similar_products(
    product_id: str,
    version: VersionDep,
    limit: int = Query(10, ge=1, le=50),
    use_text_fallback: bool = Query(True),
    use_llm_rerank: bool = Query(True),
    include_rationale: bool = Query(False, description="Include explanation for each recommendation"),
    db = Depends(mongo_db),
    redis = Depends(redis_dep),
):
    """
    Substitutable/similar products.
    Version is resolved via the X-API-Version header (1/v1 or 2/v2). Defaults to v1.
    Pipeline: vector cache → Atlas retrieval (50) → optional LLM re-rank → top-10 → cache.
    """
    logger.info(
        "Request: similar_products product_id=%s, version=%s, limit=%s, use_text_fallback=%s, use_llm_rerank=%s, include_rationale=%s",
        product_id, version, limit, use_text_fallback, use_llm_rerank, include_rationale,
    )

    start_time = time.perf_counter()

    res = await get_similar_products_cached(
        db=db,
        redis=redis,
        version=version,
        product_id=product_id,
        limit=limit,
        use_text_fallback=use_text_fallback,
        use_llm_rerank=use_llm_rerank,
        include_rationale=include_rationale,
    )

    elapsed_time = time.perf_counter() - start_time
    logger.info(
        "Response: similar_products product_id=%s, count=%s, elapsed_time=%.4fs",
        product_id, (len(res.items) if hasattr(res, "items") else "unknown"), elapsed_time,
    )
    return res.model_dump()

