from __future__ import annotations
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query
from app.api.deps import mongo_db

from app.domain.services.last_seen_svc import get_last_seen_products_svc
from app.core.versioning import resolve_version

import logging
logger = logging.getLogger(__name__)

router = APIRouter(tags=["users"])

VersionDep = Annotated[str, Depends(resolve_version)]

@router.get("/users/{user_id}/last-seen-product")
async def get_last_seen_product(
    version: VersionDep,
    user_id: str,
    limit: int = Query(20, ge=1, le=100, description="Max number of last seen products to return"),
    db = Depends(mongo_db),
):
    """
    Return up to `limit` most recent VIEW events for this user.
    """
    logger.info(f"Request: last_seen_product user_id={user_id}, limit={limit}")
    res = await get_last_seen_products_svc(db=db, version=version, user_id=user_id, limit=limit)
    if not res or res.get("count", 0) == 0:
        raise HTTPException(status_code=404, detail="No view events found for this user.")
    logger.info(f"Response: get_last_seen_product: returned {res.get('count', 0)} items for user_id={user_id}")
    return res
