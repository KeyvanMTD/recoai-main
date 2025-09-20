from app.domain.services.pipeline_svc import recommend
from app.domain.services.constants import KIND_SIMILAR

async def get_similar_products_cached(db, redis, *, version: str, product_id: str, limit: int = 10, use_llm_rerank: bool = True, include_rationale: bool = False, **kw):
    """
    Service function to retrieve similar products with caching.
    - Calls the generic recommend() pipeline with KIND_SIMILAR.
    - Passes database, cache, API version, and product_id.
    - Additional keyword arguments (**kw) allow for custom filters, limits, etc.
    - Returns a RecoResult containing recommended similar products.
    """
    # Map use_llm_rerank to use_llm which is what recommend() expects
    result = await recommend(
        kind=KIND_SIMILAR, 
        version=version, 
        product_id=product_id, 
        db=db, 
        redis=redis,
        use_llm=use_llm_rerank,  # Map parameter name
        include_rationale=include_rationale,
        **kw
    )
    return result
