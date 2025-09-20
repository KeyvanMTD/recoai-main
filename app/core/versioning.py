from fastapi import Header
from typing import Literal

async def resolve_version(
    x_api_version: str | None = Header(default=None),
) -> Literal["v1","v2"]:
    """
    Dependency to resolve API version from request headers.
    - Priority to explicit 'X-API-Version' header (values: '1', 'v1', '2', 'v2').
    - Defaults to 'v2' if nothing matches.
    """
    # Priority to explicit version header
    if x_api_version in {"1","v1"}: return "v1"
    if x_api_version in {"2","v2"}: return "v2"
    
    # Default version (can be changed if needed)
    return "v1"
