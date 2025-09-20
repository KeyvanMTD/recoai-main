# app/api/routers/products.py

from fastapi import APIRouter, Depends, Query, HTTPException
from app.api.deps import mongo_db, redis_dep
from typing import Annotated, List, Optional
import time

from app.core.versioning import resolve_version
from app.domain.repositories.vector_cache_repo import VectorCacheRepo
from app.domain.services.embedding_svc import batch_get_or_create_embeddings
from app.domain.services.constants import KIND_SIMILAR, KIND_COMPLEMENTARY

import logging
logger = logging.getLogger(__name__)

router = APIRouter(tags=["products"])

VersionDep = Annotated[str, Depends(resolve_version)]

## moved: similar and complementary routes are now in separate routers


class VectorizeRequestParams:
    # Placeholder to document defaults in OpenAPI (using Query on function params)
    pass

@router.post("/products/vectorize", summary="Vectorize existing products in the 'products' collection (any KINDs)")
async def vectorize_products(
    version: VersionDep,                              # resolved from X-API-Version
    force: bool = Query(False, description="Recompute even if cache/DB has vectors"),
    do_sim: bool = Query(True, description="Compute 'sim' vectors"),
    do_comp: bool = Query(True, description="Compute 'comp' vectors"),
    limit: Optional[int] = Query(None, ge=1, description="Max number of products to process"),
    openai_batch_size: int = Query(64, ge=1, le=2048, description="Max inputs per OpenAI call"),
    scan_batch_size: int = Query(500, ge=10, le=5000, description="DB scan and embedding batch size"),
    db = Depends(mongo_db),
    redis = Depends(redis_dep),
):
    """
    Scans the existing 'products' collection, gathers product_ids, and generates embeddings.
    Runs in batches to avoid memory spikes. Returns aggregated stats.
    """

    # Build selected kinds dynamically (agnostic to add future kinds)
    selected_kinds: List[str] = []
    if do_sim:
        selected_kinds.append(KIND_SIMILAR)
    if do_comp:
        selected_kinds.append(KIND_COMPLEMENTARY)
    if not selected_kinds:
        raise HTTPException(status_code=400, detail="Enable at least one embedding kind (e.g., do_sim or do_comp)")

    start = time.perf_counter()
    vector_cache = VectorCacheRepo(redis)
    col = db["products"]

    total_seen = 0
    ids_batch: List[str] = []

    # Aggregated stats per kind (agnostic)
    def _empty_stats() -> dict:
        return {"cache_hits": 0, "db_hits": 0, "embedded": 0, "errors": [], "missing_products": []}

    agg: dict[str, dict] = {k: _empty_stats() for k in selected_kinds}

    def add_stats(kind: str, st: dict):
        a = agg[kind]
        a["cache_hits"] += st.get("cache_hits", 0)
        a["db_hits"] += st.get("db_hits", 0)
        a["embedded"] += st.get("embedded", 0)
        a["errors"].extend(st.get("errors", []) or [])
        a["missing_products"].extend(st.get("missing_products", []) or [])

    async def process_ids_batch(batch_ids: List[str]):
        # For each selected kind, call the batch embedding function and merge stats
        for kind in selected_kinds:
            st = await batch_get_or_create_embeddings(
                db=db,
                cache=vector_cache,
                product_ids=batch_ids,
                kind=kind,
                force=force,
                write_back_db=True,
                hydrate_cache=True,
                openai_batch_size=openai_batch_size,
                scan_batch_size=scan_batch_size,
            )
            add_stats(kind, st)

    logger.info(
        f"[vectorize] start kinds={selected_kinds} force={force} "
        f"openai_batch_size={openai_batch_size} scan_batch_size={scan_batch_size} limit={limit}"
    )

    cursor = col.find({}, {"_id": 0, "product_id": 1})
    try:
        async for doc in cursor:
            pid = doc.get("product_id")
            if not pid:
                continue
            ids_batch.append(pid)
            total_seen += 1
            # stop after reaching limit (let the final flush handle remaining)
            if limit and total_seen >= limit:
                break
            if len(ids_batch) >= scan_batch_size:
                await process_ids_batch(ids_batch)
                ids_batch.clear()
    finally:
        # Ensure cursor is closed promptly
        try:
            await cursor.close()
        except Exception:
            pass

    # Flush remaining ids (partial batch)
    if ids_batch:
        await process_ids_batch(ids_batch)

    elapsed_ms = (time.perf_counter() - start) * 1000.0
    # Build a compact summary for logging
    summary = {k: {"embedded": agg[k]["embedded"], "cache": agg[k]["cache_hits"], "db": agg[k]["db_hits"]} for k in agg}
    logger.info(f"[vectorize] done seen={total_seen} summary={summary} time_ms={elapsed_ms:.1f}")

    # Backward-friendly response: include per-kind stats; keep sim/comp keys if present
    response = {
        "version": version,
        "seen": total_seen,
        "stats_by_kind": agg,
        "processing_time_ms": elapsed_ms,
    }
    if KIND_SIMILAR in agg:
        response["sim"] = agg[KIND_SIMILAR]
    if KIND_COMPLEMENTARY in agg:
        response["comp"] = agg[KIND_COMPLEMENTARY]
    return response
