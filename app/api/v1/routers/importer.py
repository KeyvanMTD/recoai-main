from fastapi import APIRouter, UploadFile, File, Query, HTTPException
from fastapi import Depends
from typing import Optional, List, Dict, Any
import json
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.db.mongo import get_db
from pymongo import UpdateOne
import logging
from pymongo.errors import ServerSelectionTimeoutError, AutoReconnect, ConnectionFailure

router = APIRouter(prefix="/import", tags=["import"])

# Local limits/defaults (replace settings.*)
DEFAULT_BATCH_SIZE = 1000         # default batch size for bulk writes
MAX_JSON_ARRAY_MB = 5             # max allowed size for JSON array uploads (in MB)

logger = logging.getLogger(__name__)

def _is_probably_jsonl(first_bytes: bytes) -> bool:
    # Heuristic: JSON array starts with '[' (maybe after whitespace), JSONL not
    s = first_bytes.lstrip()
    return not s.startswith(b"[")

# Stream using async reads (UploadFile doesn't implement __aiter__)
CHUNK_SIZE = 64 * 1024  # 64KB

async def _iter_bytes(upload: UploadFile, chunk_size: int = CHUNK_SIZE):
    while True:
        chunk = await upload.read(chunk_size)
        if not chunk:
            break
        yield chunk

async def _iter_jsonl(upload: UploadFile):
    # Kept for compatibility; yields raw chunks (not line-split)
    async for chunk in _iter_bytes(upload):
        yield chunk

async def _stream_jsonl_docs(upload: UploadFile):
    # Re-buffer chunks into lines and yield parsed JSON objects
    await upload.seek(0)
    buffer = b""
    async for chunk in _iter_bytes(upload):
        buffer += chunk
        while True:
            nl = buffer.find(b"\n")
            if nl == -1:
                break
            line = buffer[:nl]
            buffer = buffer[nl + 1 :]
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as e:
                raise HTTPException(status_code=400, detail=f"Invalid JSONL line: {e}")
    tail = buffer.strip()
    if tail:
        try:
            yield json.loads(tail)
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSONL tail: {e}")

async def _bulk_insert(
    db: AsyncIOMotorDatabase,
    collection_name: str,
    docs_iter,
    batch_size: int,
    ordered: bool
) -> dict:
    col = db[collection_name]
    total = 0
    batch: List[Dict[str, Any]] = []
    async for doc in docs_iter:
        batch.append(doc)
        if len(batch) >= batch_size:
            try:
                res = await col.insert_many(batch, ordered=ordered)
            except (ServerSelectionTimeoutError, AutoReconnect, ConnectionFailure) as e:
                logger.error(f"[import] insert_many batch failed: {e}")
                raise HTTPException(status_code=503, detail="MongoDB unavailable (connection/TLS).")
            total += len(res.inserted_ids)
            batch.clear()
    if batch:
        try:
            res = await col.insert_many(batch, ordered=ordered)
        except (ServerSelectionTimeoutError, AutoReconnect, ConnectionFailure) as e:
            logger.error(f"[import] insert_many final batch failed: {e}")
            raise HTTPException(status_code=503, detail="MongoDB unavailable (connection/TLS).")
        total += len(res.inserted_ids)
    return {"inserted_count": total}

async def _bulk_upsert(
    db: AsyncIOMotorDatabase,
    collection_name: str,
    docs_iter,
    id_field: str,
    batch_size: int,
    ordered: bool
) -> dict:
    col = db[collection_name]
    total_upserts = 0
    total_modified = 0

    ops: List[UpdateOne] = []
    async for doc in docs_iter:
        if id_field not in doc:
            raise HTTPException(status_code=400, detail=f"Field '{id_field}' missing in a document for upsert.")
        key_val = doc[id_field]
        filt = {id_field: key_val}
        ops.append(UpdateOne(filt, {"$set": doc}, upsert=True))
        if len(ops) >= batch_size:
            try:
                res = await col.bulk_write(ops, ordered=ordered)
            except (ServerSelectionTimeoutError, AutoReconnect, ConnectionFailure) as e:
                logger.error(f"[import] bulk_write batch failed: {e}")
                raise HTTPException(status_code=503, detail="MongoDB unavailable (connection/TLS).")
            total_upserts += res.upserted_count or 0
            total_modified += res.modified_count or 0
            ops.clear()
    if ops:
        try:
            res = await col.bulk_write(ops, ordered=ordered)
        except (ServerSelectionTimeoutError, AutoReconnect, ConnectionFailure) as e:
            logger.error(f"[import] bulk_write final batch failed: {e}")
            raise HTTPException(status_code=503, detail="MongoDB unavailable (connection/TLS).")
        total_upserts += res.upserted_count or 0
        total_modified += res.modified_count or 0

    return {"upserted_count": total_upserts, "modified_count": total_modified}

