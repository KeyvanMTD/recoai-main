from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class Product(BaseModel):
    product_id: str
    name: str
    description: Optional[str] = None
    category_id: Optional[str] = None
    category_path: Optional[str] = None
    brand: Optional[str] = None
    current_price: Optional[float] = None
    original_price: Optional[float] = None
    currency: Optional[str] = None
    stock: Optional[int] = None
    image_url: Optional[str] = None
    tags: List[str] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"frozen": True}  # immuable = safe

class RecoItem(BaseModel):
    product_id: str
    score: float = Field(ge=0)
    rationale: Optional[str] = None
    model_config = {"frozen": True} # immuable = safe

class RecoResult(BaseModel):
    source_product_id: str
    items: List[RecoItem]
    count: int
    model_config = {"frozen": True} # immuable = safe
