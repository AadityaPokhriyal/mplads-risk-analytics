# Model 2: Project Execution Delay & Stalling Engine — Input & Output Specification

> **Model Type:** **Multi-Stage Execution Latency Engine & Multivariate Isolation Forest**  
> **Target Scope:** Detecting Stalled Projects (>365d), Stage-Wise Bottlenecks, Cost Escalation, & Zero-Proof Ghost Completions  
> **Dataset Source:** `New Datasets/` (`Works Recommended.csv`, `Works Sanctioned.csv`, `Works Completed.csv`, `Expenditure on Completed and On-going Works as on Date.csv`)  
> **File Location:** `ML Research and docs/MODEL_2_EXECUTION_DELAY_IO_SPEC.md`  

---

## 1. Overview

This specification defines the input features, feature engineering pipeline, API schemas, and response payload structure for **Model 2 (Pillar 2: Project Execution Delay & Cost Overrun Engine)**. It processes live project milestones from the MPLADS portal, evaluates multi-stage execution latencies against state/sector baselines, enforces mandatory photographic proof compliance, and predicts execution risk scores for active and completed works.

---

## 2. Model Inputs

### A. Raw Source Fields (Derived from `New Datasets/`)

| Field Name | Type | Description | Source Dataset | Sample Value |
| :--- | :---: | :--- | :--- | :--- |
| `work_id` | String | Standardized unique project code | All CSVs | `"WS/MP620/2024-2025/133166"` |
| `work_description` | String | Civil work title and physical scope | Recommended / Sanctioned | `"Construction of Community Bhavan..."` |
| `work_category` | String | Project sector category | Recommended / Sanctioned | `"Normal/Others"` |
| `state` | String | State / Union Territory | All CSVs | `"Karnataka"` |
| `mp_name` | String | Recommending Member of Parliament | All CSVs | `"Pralhad Venkatesh Joshi"` |
| `constituency` | String | Parliamentary Constituency | All CSVs | `"DHARWAD"` |
| `ida` | String | Implementing District Authority | All CSVs | `"DHARWAD(DEPUTY COMMISSIONER...)"` |
| `recommended_amount` | Float | Initial proposed project budget (₹) | Works Recommended | `497185.0` |
| `recommended_date` | String | Proposal date (`YYYY-MM-DD`) | Works Recommended | `"2024-07-08"` |
| `sanction_amount` | Float | Approved administrative budget (₹) | Works Sanctioned | `497185.0` |
| `sanction_date` | String | Administrative sanction date (`YYYY-MM-DD`)| Works Sanctioned | `"2024-07-09"` |
| `work_status` | String | Current execution milestone | Works Sanctioned | `"Physical Inspection"` |
| `amount_disbursed` | Float | Final / cumulative disbursed amount (₹) | Works Completed / Exp | `448127.0` |
| `completion_date` | String | Project completion date (`YYYY-MM-DD` or `null`) | Works Completed | `"2024-09-05"` |
| `has_photo_evidence` | Boolean| Mobile app geo-tagged photo verified | Works Completed (`Image`) | `false` |

---

### B. Engineered Feature Vector (Fed into ML Scorer)

| Feature Name | Type | Formula / Logic | Purpose | Normal Range |
| :--- | :---: | :--- | :--- | :---: |
| `rec_to_sanc_days` | Int | `Sanction Date - Recommended Date` | Measures administrative approval latency | 0 to 120 days |
| `sanc_to_comp_days` | Int | `Completion Date - Sanction Date` (or `Current Date - Sanction Date` if ongoing) | Measures construction & inspection turnaround | 30 to 240 days |
| `total_lead_time_days` | Int | `Completion Date - Recommended Date` | Total lifecycle turnaround | 60 to 365 days |
| `is_stalled_365` | Boolean| `True` if ongoing project age > 365 days, else `False` | Detects chronic zombie projects | `False` |
| `missing_photo_penalty`| Float | `40.0` if `has_photo_evidence == False`, else `0.0` | High governance penalty for unverified payouts | `0.0` or `40.0` |
| `status_risk_factor` | Float | Weighted factor: `Physical Inspection` (0.8), `Vendor Identification` (0.7), `Partially Completed` (0.5), `Sanction` (0.4) | Quantifies milestone chokepoints | `0.1` to `1.0` |
| `cost_escalation_ratio` | Float | `amount_disbursed / sanction_amount` | Flags budget inflation | `0.5` to `1.0` |
| `mp_completion_ratio` | Float | `MP Completed Works / MP Sanctioned Works` | Contextual track record of the MP | `0.0` to `1.0` |

