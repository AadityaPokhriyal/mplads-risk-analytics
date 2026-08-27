"""FastAPI endpoints for ML inference and health checks."""

import logging
from typing import List, Union
from fastapi import APIRouter, HTTPException, Depends, status

from app.schemas.work import (
    WorkInput,
    WorkRiskResponse,
    BatchWorkInput,
    BatchRiskResponse,
    HealthResponse
)
from app.services.scoring import score_single_work, score_batch_works
from app.models.loader import get_registry, ModelRegistry

logger = logging.getLogger("fastapi_app.routers.predict")

router = APIRouter(tags=["ML Risk Inference"])


@router.get("/health", response_model=HealthResponse, summary="ML Service Health Check")
async def health_check(registry: ModelRegistry = Depends(get_registry)):
    """Verifies that the ML model, scalers, and statistical dictionaries are loaded and operational."""
    try:
        is_ready = registry.is_loaded()
        if not is_ready:
            registry.load_artifacts()
            is_ready = registry.is_loaded()

        return HealthResponse(
            status="healthy" if is_ready else "unhealthy",
            version="1.0.0",
            model_loaded=is_ready,
            artifacts={
                "model": "IsolationForest (n_estimators=150, contamination=0.10)",
                "scaler": "StandardScaler (5 features)",
                "category_count": len(registry.get_category_stats()),
                "mp_count": len(registry.get_mp_completion_rates())
            }
        )
    except Exception as e:
        logger.error("Health check error: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"ML Service Unhealthy: {str(e)}"
        )


@router.post(
    "/api/predict/work",
    response_model=WorkRiskResponse,
    summary="Single Work Risk Analysis",
    description="Evaluates a single project work for execution delay, cost escalation, photo compliance, and sector anomalies."
)
async def predict_single_work(work: WorkInput):
    """Real-time scoring for an individual work."""
    try:
        response = score_single_work(work)
        return response
    except Exception as e:
        logger.error("Error scoring work_id %s: %s", work.work_id, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Inference error on work_id {work.work_id}: {str(e)}"
        )


@router.post(
    "/api/predict/works",
    response_model=BatchRiskResponse,
    summary="Batch Works Risk Analysis",
    description="Batch-scores a collection of project works (e.g. for an MP or district), returning summary KPIs and flagged risk items."
)
async def predict_batch_works(payload: Union[BatchWorkInput, List[WorkInput]]):
    """Batch scoring for an array or wrapped object of project works."""
    try:
        # Support both wrapped {"works": [...]} and raw list [...] requests
        if isinstance(payload, BatchWorkInput):
            works_list = payload.works
        elif isinstance(payload, list):
            works_list = payload
        else:
            raise ValueError("Payload must be either a BatchWorkInput or a list of WorkInput items.")

        response = score_batch_works(works_list)
        return response
    except Exception as e:
        logger.error("Error in batch scoring: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Batch inference error: {str(e)}"
        )
