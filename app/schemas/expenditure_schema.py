# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

from pydantic import BaseModel, Field
from typing import List, Optional

class ExpenditureInput(BaseModel):
    work_id: str
    mp_name: str
    constituency: str
    ida: str
    vendor: str
    expenditure_amount: float = Field(..., gt=0)
    expenditure_date: str  # any parseable format — normalized internally
    work_description: Optional[str] = None
 
 
class ExpenditureBatchInput(BaseModel):
    transactions: List[ExpenditureInput]
 
 
class FeatureContribution(BaseModel):
    feature: str
    value: float
    contribution_to_risk: float
 
 
class PredictionOutput(BaseModel):
    work_id: str = Field(..., alias="Work ID")
    risk_score: float
    risk_level: str
    is_anomaly: bool
    metrics: dict
    raw_anomaly_score: float
    top_contributing_features: Optional[List[FeatureContribution]] = None
 
    class Config:
        populate_by_name = True
 
 
class BatchPredictionItem(BaseModel):
    work_id: str
    mp_name: str
    vendor: str
    expenditure_amount: float
    risk_score: float
    risk_level: str
    is_anomaly: bool
 
 
class BatchPredictionOutput(BaseModel):
    summary: dict
    results: List[BatchPredictionItem]
 
 