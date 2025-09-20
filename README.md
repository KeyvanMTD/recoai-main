## Overview

FastAPI application for product recommendations, analytics, and user activity.  
It integrates MongoDB (Atlas), Redis, and OpenAI for embeddings and optional LLM reranking.

---

## Structure

- **main.py**  
  FastAPI app entrypoint, router registration, logging, and lifespan management.

- **core/**  
  Configuration, versioning, logging, and application lifecycle utilities.

- **api/v1/routers/**  
  Versioned routers. Notable files:
  - `similar.py` → `/products/{product_id}/similar`
  - `complementary.py` → `/products/{product_id}/complementary`
  - `topsales.py` → `/top-sales`
  - `lastseen.py` → `/users/{user_id}/last-seen-product`
  - `xsell.py` → `/x-sell`
  - `products.py` → utilities like `/products/vectorize`

- **api/deps.py**  
  Dependency injection for database and cache clients.

- **domain/models/**  
  Pydantic models for products, recommendations, and related entities.

- **domain/repositories/**  
  Data access layers for products, vectors, cache, and search.

- **domain/services/**  
  Business logic for recommendation pipelines, embedding, retrieval, reranking, and prompts.

---

## Key Endpoints

- Similar products: `GET /products/{product_id}/similar`
- Complementary products: `GET /products/{product_id}/complementary`
- Cross-sell (co-purchase mining): `GET /products/{product_id}/x-sell`
- Top sellers: `GET /top-sales`
- User last seen (unique, most recent first): `GET /users/{user_id}/last-seen-product`
- Health check: `GET /health`
- Utilities: `POST /products/vectorize`

All recommendation endpoints accept `X-API-Version: v1|v2`.

---

## Environment Variables

- `APP_ENV` (development|production)
- `APP_NAME`
- `DEBUG`
- `MONGO_URI`
- `MONGO_DB`
- `REDIS_URL`
- `OPENAI_API_KEY`
- `OPENAI_EMBEDDING_MODEL`
- `OPENAI_RAG_MODEL`
  (See `.env.example` for details)

---

## How to Run

1. **Install dependencies**  
   ```sh
   pip install -r requirements.txt
   ```

2. **Start the API**  
   ```sh
   uvicorn app.main:app --reload
   ```

3. **Example requests**  
   ```sh
   # Similar
   curl -H "X-API-Version: v1" "http://localhost:8000/products/123/similar?limit=5"

   # Complementary
   curl -H "X-API-Version: v1" "http://localhost:8000/products/123/complementary?limit=5"

   # Top sales
   curl -H "X-API-Version: v1" "http://localhost:8000/top-sales?limit=20"

   # Last seen (unique, most recent)
   curl -H "X-API-Version: v1" "http://localhost:8000/users/abc/last-seen-product?limit=20"

   # Cross-sell
   curl -H "X-API-Version: v1" "http://localhost:8000/products/123/x-sell?limit=10"
   ```

---

## Testing

- Unit tests can be added in a `tests/` folder at the project root.
- Use `pytest` for running tests.

---

## Notes

- All configuration is managed via `app/core/config.py`.
- For production, use environment variables and a proper `.env` file.
- See `openapi.yaml` for a static API overview; the live docs are available at `/docs` when running.
