# app/domain/services/rerank.py

from __future__ import annotations
from typing import List, Tuple, Optional, Dict, Any
import json
import re
import logging
from time import monotonic as _now  
from app.core.config import Settings

from openai import AsyncOpenAI
from pydantic import BaseModel, Field, RootModel, ValidationError

from app.core.config import get_settings
from app.domain.models.product import Product, RecoItem
from app.domain.services.constants import (
    RERANK_ALPHA,
    MIN_SCORE_RETRIEVAL_SIM,
    MIN_SCORE_RETRIEVAL_COMP,
    MIN_SCORE_RETRIEVAL_XSELL,
    MIN_SCORE_RETRIEVAL_UPSELL,
    KIND_SIMILAR, KIND_SIMILAR_RICH,
    KIND_COMPLEMENTARY, KIND_COMPLEMENTARY_RICH,
    KIND_XSELL, KIND_UPSELL,
)
from app.domain.services.prompts import system_prompt, user_task

logger = logging.getLogger(__name__)

# Completion token caps
DEFAULT_MAX_TOKENS = 256
RATIONALE_MAX_TOKENS = 512

# =============================================================================
#                               VALIDATION SCHEMA
# =============================================================================

class RankItem(BaseModel):
    """
    Represents a single candidate product in the LLM output.
    Matches the expected output in prompts.py:
      {
        "product_id": "<candidate.product_id>",
        "score": 0.000,                # non-increasing order
        "rationale": "short, factual, from CONTEXT only"  # optional
      }
    """
    product_id: str = Field(..., min_length=1)
    score: float = Field(..., ge=0.0, le=1.0)
    rationale: Optional[str] = Field(default=None, max_length=100)  # Optional field with default

class RankResponse(BaseModel):
    """
    Represents the full LLM output for a query, matching prompts.py:
      {
        "query_product_id": "<from QUERY.product_id>",
        "results": [RankItem, ...]
      }
    """
    query_product_id: str = Field(..., min_length=1)
    results: List[RankItem]

# Regex to strip code fences (``` or ```json) from LLM output
_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

def _strip_fences(s: str) -> str:
    """Remove ``` or ```json fences the LLM might add."""
    return _CODE_FENCE_RE.sub("", s).strip()

def _parse_and_validate(json_text: str) -> List[RankItem]:
    """
    Parse a JSON array, validate with Pydantic, and return Python objects.
    Raises ValueError on any issue.
    """
    try:
        raw = _strip_fences(json_text)
        logger.debug(f"LLM raw response after fence stripping: {raw}...")
        parsed = json.loads(raw)
        logger.debug(f"Parsed JSON keys: {parsed.keys() if isinstance(parsed, dict) else 'not dict'}")
        model = RankResponse.model_validate(parsed)
        items: List[RankItem] = model.results
        logger.debug(f"First item rationale: {items[0].rationale if items else 'no items'}")
    except (json.JSONDecodeError, ValidationError) as e:
        raise ValueError(f"Invalid LLM JSON: {e}") from e

    # Deduplicate while preserving order
    seen = set()
    deduped: List[RankItem] = []
    for it in items:
        if it.product_id not in seen:
            seen.add(it.product_id)
            deduped.append(it)
    return deduped

# =============================================================================
#                               LLM CALL + RETRY
# =============================================================================

async def _call_llm(messages: List[dict], model: str, timeout_s: int, max_tokens: int) -> str:
    """
    Call the LLM with the given messages, model, and timeout.
    Returns the raw content string from the LLM response.
    """
    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    t0 = _now()
    resp = await client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,  # dynamic based on rationale
        temperature=0.0,
        timeout=timeout_s,
        response_format={"type": "json_object"},
    )
    dt = _now() - t0
    # Best-effort usage logging
    try:
        u = getattr(resp, "usage", None)
        p = getattr(u, "prompt_tokens", None) if u else None
        c = getattr(u, "completion_tokens", None) if u else None
        tot = getattr(u, "total_tokens", None) if u else None
        logger.info(
            f"LLM call model={getattr(resp, 'model', model)} duration={dt:.3f}s "
            f"tokens(prompt={p}, completion={c}, total={tot})"
        )
    except Exception:
        logger.info(f"LLM call model={model} duration={dt:.3f}s (usage unavailable)")
    return resp.choices[0].message.content or "[]"

