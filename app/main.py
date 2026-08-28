"""FastAPI main entrypoint for MPLADS Risk Analytics ML Engine."""

import os
import logging
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from app.models.loader import get_registry
from app.routers.predict import router as predict_router

# Load environment variables
load_dotenv()

# Configure logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s"
)
logger = logging.getLogger("fastapi_app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan handler: loads ML models & lookups into memory on startup."""
    logger.info("Initializing MPLADS Risk Analytics ML Service...")
    registry = get_registry()
    try:
        registry.load_artifacts()
        logger.info("ML Service successfully initialized and ready to serve requests.")
    except Exception as e:
        logger.error("Failed to load ML artifacts at startup: %s", e, exc_info=True)
        raise e
    yield
    logger.info("Shutting down MPLADS Risk Analytics ML Service...")


# Create FastAPI application instance
app = FastAPI(
    title="MPLADS Risk Analytics — Execution & Anomaly ML Engine",
    description="Machine Learning Service for detecting project execution delay, budget overruns, photo compliance deficits, and sector expenditure anomalies.",
    version="1.0.0",
    lifespan=lifespan
)

# CORS Policy: Restricted strictly to Express proxy backend
raw_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000")
allowed_origins = [orig.strip() for orig in raw_origins.split(",") if orig.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
logger.info("Configured CORS allowed origins: %s", allowed_origins)

# Mount routes
app.include_router(predict_router)


@app.get("/", summary="Root Welcome")
async def root():
    return {
        "service": "MPLADS Risk Analytics ML Engine",
        "status": "operational",
        "docs_url": "/docs",
        "health_url": "/health"
    }


if __name__ == "__main__":
    port = int(os.getenv("ML_PORT", "3000"))
    host = os.getenv("ML_HOST", "0.0.0.0")
    logger.info("Starting uvicorn server on %s:%d...", host, port)
    uvicorn.run("app.main:app", host=host, port=port, reload=True)
