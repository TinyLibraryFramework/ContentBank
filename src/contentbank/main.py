"""
ContentBank API server entry point.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from contentbank.config import settings
from contentbank.core.validation import load_shapes
from contentbank.api.routes import objects, replication, proxy, auth

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    # Pre-load SHACL shapes at startup so first request isn't slow
    logger.info(f"Loading SHACL shapes from {settings.shapes_dir}")
    load_shapes(str(settings.shapes_dir))
    logger.info("ContentBank ready")
    yield
    logger.info("ContentBank shutting down")


app = FastAPI(
    title="ContentBank",
    description="Content-addressable persistent storage for TinyLibrary",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Routes ---
app.include_router(auth.router,        prefix="/api/v1")
app.include_router(objects.router,     prefix="/api/v1")
app.include_router(replication.router, prefix="/api/v1")
app.include_router(proxy.router,       prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok", "node_id": settings.node_id}


def main():
    import uvicorn
    logging.basicConfig(level=logging.DEBUG if settings.debug else logging.INFO)
    uvicorn.run(
        "contentbank.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )


if __name__ == "__main__":
    main()
