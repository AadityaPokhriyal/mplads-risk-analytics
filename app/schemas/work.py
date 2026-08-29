"""Pydantic schemas for Work risk analysis requests and responses."""

from typing import List, Optional, Union, Dict, Any
from pydantic import BaseModel, Field


class WorkInput(BaseModel):
    """Input payload representing an individual MPLADS project work."""
    work_id: Union[int, str] = Field(..., description="Unique project identifier (e.g. 134703)")
    work_description: Optional[str] = Field(default="", description="Scope / description of the work")
    category: Optional[str] = Field(default="Normal/Others", description="Project sector category")
    mp_name: Optional[str] = Field(default="", description="Recommending Member of Parliament name")
    constituency: Optional[str] = Field(default="", description="Parliamentary Constituency")
    ida: Optional[str] = Field(default="", description="Implementing District Authority")
    recommended_amount: float = Field(..., description="Sanctioned estimated amount in ₹")
    final_amount: float = Field(..., description="Final settled payout in ₹")
    recommendation_date: Optional[str] = Field(default=None, description="ISO timestamp of recommendation")
    completed_date: Optional[str] = Field(default=None, description="ISO timestamp of completion sign-off")
    has_images: bool = Field(default=False, description="Whether photographic proof was uploaded")

    model_config = {
        "extra": "ignore",
        "json_schema_extra": {
            "example": {
                "work_id": 134703,
                "work_description": "Upgradation of Road from Madhavaram Village to Company Indlu",
                "category": "Normal/Others",
                "mp_name": "DAGGUMALLA PRASADA RAO",
                "constituency": "CHITTOOR",
                "ida": "CHITTOOR(DISTRICT COLLECTOR CHITTOOR_IDA)",
                "recommended_amount": 350000.0,
                "final_amount": 499993.0,
                "recommendation_date": "2024-01-10T00:00:00.000Z",
                "completed_date": "2025-01-31T00:00:00.000Z",
                "has_images": False
            }
        }
    }


class WorkMetrics(BaseModel):
    """Engineered and derived quantitative metrics for the evaluated work."""
    recommended_cost: float
    final_settled_cost: float
    cost_escalation_pct: str
    cost_escalation_ratio: float
    execution_duration_days: int
    has_photo_evidence: bool
    mp_completion_rate_pct: float
    category_z_score: float


class WorkRiskResponse(BaseModel):
    """Output evaluation report for a single work."""
    work_id: Union[int, str]
    execution_risk_score: float = Field(..., description="Calculated risk score between 0.0 and 100.0")
    risk_level: str = Field(..., description="COMPLIANT_LOW_RISK, MODERATE_RISK, or HIGH_EXECUTION_RISK")
    is_compliant: bool = Field(..., description="Whether the work passes compliance thresholds")
    metrics: WorkMetrics
    flagged_reasons: List[str] = Field(default_factory=list, description="Human-readable compliance findings")
    explainability_tags: List[str] = Field(default_factory=list, description="Machine-readable diagnostic tags")
    recommended_action: str = Field(..., description="Recommended governance or audit intervention")


class BatchWorkInput(BaseModel):
    """Batch input schema containing a list of works for an MP or district."""
    mp_name: Optional[str] = Field(default=None, description="Optional MP Name context")
    constituency: Optional[str] = Field(default=None, description="Optional Constituency context")
    works: List[WorkInput] = Field(..., description="List of work records to score")

    model_config = {
        "json_schema_extra": {
            "example": {
                "mp_name": "DAGGUMALLA PRASADA RAO",
                "constituency": "CHITTOOR",
                "works": [
                    {
                        "work_id": 134703,
                        "work_description": "Road Upgradation",
                        "category": "Normal/Others",
                        "recommended_amount": 350000.0,
                        "final_amount": 499993.0,
                        "recommendation_date": "2024-01-10T00:00:00.000Z",
                        "completed_date": "2025-01-31T00:00:00.000Z",
                        "has_images": False
                    },
                    {
                        "work_id": 134704,
                        "work_description": "Community Hall Construction",
                        "category": "Normal/Others",
                        "recommended_amount": 500000.0,
                        "final_amount": 495000.0,
                        "recommendation_date": "2024-06-01T00:00:00.000Z",
                        "completed_date": "2024-09-29T00:00:00.000Z",
                        "has_images": True
                    }
                ]
            }
        }
    }


class BatchRiskSummary(BaseModel):
    """Macro summary statistics for a batch analysis run."""
    total_works: int
    average_risk_score: float
    high_risk_count: int
    moderate_risk_count: int
    compliant_count: int
    missing_photos_count: int
    cost_overrun_works_count: int
    delayed_works_count: int
    total_recommended_amount: float
    total_final_amount: float
    total_cost_overrun_amount: float


class BatchRiskResponse(BaseModel):
    """Aggregated batch response with summary metrics and work breakdowns."""
    summary: BatchRiskSummary
    flagged_works: List[WorkRiskResponse]
    all_works: List[WorkRiskResponse]


class HealthResponse(BaseModel):
    """Health check payload."""
    status: str
    version: str
    model_loaded: bool
    artifacts: Dict[str, Any]
