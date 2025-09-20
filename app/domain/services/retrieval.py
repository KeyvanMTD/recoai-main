import logging
from app.domain.models.product import RecoItem
from typing import Optional, Literal

logger = logging.getLogger(__name__)

# Use the vector field stored on each product document (per KIND).
def _vector_path(kind: Literal["sim", "comp"] = "sim") -> str:
    return f"vectors.{kind}.vector"

async def retrieve_candidates(
    search_repo,
    vec: list[float] | None,
    text_query: str,
    must_filters: dict | None,
    retrieval_k: int,
    kind: Literal["sim", "comp"] = "sim",  # choose which vector to use; default "sim"
):
    """
    Retrieve candidate products using MongoDB Atlas $vectorSearch on the per-product vector field.
    Falls back to text search if no vector results.
    """
    items: list[RecoItem] = []

    # Validate filter format
    if must_filters and "compound" not in must_filters:
        logger.warning("Filters not in Atlas Search compound format; expected {'compound': {'filter': [...]}}")

    # ---------- Vector phase ($vectorSearch) ----------
    if vec:
        try:
            raw = await search_repo.vector_search(
                query_vector=vec,
                path=_vector_path(kind),  # "vectors.sim.vector" when kind="sim"
                limit=retrieval_k,
                num_candidates=max(200, 10 * retrieval_k),
                must_filters=must_filters,  # optional Atlas Search-style filters
            )
            logger.info(f"Atlas $vectorSearch returned {len(raw)} results for path={_vector_path(kind)}")
            items = [RecoItem(product_id=r["product_id"], score=float(r.get("score", 0))) for r in raw]
        except Exception as e:
            logger.error(f"Atlas $vectorSearch failed: {e}")
            items = []

    # ---------- Text fallback ----------
    if not items and text_query:
        try:
            fallback_filters = (
                must_filters.get("compound", {}).get("filter", [])
                if must_filters else []
            )

            search_query = {
                "compound": {
                    "must": [
                        {
                            "text": {
                                "query": text_query,
                                "path": [
                                    "name",
                                    "description",
                                    "tags",
                                    "brand",
                                ],
                                "fuzzy": {"maxEdits": 1, "prefixLength": 3},
                            }
                        }
                    ],
                    "filter": fallback_filters,
                }
            }

            logger.debug(
                f"Attempting Atlas text fallback: query='{text_query}', k={retrieval_k}, filters={fallback_filters}"
            )

            raw = await search_repo.execute_atlas_search(
                search_query=search_query,
                limit=retrieval_k,
            )

            logger.info(f"Atlas text fallback returned {len(raw)} results")
            items = [
                RecoItem(product_id=r["product_id"], score=float(r.get("score", 0)))
                for r in raw
            ]
        except Exception as e:
            logger.error(f"Atlas text fallback failed: {e}")
            items = []

    logger.debug(f"Returning {len(items)} candidates")
    return items
