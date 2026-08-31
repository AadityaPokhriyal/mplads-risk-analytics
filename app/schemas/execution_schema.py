from pydantic import BaseModel, Field
from typing import List, Optional, Union
import datetime

# ---------------------------------------------------------------------------
# Request Schemas
# ---------------------------------------------------------------------------

class WorkExecutionInput(BaseModel):
    work_id: str = Field(..., example="WS/MP620/2024-2025/133166")
    work_description: str
    work_category: Optional[str] = "Normal/Others"
    state: str
    mp_name: str
    constituency: str
    ida: str
    recommended_amount: float = Field(..., ge=0)
    recommended_date: Union[str, datetime.date]
    sanction_amount: float = Field(..., ge=0)
    sanction_date: Union[str, datetime.date]
    work_status: str
    amount_disbursed: float = Field(..., ge=0)
    completion_date: Optional[Union[str, datetime.date]] = None
    has_photo_evidence: bool = False


class WorkExecutionBatchInput(BaseModel):
    works: List[WorkExecutionInput]


# ---------------------------------------------------------------------------
# Response Schemas
# ---------------------------------------------------------------------------

class LifecycleMetrics(BaseModel):
    recommended_amount: float
    sanction_amount: float
    amount_disbursed: float
    disbursement_pct: str
    current_stage: str
    approval_latency_days: int
    current_project_age_days: Optional[int] = None
    execution_duration_days: Optional[int] = None
    is_stalled: bool
    has_photo_evidence: bool


class WorkExecutionPredictionOutput(BaseModel):
    work_id: str
    execution_risk_score: float
    risk_level: str
    is_compliant: bool
    lifecycle_metrics: LifecycleMetrics
    flagged_reasons: List[str]
    explainability_tags: List[str]
    recommended_action: str


class BatchWorkExecutionPredictionItem(BaseModel):
    work_id: str
    work_description: Optional[str] = None
    state: str
    mp_name: str
    execution_risk_score: float
    risk_level: str
    is_compliant: bool
    is_stalled: bool
    has_photo_evidence: bool
    current_stage: str
    flagged_reasons: List[str]
    explainability_tags: List[str]
    recommended_action: str


class WorkExecutionBatchOutput(BaseModel):
    summary: dict
    results: List[BatchWorkExecutionPredictionItem]
