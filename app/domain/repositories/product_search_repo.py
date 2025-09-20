# app/domain/repositories/product_search_repo.py
from __future__ import annotations
from typing import Any, Dict, List, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase, AsyncIOMotorCollection


class ProductSearchRepo:
    """
    MongoDB Atlas Search: vector ($vectorSearch / knnBeta) + texte (fallback).
    """

    VECTOR_INDEX = "vector_index"
    TEXT_INDEX = "text_index"

    def __init__(self, db: AsyncIOMotorDatabase, collection_name: str = "products"):
        self.col: AsyncIOMotorCollection = db[collection_name]

    # ---------- Utils ----------
    @staticmethod
    def _to_mql(clause: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convertit une clause style Atlas Search (equals/range/in/exists) en MQL pour $match/$vectorSearch.filter."""
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
        # NOTE: la conversion d'un "not" en MQL dépend du contenu interne et reste non triviale;
        # on l'ignore ici car on ne l'utilise que côté $search (pas côté $vectorSearch.filter).
        return None

    @staticmethod
    def _mql_from_compound_filter(
        must_filters: Optional[Dict[str, Any]],
        exclude_product_id: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """Compose un $match MQL à partir d'un compound.filter potentiel + exclusion d'un product_id."""
        mql_parts: List[Dict[str, Any]] = []

        if must_filters:
            comp = must_filters.get("compound")
            if isinstance(comp, dict):
                clauses = comp.get("filter") or []
                for c in clauses:
                    conv = ProductSearchRepo._to_mql(c)
                    if conv:
                        mql_parts.append(conv)

        if exclude_product_id:
            mql_parts.append({"product_id": {"$ne": exclude_product_id}})

        if not mql_parts:
            return None
        return mql_parts[0] if len(mql_parts) == 1 else {"$and": mql_parts}

    # ---------- Vector search ----------
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
        Recherche sémantique via $vectorSearch. Filtre MQL appliqué après.
        """
        mql_match = self._mql_from_compound_filter(must_filters, exclude_product_id)

        pipeline: List[Dict[str, Any]] = [
            {
                "$vectorSearch": {
                    "index": self.VECTOR_INDEX,
                    "path": path,
                    "queryVector": query_vector,
                    "numCandidates": num_candidates,
                    "limit": limit,
                }
            }
        ]
        if mql_match:
            pipeline.append({"$match": mql_match})

        pipeline += [
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
                    "image_url": 1,
                    "tags": 1,
                    "metadata": 1,
                }
            },
        ]

        cursor = self.col.aggregate(pipeline)
        return [doc async for doc in cursor]

    # ---------- Text fallback ----------
    async def text_search_fallback(
        self,
        query_text: str,
        limit: int = 10,
        exclude_product_id: Optional[str] = None,
        must_filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Recherche full-text via $search (index texte). **Ne jamais** mettre `filter: []`.
        """
        # MQL pour exclusion et filtres simples après $search
        mql_match = self._mql_from_compound_filter(must_filters, exclude_product_id)

        compound: Dict[str, Any] = {
            "must": [
                {
                    "text": {
                        "query": query_text,
                        "path": ["name", "description", "brand", "tags"],
                    }
                }
            ]
        }
        # Ajouter les filtres Atlas Search seulement s'ils existent et non vides
        if must_filters and isinstance(must_filters.get("compound"), dict):
            comp = must_filters["compound"]
            flt = comp.get("filter") or []
            if flt:
                compound["filter"] = flt

        # Exclusion du produit source au format Atlas Search
        if exclude_product_id:
            compound.setdefault("filter", []).append({
                "not": {"equals": {"path": "product_id", "value": exclude_product_id}}
            })

        pipeline: List[Dict[str, Any]] = [
            {"$search": {"index": self.TEXT_INDEX, "compound": compound}}
        ]
        if mql_match:
            pipeline.append({"$match": mql_match})

        pipeline += [
            {"$addFields": {"score": {"$meta": "searchScore"}}},
            {
                "$project": {
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
            {"$limit": limit},
        ]

        cursor = self.col.aggregate(pipeline)
        return [doc async for doc in cursor]

    # ---------- Exécution générique ----------
    async def execute_atlas_search(
        self,
        search_query: Dict[str, Any],
        limit: int = 10,
        exclude_product_id: Optional[str] = None,
        projection: Optional[Dict[str, Any]] = None,
        mql_match: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Exécute un $search/$vectorSearch générique, en évitant `filter: []`.
        """
        # Ajoute exclusion product_id dans compound.filter si présent
        if exclude_product_id and "compound" in search_query and isinstance(search_query["compound"], dict):
            comp = search_query["compound"]
            comp.setdefault("filter", []).append({
                "not": {"equals": {"path": "product_id", "value": exclude_product_id}}
            })
            if not comp["filter"]:
                comp.pop("filter", None)

        def _find_op(d: Any, key: str) -> Optional[Dict[str, Any]]:
            if isinstance(d, dict):
                if key in d and isinstance(d[key], dict):
                    return d[key]
                for v in d.values():
                    f = _find_op(v, key)
                    if f:
                        return f
            elif isinstance(d, list):
                for it in d:
                    f = _find_op(it, key)
                    if f:
                        return f
            return None

        pipeline: List[Dict[str, Any]] = []
        vs_cfg = _find_op(search_query, "vectorSearch")
        if vs_cfg:
            pipeline.append({"$vectorSearch": {"index": self.VECTOR_INDEX, **vs_cfg}})
        else:
            has_knn = _find_op(search_query, "knnBeta") is not None
            index_name = self.VECTOR_INDEX if has_knn else self.TEXT_INDEX
            # Nettoyage: `compound.filter` vide => on le retire
            if "compound" in search_query:
                comp = search_query["compound"]
                if isinstance(comp, dict) and "filter" in comp and (not comp["filter"] or len(comp["filter"]) == 0):
                    comp.pop("filter", None)
            pipeline.append({"$search": {"index": index_name, **search_query}})

        if mql_match:
            pipeline.append({"$match": mql_match})

        pipeline += [
            {"$addFields": {"score": {"$meta": "searchScore"}}},
            {"$project": projection or {
                "_id": 0, "score": 1, "product_id": 1, "name": 1, "brand": 1,
                "current_price": 1, "original_price": 1, "currency": 1,
                "category_id": 1, "category_path": 1, "image_url": 1, "tags": 1, "metadata": 1,
            }},
            {"$limit": limit},
        ]

        cursor = self.col.aggregate(pipeline)
        return [doc async for doc in cursor]