---

### C. Live Real-Time API Input (JSON Request to `POST /api/predict/work-delay`)

```json
{
  "work_id": "WS/MP620/2024-2025/133166",
  "work_description": "Construction of Community Bhavan at Navalgund TQ Belavatagi Village",
  "work_category": "Normal/Others",
  "state": "Karnataka",
  "mp_name": "Pralhad Venkatesh Joshi",
  "constituency": "DHARWAD",
  "ida": "DHARWAD(DEPUTY COMMISSIONER DHARWAR_IDA)",
  "recommended_amount": 497185.0,
  "recommended_date": "2024-07-08",
  "sanction_amount": 497185.0,
  "sanction_date": "2024-07-09",
  "work_status": "Physical Inspection",
  "amount_disbursed": 448127.0,
  "completion_date": null,
  "has_photo_evidence": false
}
```

---

## 3. Model Outputs & Response Payloads

### A. Raw Model Scores
* **`execution_risk_score`:** Scaled float from `0.0` to `100.0` (e.g. `88.5`).
* **`risk_level`:** Categorical string (`"HIGH_EXECUTION_RISK"`, `"MODERATE_RISK"`, `"COMPLIANT_LOW_RISK"`).
* **`is_compliant`:** Boolean (`true` / `false`).

---

### B. Processed JSON Response (Sent to Frontend & Alerts)

#### 🔴 Case 1: High Execution Risk (Stalled Project + Zero Photo Evidence)
```json
{
  "work_id": "WS/MP620/2024-2025/133166",
  "execution_risk_score": 88.5,
  "risk_level": "HIGH_EXECUTION_RISK",
  "is_compliant": false,
  "lifecycle_metrics": {
    "recommended_amount": 497185.0,
    "sanction_amount": 497185.0,
    "amount_disbursed": 448127.0,
    "disbursement_pct": "90.13%",
    "current_stage": "Physical Inspection",
    "approval_latency_days": 1,
    "current_project_age_days": 416,
    "is_stalled": true,
    "has_photo_evidence": false
  },
  "flagged_reasons": [
    "Chronic Project Stalling: Project has been in 'Physical Inspection' stage for 416 days (national threshold: 180 days).",
    "Missing Mandatory Photographic Proof: 90.13% of funds disbursed with NO geo-tagged inspection photos uploaded.",
    "Blocked Public Capital: ₹4.48 Lakh disbursed without final project closure certificate."
  ],
  "explainability_tags": [
    "CHRONIC_STALLING_365D",
    "ZERO_PHOTO_EVIDENCE",
    "PHYSICAL_INSPECTION_BOTTLENECK"
  ],
  "recommended_action": "Issue formal show-cause notice to DHARWAD District Authority and order mandatory on-site physical verification by District Vigilance Officer."
}
```

#### 🟢 Case 2: Low Execution Risk (Completed on Time with Verified Photos)
```json
{
  "work_id": "WS/MP418/2024-2025/133409",
  "execution_risk_score": 12.0,
  "risk_level": "COMPLIANT_LOW_RISK",
  "is_compliant": true,
  "lifecycle_metrics": {
    "recommended_amount": 450000.0,
    "sanction_amount": 448127.0,
    "amount_disbursed": 448127.0,
    "disbursement_pct": "100.00%",
    "current_stage": "Work Completed",
    "approval_latency_days": 14,
    "execution_duration_days": 85,
    "is_stalled": false,
    "has_photo_evidence": true
  },
  "flagged_reasons": [],
  "explainability_tags": [
    "ON_TIME_COMPLETION",
    "VERIFIED_PHOTOS",
    "WITHIN_BUDGET"
  ],
  "recommended_action": "Standard audit sign-off and Final Completion Certificate (FCC) approved."
}
```

