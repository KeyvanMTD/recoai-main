from app.domain.services.pipeline_svc import recommend
from app.domain.services.constants import KIND_COMPLEMENTARY

async def get_complementary_products_cached(db, redis, *, version: str, product_id: str, limit: int = 10, use_llm_rerank: bool = True, include_rationale: bool = False, **kw):
    """
    Service function to retrieve complementary products with caching.
    - Calls the generic recommend() pipeline with KIND_COMPLEMENTARY.
    - Passes database, cache, API version, and product_id.
    - Additional keyword arguments (**kw) allow for custom filters, limits, etc.
    - Returns a RecoResult containing recommended complementary products.
    """
    return await recommend(kind=KIND_COMPLEMENTARY, version=version, product_id=product_id, db=db, redis=redis, use_llm=use_llm_rerank, include_rationale=include_rationale, **kw)
    
