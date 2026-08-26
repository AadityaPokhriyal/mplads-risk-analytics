# Model 2: Project Delay & Cost Overrun Engine — Input & Output Specification

> **Model Type:** **Multivariate Outlier Scorer & Rule-Weighted Engine**  
> **Target Scope:** Detecting Stalled Projects, Inflated Settled Costs, and Unverified Zero-Proof Completions  
> **File Location:** `Ml research and docs/MODEL_2_EXECUTION_DELAY_IO_SPEC.md`

---

## 1. Overview
This specification details the exact input features and output structure for **Model 2 (Pillar 2)**. It evaluates project execution performance, compliance with photographic verification mandates, and cost inflation deltas.

---

## 2. Model Inputs

### A. Raw Source Fields (from [`mplads_recommended_works_2026-08-22.csv`](file:///c:/Users/DIVYA/OneDrive/Desktop/3_Projects_and_Development/Projects/SIH/mplads-risk-analytics/Datasets/mplads_recommended_works_2026-08-22.csv) & [`mplads_completed_works_2026-08-22.csv`](file:///c:/Users/DIVYA/OneDrive/Desktop/3_Projects_and_Development/Projects/SIH/mplads-risk-analytics/Datasets/mplads_completed_works_2026-08-22.csv))

| Field Name | Type | Description | Sample Value |
| :--- | :---: | :--- | :--- |
| `Work ID` | Int | Unique project identifier | `134703` |
| `Work Description` | String | Description / scope of work | `"Upgradation of Road from..."` |
| `Category` | String | Project sector category | `"Normal/Others"` |
| `MP Name` | String | Recommending Member of Parliament | `"DAGGUMALLA PRASADA RAO"` |
| `Constituency` | String | Parliamentary Constituency | `"CHITTOOR"` |
| `IDA` | String | Implementing District Authority | `"CHITTOOR(DISTRICT COLLECTOR...)"` |
| `Recommended Amount (₹)`| Float | Initial sanctioned estimate | `350000.0` |
| `Recommendation Date` | String | ISO proposal timestamp | `"2024-01-10T00:00:00.000Z"` |
| `Final Amount (₹)` | Float | Final settled payout | `499993.0` |
| `Completed Date` | String | ISO completion sign-off timestamp | `"2025-01-31T00:00:00.000Z"` |
| `Has Images` | Boolean | Mobile app photo proof attached | `False` |

---

### B. Engineered Feature Vector (Fed into Execution Scoring Engine)

| Feature Name | Type | Calculation / Logic | Purpose | Range |
| :--- | :---: | :--- | :--- | :---: |
| `cost_escalation_ratio` | Float | `Final Amount / Recommended Amount` | Detects budget inflation | `0.1` to `5.0+` |
| `execution_days` | Int | `Completed Date - Recommendation Date` (in days) | Measures project lead time | `1` to `1,000+` |
| `missing_photo_penalty`| Float | `1.0` if `Has Images == False`, else `0.0` | Heavy penalty for zero-proof works | `0.0` or `1.0` |
| `mp_completion_rate` | Float | `MP Completed Works / MP Recommended Works * 100` | Contextual baseline for the MP | `0.0%` to `100%` |
| `category_cost_deviation`| Float | `Z-Score(Final Amount)` within same work category | Flags abnormal category spending | `-3.0` to `+5.0` |

---

### C. Live Real-Time API Input (JSON Request to `POST /api/predict/work`)

```json
{
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
  "has_images": false
}
```

---

## 3. Model Outputs

### A. Raw Model Output
* **`execution_outlier_score`:** Scaled float from 0.0 to 1.0 (e.g. `0.92`).
* **`compliance_status`:** `"NON_COMPLIANT"` / `"COMPLIANT"`.

---

### B. Processed JSON Response (Sent to Frontend)

#### 🔴 Case 1: High Execution Risk (Zero Photo Proof + Cost Overrun)
```json
{
  "work_id": 134703,
  "execution_risk_score": 92.0,
  "risk_level": "HIGH_EXECUTION_RISK",
  "is_compliant": false,
  "metrics": {
    "recommended_cost": 350000.0,
    "final_settled_cost": 499993.0,
    "cost_escalation_pct": "+42.85%",
    "execution_duration_days": 387,
    "has_photo_evidence": false
  },
  "flagged_reasons": [
    "Missing Mandatory Proof: Project signed off as completed with NO photographic evidence (Has Images = False)",
    "Cost Escalation: Final settled cost exceeded recommended estimate by 42.85% (₹1,49,993 overrun)",
    "Prolonged Duration: Project took 387 days against state average of 180 days"
  ],
  "explainability_tags": ["ZERO_PHOTO_EVIDENCE", "COST_OVERRUN", "CHRONIC_DELAY"],
  "recommended_action": "Withhold contractor final retention money and mandate geo-tagged inspection by District Vigilance Officer."
}
```

#### 🟢 Case 2: Low Execution Risk (Completed on Time with Photos)
```json
{
  "work_id": 134704,
  "execution_risk_score": 11.5,
  "risk_level": "COMPLIANT_LOW_RISK",
  "is_compliant": true,
  "metrics": {
    "recommended_cost": 500000.0,
    "final_settled_cost": 495000.0,
    "cost_escalation_pct": "-1.00%",
    "execution_duration_days": 120,
    "has_photo_evidence": true
  },
  "flagged_reasons": [],
  "explainability_tags": ["COMPLIANT", "VERIFIED_PHOTOS"],
  "recommended_action": "Standard audit closure approved."
}
```

---

## 4. Frontend UI Component Mapping

| Output Field | UI Component | Visual Representation |
| :--- | :--- | :--- |
| `execution_risk_score` (92.0) | **Risk Rating Gauge** | Amber/Red Meter (`92/100`) |
| `has_photo_evidence` (`false`) | **Photo Proof Badge** | Red Cross Icon (`❌ No Photos Uploaded`) |
| `cost_escalation_pct` (`+42.85%`)| **Cost Variance Indicator** | Red Upward Arrow (`▲ +42.85% Cost Delta`) |
| `flagged_reasons` | **Project Audit Drawer** | Bullet list of compliance infractions |
| `recommended_action` | **Collector Action Button** | *"Order Physical Site Inspection"* button |