---

## 4. Frontend UI Component Mapping

| API Output Field | Target UI Component | Visual Presentation in Dashboard |
| :--- | :--- | :--- |
| `execution_risk_score` (`88.5`) | **Risk Rating Radial Gauge** | Crimson Meter (`88.5 / 100`) |
| `current_stage` (`"Physical Inspection"`) | **Lifecycle Stepper Badge** | Step Indicator with Amber Warning on delayed stage |
| `has_photo_evidence` (`false`) | **Geo-Photo Compliance Tag** | Red Warning Pill (`❌ 0 Photos Uploaded`) |
| `current_project_age_days` (`416`) | **Stalling Clock** | Red Highlight (`⏱️ 416 Days Active - Stalled`) |
| `flagged_reasons` | **Collector Audit Drawer** | Structured list of specific governance infractions |
| `recommended_action` | **District Action Trigger** | *"Order Vigilance Physical Inspection"* action button |

---

## 5. Integration Code Snippet (FastAPI Endpoint)

```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List
import datetime

router = APIRouter(prefix="/api/predict", tags=["Execution Risk Engine"])

class WorkExecutionInput(BaseModel):
    work_id: str = Field(..., example="WS/MP620/2024-2025/133166")
    work_description: str
    work_category: str = "Normal/Others"
    state: str
    mp_name: str
    constituency: str
    ida: str
    recommended_amount: float
    recommended_date: datetime.date
    sanction_amount: float
    sanction_date: datetime.date
    work_status: str
    amount_disbursed: float
    completion_date: Optional[datetime.date] = None
    has_photo_evidence: bool = False

@router.post("/work-delay")
def predict_execution_risk(payload: WorkExecutionInput):
    # 1. Calculate age & delays
    today = datetime.date.today()
    approval_latency = (payload.sanction_date - payload.recommended_date).days
    
    if payload.completion_date:
        exec_duration = (payload.completion_date - payload.sanction_date).days
        is_stalled = False
        project_age = exec_duration
    else:
        project_age = (today - payload.sanction_date).days
        is_stalled = project_age > 365

    # 2. Risk scoring calculation
    risk_score = 0.0
    flags = []
    tags = []

    # Check photo evidence
    if not payload.has_photo_evidence:
        risk_score += 40.0
        flags.append("Missing Mandatory Proof: Work recorded with NO photographic evidence.")
        tags.append("ZERO_PHOTO_EVIDENCE")

    # Check stalling
    if is_stalled:
        risk_score += 45.0
        flags.append(f"Chronic Stalling: Project has been in '{payload.work_status}' for {project_age} days (>365d).")
        tags.append("CHRONIC_STALLING_365D")
    elif project_age > 180 and not payload.completion_date:
        risk_score += 20.0
        flags.append(f"Moderate Delay: Project active for {project_age} days (>180d).")
        tags.append("MODERATE_DELAY")

    # Determine risk level
    risk_score = min(100.0, risk_score)
    if risk_score >= 70.0:
        level = "HIGH_EXECUTION_RISK"
        action = "Issue show-cause notice and mandate on-site inspection by District Vigilance Officer."
    elif risk_score >= 30.0:
        level = "MODERATE_RISK"
        action = "Request expedited milestone status update from Implementing District Authority."
    else:
        level = "COMPLIANT_LOW_RISK"
        action = "Standard audit sign-off and Final Completion Certificate approved."

    return {
        "work_id": payload.work_id,
        "execution_risk_score": round(risk_score, 1),
        "risk_level": level,
        "is_compliant": risk_score < 30.0,
        "lifecycle_metrics": {
            "recommended_amount": payload.recommended_amount,
            "sanction_amount": payload.sanction_amount,
            "amount_disbursed": payload.amount_disbursed,
            "current_stage": payload.work_status,
            "approval_latency_days": approval_latency,
            "current_project_age_days": project_age,
            "is_stalled": is_stalled,
            "has_photo_evidence": payload.has_photo_evidence
        },
        "flagged_reasons": flags,
        "explainability_tags": tags,
        "recommended_action": action
    }
```