@router.post("")
async def import_json(
    file: UploadFile = File(..., description="JSON array (.json) or JSONL/NDJSON (.jsonl/.ndjson)."),
    db_name: Optional[str] = Query(None, description="Database name. Defaults to config DEFAULT_DB."),
    collection: str = Query(..., description="Target collection name (will be created if it doesn't exist)."),
    mode: str = Query("insert", regex="^(insert|upsert)$", description="insert | upsert"),
    id_field: Optional[str] = Query(None, description="Field used for upsert match (required for mode=upsert)."),
    drop_existing: bool = Query(False, description="Drop the collection before import."),
    ordered: bool = Query(False, description="Mongo ordered writes. False is faster and continues on errors."),
    batch_size: int = Query(DEFAULT_BATCH_SIZE, ge=1, le=10000, description="Batch size for bulk writes."),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    database: AsyncIOMotorDatabase = db.client[db_name] if db_name else db

    # Fail fast if Mongo is unreachable
    try:
        await database.command({"ping": 1})
    except (ServerSelectionTimeoutError, AutoReconnect, ConnectionFailure, Exception) as e:
        logger.error(f"[import] MongoDB ping failed: {e}")
        raise HTTPException(status_code=503, detail="MongoDB unavailable (connection/TLS).")

    if drop_existing:
        await database.drop_collection(collection)

    # Peek to decide JSON vs JSONL
    head = await file.read(512)
    await file.seek(0)

    is_jsonl = _is_probably_jsonl(head)
    col = database[collection]

    if mode == "upsert" and not id_field:
        raise HTTPException(status_code=400, detail="id_field is required for mode=upsert.")

    if is_jsonl:
        # Stream JSONL to avoid memory blowups
        docs_iter = _stream_jsonl_docs(file)
        result = await (_bulk_upsert(database, collection, docs_iter, id_field, batch_size, ordered)
                        if mode == "upsert" else
                        _bulk_insert(database, collection, docs_iter, batch_size, ordered))
        return {
            "collection": collection,
            "format": "jsonl",
            "mode": mode,
            **result
        }

    # JSON array path: guard size, then parse
    size = 0
    if hasattr(file, "size") and file.size is not None:
        size = int(file.size)
    else:
        # If size unknown, we will enforce limit after reading content
        size = 0

    # hard stop to avoid accidental OOMs on giant arrays
    if size and size > MAX_JSON_ARRAY_MB * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"JSON array too large (> {MAX_JSON_ARRAY_MB} MB). Prefer JSONL."
        )

    content = await file.read()
    # Enforce limit if size was unknown
    if not size and len(content) > MAX_JSON_ARRAY_MB * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"JSON array too large (> {MAX_JSON_ARRAY_MB} MB). Prefer JSONL."
        )
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON array: {e}")

    if not isinstance(data, list):
        raise HTTPException(status_code=400, detail="Top-level JSON must be an array or send JSONL.")

    async def _array_iter():
        for doc in data:
            yield doc

    docs_iter = _array_iter()
    result = await (_bulk_upsert(database, collection, docs_iter, id_field, batch_size, ordered)
                    if mode == "upsert" else
                    _bulk_insert(database, collection, docs_iter, batch_size, ordered))

    return {
        "collection": collection,
        "format": "json_array",
        "mode": mode,
        **result
    }


'''
Usage
1) Import JSONL/NDJSON (recommended: streaming, memory‑safe)
curl -X POST "http://localhost:8000/import?collection=products&mode=insert&ordered=false" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@products_5000.jsonl;type=application/x-ndjson"

2) Upsert JSONL by custom key (e.g., product_id)
curl -X POST "http://localhost:8000/import?collection=products&mode=upsert&id_field=product_id" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@products_5000.jsonl;type=application/x-ndjson"

3) Import a JSON array (small/medium files only)
curl -X POST "http://localhost:8000/import?collection=products" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@products_5000.json;type=application/json"

4) Drop & recreate collection before import
curl -X POST "http://localhost:8000/import?collection=products&drop_existing=true" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@products_5000.jsonl;type=application/x-ndjson"

Opinionated guidance (no BS)

Prefer JSONL/NDJSON for anything beyond a few MB. Arrays require buffering the whole payload; JSONL streams doc‑by‑doc, which is safer and faster for big imports.

Use ordered=false to keep going on bad docs (like mongoimport --maintainInsertionOrder=false behavior).

Upsert mode: specify id_field (e.g., product_id). The code uses UpdateOne(..., upsert=True) bulk writes.

If you need schema validation before insert/upsert, add a Pydantic model and validate inside the iterators.

For indexing, create indexes after the import to speed up ingestion, or pre‑create only the critical unique key index (e.g., product_id) when using upsert.
'''
