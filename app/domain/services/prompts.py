from app.domain.services.constants import KIND_COMPLEMENTARY, KIND_SIMILAR, KIND_XSELL

def system_prompt(kind: str) -> str:
    # These are already concise, no change needed
    if kind == KIND_COMPLEMENTARY:
        return "You are a ranking model for PRODUCT COMPLEMENTARITY (cross-sell). Return strict JSON only."
    if kind == KIND_SIMILAR:
        return "You are a ranking model for PRODUCT SUBSTITUTABILITY (similar products). Return strict JSON only."
    if kind == KIND_XSELL:
        return "Rank cross-sell products for the given query product. Return strict JSON."
    raise ValueError(f"Unknown kind for system prompt: {kind}")

def user_task(kind: str, include_rationale: bool = False) -> str:
    # Compact JSON output format for both prompts
    output_format = (
        '{"query_product_id":"<from QUERY.product_id>","results":['
        '{"product_id":"<candidate.product_id>","score":0.000' + 
        (',"rationale":"brief reason"' if include_rationale else '') + 
        '}]}'
    )
    
    # Shared constraints for both prompts
    constraints = (
        "RULES:\n"
        "- Use ONLY provided CONTEXT\n"
        "- Scores: 0.0-1.0 non-increasing\n" +
        ("- Rationale: ≤25 words, factual\n" if include_rationale else "") +
        "- Format: strict JSON\n"
        "- Skip low confidence (<0.50)"
    )
    
    if kind == KIND_COMPLEMENTARY:
        return (
            "Rank how well CANDIDATES complement the QUERY product.\n\n"
            "DEFINITION: Complementary = used together (camera↔lens; phone↔case)\n"
            "NOT complementary = Similar, same purpose or unrelated items\n\n"
            "SCORING:\n"
            "+0.50: Strong functional relationship (works with, bundle patterns)\n"
            "+0.30: Compatible/matching (size, connector, mount) or shared context\n"
            "+0.20: Logical category pair or price-role balance\n"
            "-0.50: Same role as QUERY or incompatible\n"
            "-0.30: Unrelated purpose/context\n\n" +
            constraints + "\n\n" +
            "OUTPUT FORMAT: " + output_format
        )
    
    if kind == KIND_SIMILAR:
        return (
            "Rank how well CANDIDATES can replace the QUERY product.\n\n"
            "DEFINITION: Similar = same purpose, overlapping attributes, similar price\n"
            "NOT similar = complementary (used together) or major category/spec mismatch\n\n"
            "SCORING:\n"
            "+0.50: Same category & primary purpose\n" 
            "+0.30: Strong attribute overlap & similar price (±20%)\n"
            "+0.20: Same brand/family or comparable positioning\n"
            "-0.40: Different primary purpose\n"
            "-0.30: Cross-category or major price gap (>50%)\n\n" +
            constraints + "\n\n" +
            "OUTPUT FORMAT: " + output_format
        )
        
    if kind == KIND_XSELL:
        return (
            "Rank how well CANDIDATES are cross-sell products for the QUERY product.\n\n"
            "DEFINITION: Cross-sell = products often bought together with the query product\n"
            "NOT cross-sell = Similar (substitutable) or unrelated items\n\n"
            "SCORING:\n"
            "+0.50: Very frequently co-purchased (strong signal)\n"
            "+0.30: Frequently co-purchased (moderate signal)\n"
            "+0.20: Occasionally co-purchased (weak signal)\n"
            "-0.50: Rarely/never co-purchased\n"
            "-0.30: Similar/substitutable products\n\n" +
            constraints + "\n\n" +
            "OUTPUT FORMAT: " + output_format
        )
    
    raise ValueError(f"Unknown kind for user task: {kind}")

