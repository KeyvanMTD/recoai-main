from app.domain.services.constants import KIND_SIMILAR, KIND_COMPLEMENTARY

def _normalize_gender(g):
    """
    Normalize common gender strings to: 'male' | 'female' | 'unisex'.
    Returns None if empty/unknown.
    """
    if g is None:
        return None
    s = str(g).strip().lower()
    if not s:
        return None
    if s in {"m", "male", "man", "men"}:
        return "male"
    if s in {"f", "female", "woman", "women"}:
        return "female"
    if s in {"u", "unisex", "all", "any"}:
        return "unisex"
    # Keep other values as-is to avoid over-filtering
    return s

def _extract_gender(src):
    """
    Return normalized gender from source product.
    Can return str, list[str], or None.
    """
    g = getattr(src, "gender", None)
    if not g:
        meta = getattr(src, "metadata", {}) or {}
        g = meta.get("gender")

    # Normalize and keep structure
    if isinstance(g, (list, tuple)):
        norm = list({_normalize_gender(x) for x in g if _normalize_gender(x)})
        return norm or None
    return _normalize_gender(g)

def default_filters(kind: str, src) -> dict:
    """
    Generate Atlas Search filters based on product type and source product.
    Returns a properly formatted compound filter for Atlas Search.
    """
    # Start with an empty filter array that we'll populate
    filters = []
    
    # Common filter: stock > 0
    filters.append({
        "range": {
            "path": "stock",
            "gt": 0
        }
    })
    
    if kind == KIND_COMPLEMENTARY:
        # Complementary products: different category, but share at least one tag/use-case
        if src.category_id:
            filters.append({
                "not": {
                    "equals": {
                        "path": "category_id",
                        "value": src.category_id
                    }
                }
            })
        if src.tags and len(src.tags) > 0:
            filters.append({
                "text": {
                    "path": "tags",
                    "query": " ".join(src.tags)
                }
            })
        # Exclude products with the same name as the source (if present)
        if getattr(src, "name", None):
            filters.append({
                "not": {
                    "equals": {
                        "path": "name",
                        "value": src.name
                    }
                }
            })

    elif kind == KIND_SIMILAR:
        # Similar products: same category (optional: same brand)
        if src.category_id:
            filters.append({
                "equals": {
                    "path": "category_id",
                    "value": src.category_id
                }
            })

        # Exclude products with the same name as the source (if name is present)
        if getattr(src, "name", None):
            filters.append({
                "not": {
                    "equals": {
                        "path": "name",
                        "value": src.name
                    }
                }
            })

        # Exclude variants: any product whose parent_product_id points to the source
        # If the source is itself a variant (has a parent), exclude siblings by that parent.
        parent_id = getattr(src, "parent_product_id", None)
        anchor_parent = parent_id or getattr(src, "product_id", None)
        if anchor_parent:
            filters.append({
                "not": {
                    "equals": {
                        "path": "parent_product_id",
                        "value": anchor_parent
                    }
                }
            })

    # Gender rule for SIM and COMP:
    # - If source gender is male => exclude only metadata.gender == "female"
    # - If source gender is female => exclude only metadata.gender == "male"
    # - If source gender is unisex or both male & female => no filter
    # - If source has no gender => no filter
    if kind in {KIND_COMPLEMENTARY, KIND_SIMILAR}:
        sg = _extract_gender(src)

        # Resolve to a single decision
        if isinstance(sg, list):
            sset = set(sg)
            if "unisex" in sset or ({"male", "female"} <= sset):
                sg_norm = None  # accept all genders
            elif sset == {"male"}:
                sg_norm = "male"
            elif sset == {"female"}:
                sg_norm = "female"
            else:
                # Mixed/unknown -> do not filter
                sg_norm = None
        else:
            sg_norm = sg

        if sg_norm == "male":
            filters.append({
                "not": {
                    "equals": {
                        "path": "metadata.gender",
                        "value": "female"
                    }
                }
            })
        elif sg_norm == "female":
            filters.append({
                "not": {
                    "equals": {
                        "path": "metadata.gender",
                        "value": "male"
                    }
                }
            })
        # sg_norm is None or "unisex" => no gender filter

    # Wrap everything in a compound filter
    return {
        "compound": {
            "filter": filters
        }
    }