async def _rerank_with_schema_retry(
    messages: List[dict],
    *,
    model: str,
    timeout_s: int,
    max_retries: int = 2,
    max_tokens: int,  # <-- added
) -> List[Dict[str, Any]]:
    """
    Ask the LLM for JSON ranking. Validate strictly.
    On parse/validation error, retry with a stricter instruction & JSON Schema.
    """
    last_err: Optional[str] = None
    schema = RankResponse.model_json_schema()

    for attempt in range(max_retries + 1):
        content = await _call_llm(messages, model=model, timeout_s=timeout_s, max_tokens=max_tokens)
        try:
            items = _parse_and_validate(content)
            return [it.model_dump() for it in items]
        except ValueError as e:
            last_err = str(e)
            if attempt == max_retries:
                raise
            messages = messages + [
                {"role": "system",
                 "content": (
                     "Your previous response did not conform to the required JSON format. "
                     "You MUST return JSON that matches the provided JSON Schema exactly. "
                     "No prose, no code fences, no comments."
                 )},
                {"role": "user",
                 "content": (
                     f"Validation error was:\n{last_err}\n\n"
                     "Here is the JSON Schema you MUST follow exactly:\n"
                     f"{schema}\n\n"
                     "Return ONLY a JSON object like:\n"
                     "{{\"query_product_id\": \"...\", \"results\": [{{\"product_id\": \"...\", \"score\": 0.0-1.0, \"rationale\": \"...\"}}]}}"
                 )},
            ]
    raise RuntimeError("Unexpected fall-through in _rerank_with_schema_retry")

# =============================================================================
#                               PUBLIC API
# =============================================================================

async def rag_answer(
    *,
    kind: str,
    src: Product,
    candidates: List[RecoItem],
    prod_repo,
    settings: Settings,
    include_rationale: bool = False,
) -> List[RecoItem]:
    """
    RAG-style re-ranking with:
    - Prompt text from `prompt.py`
    - Schema validation for LLM JSON output
    - Automatic retry on parse errors
    - Fail-open fallback (returns original candidates if LLM fails)
    """
    if not candidates:
        logger.info("No candidates provided for RAG reranking.")
        return candidates

    # Hydrate candidate docs (K=50 → OK to fetch one by one if no batch method)
    ids = [c.product_id for c in candidates]
    logger.debug(f"Fetching candidate docs for product_ids: {ids}")
    if hasattr(prod_repo, "get_many_by_product_ids"):
        # Batch fetch if method available
        docs = await prod_repo.get_many_by_product_ids(ids)
        logger.debug(f"Batch fetched {len(docs)} candidate docs.")
    else:
        # Fallback: fetch one by one
        docs = []
        for pid in ids:
            d = await prod_repo.col.find_one(
                {"product_id": pid},
                projection={
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
                },
            )
            if d:
                docs.append(d)
        logger.debug(f"Individually fetched {len(docs)} candidate docs.")

    # Map product_id to doc for quick lookup
    by_id = {d["product_id"]: d for d in docs}
    # Prepare compact docs for LLM input
    passages = [_compact_doc(by_id[i]) for i in ids if i in by_id]
    # Track missing products (not found in DB)
    missing = [i for i in ids if i not in by_id]
    logger.debug(f"Prepared {len(passages)} passages for LLM input. Missing: {missing}")

    # Prepare messages for LLM prompt with conditional rationale
    user_payload = {
        "query_product": _compact_source(src),
        "candidates": passages,
        "task": user_task(kind, include_rationale=include_rationale),
    }
    user_json = _json_minify(user_payload)  # minified JSON string

    messages = [
        {"role": "system", "content": system_prompt(kind)},
        {"role": "user", "content": user_json},
    ]
    logger.info(f"LLM request JSON size={(len(user_json)/1024):.1f}KB candidates={len(passages)}")
    logger.debug(f"LLM user JSON preview: {user_json[:2000]}{'…' if len(user_json)>2000 else ''}")

    max_comp_tokens = RATIONALE_MAX_TOKENS if include_rationale else DEFAULT_MAX_TOKENS
    logger.debug(f"LLM completion max_tokens set to {max_comp_tokens} (include_rationale={include_rationale})")

    try:
        # Call LLM and validate output, with retry on error
        ranked = await _rerank_with_schema_retry(
            messages,
            model=getattr(settings, "llm_rerank_model", settings.OPENAI_RAG_MODEL),
            timeout_s=getattr(settings, "llm_rerank_timeout", 30),
            max_retries=2,
            max_tokens=max_comp_tokens,  # <-- pass dynamic cap
        )
        logger.info(f"LLM reranking succeeded for product_id={src.product_id}, got {len(ranked)} results.")
        llm_score_by_id = {r["product_id"]: float(r["score"]) for r in ranked}
        llm_rationale_by_id = {r["product_id"]: r.get("rationale", "") for r in ranked}
    except Exception as e:
        logger.error(f"LLM reranking failed for product_id={src.product_id}: {e}")
        # Fail-open: keep original order if LLM fails
        return candidates

    # Blend scores and reorder
    init_by_id = {c.product_id: float(c.score) for c in candidates}
    blended: List[Tuple[str, float, str]] = []  # Add rationale to tuple
    for pid in ids:
        init = init_by_id.get(pid, 0.0)
        llm = llm_score_by_id.get(pid, 0.0)
        rationale = llm_rationale_by_id.get(pid, "")
        blended.append((pid, RERANK_ALPHA * llm + (1 - RERANK_ALPHA) * init, rationale))
    for pid in missing:
        blended.append((pid, init_by_id.get(pid, 0.0), ""))

    logger.debug(f"Blended scores for {len(blended)} products.")

    # Sort by blended score descending
    blended.sort(key=lambda x: x[1], reverse=True)
    logger.info(f"Returning {len(blended)} reranked candidates for product_id={src.product_id}")
    
    # Filter out items below per-kind minimal score
    threshold = _min_score_threshold(kind)
    filtered_blended = [tpl for tpl in blended if tpl[1] >= threshold]
    logger.debug(f"Filter threshold(kind={kind})={threshold}; kept={len(filtered_blended)}/{len(blended)}")

    # Return as list of RecoItem with rationale only when requested
    if include_rationale:
        return [RecoItem(product_id=pid, score=score, rationale=rationale) for pid, score, rationale in filtered_blended]
    else:
        return [RecoItem(product_id=pid, score=score) for pid, score, _ in filtered_blended]
