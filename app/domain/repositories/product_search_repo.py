# app/domain/repositories/product_search_repo.py

from __future__ import annotations
from typing import Any, Dict, List, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase, AsyncIOMotorCollection

class ProductSearchRepo:
    """
    Repository for product search operations using MongoDB Atlas Search.
    Provides both vector search (semantic) and text search (keyword-based) capabilities.
    """

    # Name of the Atlas Vector Search index
    VECTOR_INDEX = "vector_index"

    # Name of the Atlas Text Search index
    TEXT_INDEX = "text_index"

    def __init__(self, db: AsyncIOMotorDatabase, collection_name: str = "products"):
        """
        Initialize the repository with a MongoDB collection reference.

        Args:
            db: AsyncIOMotorDatabase connection (provided via FastAPI dependency).
            collection_name: The MongoDB collection name containing product documents.
        """
        self.col: AsyncIOMotorCollection = db[collection_name]

    async def vector_search(
        self,
        query_vector: List[float],
        limit: int = 10,
        num_candidates: int = 200,
        exclude_product_id: Optional[str] = None,
        must_filters: Optional[Dict[str, Any]] = None,
        path: str = "vectors.sim.vector",
    ) -> List[Dict[str, Any]]:
        """
        Perform a semantic search using Atlas Vector Search.

        Args:
            query_vector: Vector representation (embedding) of the search query.
            limit: Maximum number of products to return.
            num_candidates: Number of candidate documents considered before scoring.
            exclude_product_id: Product ID to exclude from results (e.g., the source product).
            must_filters: Additional MongoDB filter conditions.

        Returns:
            List of product documents with similarity scores, sorted by score.
        """
        # Convert Atlas Search-style compound filters to MQL for $vectorSearch.filter
        def _to_mql(clause: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            if "equals" in clause:
                eq = clause["equals"]
                return {eq["path"]: eq.get("value")}
            if "range" in clause:
                r = clause["range"]
                ops: Dict[str, Any] = {}
                if "gt" in r: ops["$gt"] = r["gt"]
                if "gte" in r: ops["$gte"] = r["gte"]
                if "lt" in r: ops["$lt"] = r["lt"]
                if "lte" in r: ops["$lte"] = r["lte"]
                return {r["path"]: ops} if ops else None
            if "in" in clause:
                i = clause["in"]
                vals = i.get("values") or i.get("value") or []
                if not isinstance(vals, list):
                    vals = [vals]
                return {i["path"]: {"$in": vals}}
            if "exists" in clause:
                ex = clause["exists"]
                return {ex["path"]: {"$exists": bool(ex.get("value", True))}}
            return None

        filt: Optional[Dict[str, Any]] = None
        if must_filters:
            clauses = must_filters.get("compound", {}).get("filter", [])
            mql = [c for c in (_to_mql(c) for c in clauses) if c]
            if exclude_product_id:
                mql.append({"product_id": {"$ne": exclude_product_id}})
            if mql:
                filt = mql[0] if len(mql) == 1 else {"$and": mql}
        elif exclude_product_id:
            filt = {"product_id": {"$ne": exclude_product_id}}

        # Atlas Vector Search aggregation pipeline
        pipeline = [
            {
                "$vectorSearch": {
                    "exact": False,
                    "index": self.VECTOR_INDEX,
                    "path": path,  # e.g., "vectors.sim.vector"
                    "queryVector": query_vector,
                    "numCandidates": num_candidates,
                    "limit": limit,
                }
            }
        ]
        # Apply MQL filter after vector stage to avoid index filter requirement
        if filt:
            pipeline.append({"$match": filt})

        pipeline.extend([
            {"$addFields": {"score": {"$meta": "vectorSearchScore"}}},
            {
                "$project": {
                    "_id": 0,
                    "score": 1,
                    "product_id": 1,
                    "brand": 1,
                    "name": 1,
                    "description": 1,
                    "category_id": 1,
                }
            },
        ])

        # Execute aggregation and return results as a list of dicts
        cursor = self.col.aggregate(pipeline)
        return [doc async for doc in cursor]

    async def text_search_fallback(
        self,
        query_text: str,
        limit: int = 10,
        exclude_product_id: Optional[str] = None,
        must_filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Perform a traditional keyword-based search using Atlas Text Search.
        Used as a fallback when vector search is unavailable or returns no results.

        Args:
            query_text: Text query to match against product fields.
            limit: Maximum number of products to return.
            exclude_product_id: Product ID to exclude from results.
            must_filters: Additional MongoDB filter conditions.

        Returns:
            List of product documents with text search scores, sorted by score.
        """
        # Build filter conditions
        filt = must_filters or {}
        if exclude_product_id:
            filt = (
                {"$and": [filt, {"product_id": {"$ne": exclude_product_id}}]}
                if filt else {"product_id": {"$ne": exclude_product_id}}
            )

        # Atlas Text Search aggregation pipeline
        pipeline = [
            {
                "$search": {
                    "index": self.TEXT_INDEX,
                    "compound": {
                        "must": [
                            {
                                "text": {
                                    "query": query_text,
                                    "path": [
                                        "name",
                                        "description",
                                        "brand",
                                        "tags"
                                    ]
                                }
                            }
                        ],
                        "filter": [filt] if filt else []
                    }
                }
            },
            {"$addFields": {"score": {"$meta": "searchScore"}}},  # Attach text relevance score
            {
                "$project": {  # Control returned fields
                    "_id": 0,
                    "score": 1,
                    "product_id": 1,
                    "name": 1,
                    "brand": 1,
                    "current_price": 1,
                    "original_price": 1,
                    "currency": 1,
                    "category_id": 1,
                    "category_path": 1,
                    "image_url": 1,
                    "tags": 1,
                    "metadata": 1,
                }
            },
            {"$limit": limit}  # Ensure we return at most `limit` results
        ]

        # Execute aggregation and return results as a list of dicts
        cursor = self.col.aggregate(pipeline)
        return [doc async for doc in cursor]

    async def execute_atlas_search(
        self,
        search_query: Dict[str, Any],
        limit: int = 10,
        exclude_product_id: Optional[str] = None,
        projection: Optional[Dict[str, Any]] = None,
        mql_match: Optional[Dict[str, Any]] = None,  # <— add this
    ) -> List[Dict[str, Any]]:
        """
        Execute a generic Atlas Search query with the provided search configuration.
        Supports:
          - $search with text/compound (incl. knnBeta)
          - $vectorSearch stage (if vectorSearch operator is provided or detected nested)
        """
        # Apply product ID exclusion if specified (only for $search-style filters)
        if exclude_product_id and "compound" in search_query:
            if "filter" not in search_query["compound"]:
                search_query["compound"]["filter"] = []
            search_query["compound"]["filter"].append({
                "not": {"equals": {"path": "product_id", "value": exclude_product_id}}
            })

        # Helper to find a nested operator dict by key
        def _find_op(d: Any, key: str) -> Optional[Dict[str, Any]]:
            if isinstance(d, dict):
                if key in d and isinstance(d[key], dict):
                    return d[key]
                for v in d.values():
                    found = _find_op(v, key)
                    if found:
                        return found
            elif isinstance(d, list):
                for it in d:
                    found = _find_op(it, key)
                    if found:
                        return found
            return None

        pipeline: List[Dict[str, Any]] = []
        score_field = "searchScore"

        # 1) If a vectorSearch operator is present (even nested inside compound.must),
        #    build a $vectorSearch stage instead of $search (vectorSearch is not valid inside $search).
        vs_cfg = _find_op(search_query, "vectorSearch")
        if vs_cfg:
            # NOTE: $vectorSearch filter expects MQL, not Atlas Search compound filters.
            # If search_query carried compound.filter, we ignore it here (or convert externally).
            pipeline.append({
                "$vectorSearch": {
                    "index": self.VECTOR_INDEX,
                    **vs_cfg,  # contains: path, queryVector, numCandidates, limit, (optional) filter (MQL)
                }
            })
            score_field = "vectorSearchScore"
        else:
            # 2) If knnBeta is present, use $search with VECTOR_INDEX
            has_knn = _find_op(search_query, "knnBeta") is not None
            index_name = self.VECTOR_INDEX if has_knn else self.TEXT_INDEX
            pipeline.append({"$search": {"index": index_name, **search_query}})
            score_field = "searchScore"

        # Apply MQL filter AFTER $search (used with knnBeta on clusters without top-level filter)
        if mql_match:
            pipeline.append({"$match": mql_match})

        pipeline.extend([
            {"$addFields": {"score": {"$meta": "searchScore"}}},  # or "vectorSearchScore" if you switch
            {"$project": projection or {
                "_id": 0,
                "score": 1,
                "product_id": 1,
                "name": 1,
                "brand": 1,
                "current_price": 1,
                "original_price": 1,
                "currency": 1,
                "category_id": 1,
                "category_path": 1,
                "image_url": 1,
                "tags": 1,
                "metadata": 1,
            }},
            {"$limit": limit},
        ])

        try:
            cursor = self.col.aggregate(pipeline)
            return [doc async for doc in cursor]
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Atlas Search error: {e}")
            raise
