# api/v1/schemas/similar.py
from datetime import datetime
from pydantic import BaseModel, Field
from typing import List, Optional

class RecoItemOut(BaseModel):
    product_id: str
    score: float

class RecoResultOut(BaseModel):
    source_product_id: str
    items: List[RecoItemOut]
    count: int


class ProductIn(BaseModel):
    product_id: str
    name: str
    description: Optional[str] = None
    category_id: Optional[str] = None
    brand: Optional[str] = None
    current_price: float
    original_price: Optional[float] = None
    currency: str
    stock: int
    image_url: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    metadata: Optional[dict] = None
    tags: Optional[List[str]] = None
    parent_product_id: Optional[str] = None
    reviews_count: Optional[int] = None
    rating: Optional[float] = None
    vendor_id: Optional[str] = None

class BulkIngestResult(BaseModel):
    inserted: int
    updated: int
    sim_vectors: int
    comp_vectors: int
    errors: List[str] = Field(default_factory=list)
    processing_time_ms: float