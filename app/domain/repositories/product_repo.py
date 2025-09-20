# app/domain/repositories/product_repo.py

from __future__ import annotations
from typing import Optional, List
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.domain.models.product import Product

class ProductRepo:
    """
    Product repository backed by the 'products' collection.
    Also supports per-kind vector persistence under the 'vectors' subdocument:
      vectors.<kind> = { model, vector, updated_at }
    """

    def __init__(self, db: AsyncIOMotorDatabase, collection_name: str = "products"):
        self.col = db[collection_name]

    async def get_by_product_id(self, product_id: str) -> Optional[Product]:
        doc = await self.col.find_one({"product_id": product_id}, {"_id": 0})
        return Product.model_validate(doc) if doc else None

    # ----- Vector persistence (per kind) ------------------------------------

    async def get_vector(self, product_id: str, kind: str) -> Optional[list[float]]:
        """
        Load an embedding vector for a given product and kind from:
          vectors.<kind>.vector
        """
        proj = {f"vectors.{kind}.vector": 1, "_id": 0}
        doc = await self.col.find_one({"product_id": product_id}, proj)
        if not doc:
            return None
        node = doc.get("vectors", {}).get(kind) if isinstance(doc.get("vectors"), dict) else None
        return node.get("vector") if isinstance(node, dict) and "vector" in node else None

    async def set_vector(self, product_id: str, kind: str, vector: list[float], *, model: str) -> None:
        """
        Persist an embedding vector for a given kind under:
          vectors.<kind> = { model, vector, updated_at }
        """
        path = f"vectors.{kind}"
        now = datetime.now(timezone.utc)
        await self.col.update_one(
            {"product_id": product_id},
            {
                "$set": {
                    f"{path}.model": model,
                    f"{path}.vector": vector,
                    f"{path}.updated_at": now,
                }
            },
            upsert=False,  # assume product exists; set True if you want to upsert the product
        )

    # (Optional) Efficient batch fetch for LLM reranking hydration
    async def get_many_by_product_ids(self, ids: List[str]) -> List[dict]:
        cursor = self.col.find(
            {"product_id": {"$in": ids}},
            {
                "_id": 0,
                "product_id": 1,
                "name": 1,
                "brand": 1,
                "description": 1,
                "category_id": 1,
                "category_path": 1,
                "current_price": 1,
                "currency": 1,
                "tags": 1,
                "metadata": 1,
                "image_url": 1,
                "stock": 1,
            },
        )
        return [doc async for doc in cursor]
