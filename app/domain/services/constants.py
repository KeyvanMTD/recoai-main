# Constants for the recommendation pipeline vectorization.
RETRIEVAL_K = 30  # Number of candidates to retrieve for reranking
FINAL_K = 10  # Final number of recommendations to return after reranking

# Blend LLM vs retrieval score
RERANK_ALPHA = 0.75

# Minimal score for each algorithm to be considered in blending
MIN_SCORE_RETRIEVAL_SIM = 0.5
MIN_SCORE_RETRIEVAL_COMP = 0.5
MIN_SCORE_RETRIEVAL_XSELL = 0
MIN_SCORE_RETRIEVAL_UPSELL = 0

# Recommendation kinds
KIND_SIMILAR = "sim"     # Substitutable products per attributes
KIND_SIMILAR_RICH = "sim_rich"  # Substitutable products with rich context (e.g., views and click history)
KIND_COMPLEMENTARY = "comp"  # Used-together products per attributes
KIND_COMPLEMENTARY_RICH = "comp_rich"  # Used-together products with rich context (purchase history, etc.)
KIND_XSELL = "xsell"  # Cross-sell products
KIND_UPSELL = "upsell"  # Upsell products

# List of all supported kinds (useful for validation or enums)
ALL_KINDS = {KIND_SIMILAR, KIND_COMPLEMENTARY, KIND_XSELL, KIND_UPSELL, KIND_SIMILAR_RICH, KIND_COMPLEMENTARY_RICH}