#
# =============================================================================
#                               JSON PRUNING
# =============================================================================
def _prune_empty(obj):
    """
    Recursively remove:
      - None
      - empty strings (after strip)
      - empty lists/dicts
    Keep: 0, False, and non-empty values.
    """
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            pv = _prune_empty(v)
            if pv is None:
                continue
            if isinstance(pv, str) and pv.strip() == "":
                continue
            if isinstance(pv, (list, dict)) and len(pv) == 0:
                continue
            out[k] = pv
        return out
    if isinstance(obj, list):
        out = []
        for v in obj:
            pv = _prune_empty(v)
            if pv is None:
                continue
            if isinstance(pv, str) and pv.strip() == "":
                continue
            if isinstance(pv, (list, dict)) and len(pv) == 0:
                continue
            out.append(pv)
        return out
    if isinstance(obj, str):
        s = obj.strip()
        return s if s != "" else None
    return obj

def _json_minify(obj: Dict[str, Any]) -> str:
    """
    Prune empty/null fields and serialize to compact JSON (no spaces).
    """
    return json.dumps(_prune_empty(obj), ensure_ascii=False, separators=(',', ':'))

# =============================================================================
#                               COMPACT HELPERS
# =============================================================================

def _compact_source(src: Product) -> Dict[str, Any]:
    """
    Reduce the source product to the minimal fields for LLM context.
    """
    data = {
        "product_id": src.product_id,
        "name": src.name,
        "brand": src.brand,
        "desc": (src.description or ""),
        "category_id": src.category_id,
        "category_path": src.category_path,
        "tags": (src.tags or [])[:8],
    }
    # Shorten large text after pruning empties
    data = _prune_empty(data)
    if "desc" in data:
        data["desc"] = data["desc"][:220]
    return data

def _compact_doc(doc: dict) -> dict:
    """
    Reduce a product document to the minimal fields needed for LLM reranking.
    Includes metadata, tags, and a short description.
    """
    data = {
        "product_id": doc.get("product_id"),
        "name": doc.get("name"),
        "brand": doc.get("brand"),
        "category_id": doc.get("category_id"),
        "price": doc.get("current_price"),
        "tags": (doc.get("tags") or [])[:8],
        "desc": (doc.get("description") or ""),
    }
    data = _prune_empty(data)
    if "desc" in data:
        data["desc"] = data["desc"][:200]
    return data

def _min_score_threshold(kind: str) -> float:
    """
    Return the minimal blended score required to keep an item, based on kind.
    """
    if kind in (KIND_SIMILAR, KIND_SIMILAR_RICH):
        return MIN_SCORE_RETRIEVAL_SIM
    if kind in (KIND_COMPLEMENTARY, KIND_COMPLEMENTARY_RICH):
        return MIN_SCORE_RETRIEVAL_COMP
    if kind in (KIND_XSELL):
        return MIN_SCORE_RETRIEVAL_XSELL
    if kind in (KIND_UPSELL):  
        return MIN_SCORE_RETRIEVAL_UPSELL
    return 0.0
