# MPLADS Project Execution Delay & Stalling Engine — FastAPI Endpoint Documentation

> **Service Component:** **Pillar 2: Project Execution Delay & Cost Overrun Engine**  
> **Source File:** [`app/main.py`](file:///c:/Users/DIVYA/OneDrive/Desktop/3_Projects_and_Development/Projects/SIH/mplads-risk-analytics/app/main.py)  
> **Model Module:** [`ExecutionModelModule.py`](file:///c:/Users/DIVYA/OneDrive/Desktop/3_Projects_and_Development/Projects/SIH/mplads-risk-analytics/ExecutionModelModule.py)  
> **Trained Artifact:** [`models/execution_delay_model.joblib`](file:///c:/Users/DIVYA/OneDrive/Desktop/3_Projects_and_Development/Projects/SIH/mplads-risk-analytics/models/execution_delay_model.joblib)  
> **Base URL:** `http://localhost:3000` (Configurable via `PORT` in `.env`)

---

## 1. Overview & Architecture

The **Project Execution Delay & Stalling Engine** is a high-performance REST microservice built with **FastAPI**. It evaluates live project milestones against historical state/national baselines, detects multi-stage bureaucratic bottlenecks, enforces mandatory mobile geotagged photographic proof compliance, and flags budget overruns.

```
                          +-----------------------------------+
                          |         Incoming Request          |
                          |   (Single / Batch Work Milestones)|
                          +-----------------------------------+
                                            |
                                            v
                          +-----------------------------------+
                          |      FastAPI Endpoint Router      |
                          |   /api/predict/work[s]-delay      |
                          +-----------------------------------+
                                            |
                                            v
                          +-----------------------------------+
                          |  Fast In-Memory Baseline Engine   |
                          |  Matches MP completion ratio &    |
                          |  State approval delay baselines   |
                          +-----------------------------------+
                                            |
                                            v
                          +-----------------------------------+
                          |      Hybrid Inference Scorer      |
                          |  1. Isolation Forest Latency ML   |
                          |  2. Statutory Governance Rules    |
                          +-----------------------------------+
                                            |
                 +--------------------------+--------------------------+
                 |                                                     |
                 v                                                     v
   +---------------------------+                         +---------------------------+
   |   Single Work Scorer      |                         |  Vectorized Batch Scorer  |
   | • Metric synthesis        |                         | • Bulk throughput (<50ms) |
   | • Infraction narratives   |                         | • Portfolio aggregations  |
   | • Explainability tags     |                         | • Severity breakdown      |
   +---------------------------+                         +---------------------------+
                 |                                                     |
                 +--------------------------+--------------------------+
                                            |
                                            v
                          +-----------------------------------+
                          |        JSON API Response          |
                          |   (0-100 Score, Level, Actions)   |
                          +-----------------------------------+
```

---

## 2. Endpoints Summary Table

| HTTP Method | Route Path | Description | Typical Latency | Auth / Scope |
| :--- | :--- | :--- | :--- | :--- |
| `POST` | `/api/predict/work-delay` | Score ONE work milestone for delay, stalling, photos, & cost overrun | `< 5 ms` | Internal / Express Proxy |
| `POST` | `/api/predict/works-delay` | High-throughput batch scoring for multiple works (MP / District portfolio) | `< 50 ms` (200 works) | Internal / Express Proxy |
| `GET` | `/health` | System health check and model loading verification | `< 1 ms` | Public / Monitoring |

---

## 3. Detailed Endpoint Specifications

### 🟢 Endpoint 1: Single Work Execution Scoring

#### `POST /api/predict/work-delay`

Evaluates a single project record across its lifecycle, computing statutory governance compliance, stage delays, and administrative audit recommendations.

#### Request Headers
```http
Content-Type: application/json
Accept: application/json
```

#### Request Body Schema (`WorkExecutionInput`)

| Field Name | Type | Required | Description | Sample Value |
| :--- | :---: | :---: | :--- | :--- |
| `work_id` | `string` | **Yes** | Standardized unique project code | `"WS/MP620/2024-2025/133166"` |
| `work_description` | `string` | **Yes** | Civil work title & scope of work | `"Construction of Community Bhavan..."` |
| `work_category` | `string` | No | Project sector classification | `"Normal/Others"` *(default)* |
| `state` | `string` | **Yes** | State / Union Territory | `"Karnataka"` |
| `mp_name` | `string` | **Yes** | Recommending Member of Parliament | `"Pralhad Venkatesh Joshi"` |
| `constituency` | `string` | **Yes** | Parliamentary Constituency | `"DHARWAD"` |
| `ida` | `string` | **Yes** | Implementing District Authority | `"DHARWAD(DEPUTY COMMISSIONER...)"` |
| `recommended_amount` | `number` | **Yes** | Initial proposed budget in ₹ ($\ge 0$) | `497185.0` |
| `recommended_date` | `string` | **Yes** | Recommendation date (`YYYY-MM-DD` or `DD-Mon-YYYY`) | `"2024-07-08"` |
| `sanction_amount` | `number` | **Yes** | Approved administrative sanction in ₹ ($\ge 0$) | `497185.0` |
| `sanction_date` | `string` | **Yes** | Sanction date (`YYYY-MM-DD` or `DD-Mon-YYYY`) | `"2024-07-09"` |
| `work_status` | `string` | **Yes** | Current milestone (`Physical Inspection`, `Sanction`, `Work Completed`, etc.) | `"Physical Inspection"` |
| `amount_disbursed` | `number` | **Yes** | Cumulative fund amount disbursed in ₹ ($\ge 0$) | `448127.0` |
| `completion_date` | `string` | No | Completion date if completed, else `null` | `null` |
| `has_photo_evidence` | `boolean`| No | Mobile app geo-tagged inspection photo verified | `false` *(default)* |

---

#### Response Body Schema (`WorkExecutionPredictionOutput`)

```json
{
  "work_id": "string",
  "execution_risk_score": "number (0.0 to 100.0)",
  "risk_level": "string (HIGH_EXECUTION_RISK | MODERATE_RISK | COMPLIANT_LOW_RISK)",
  "is_compliant": "boolean",
  "lifecycle_metrics": {
    "recommended_amount": "number",
    "sanction_amount": "number",
    "amount_disbursed": "number",
    "disbursement_pct": "string (percentage)",
    "current_stage": "string",
    "approval_latency_days": "integer",
    "current_project_age_days": "integer (optional)",
    "execution_duration_days": "integer (optional)",
    "is_stalled": "boolean",
    "has_photo_evidence": "boolean"
  },
  "flagged_reasons": ["string"],
  "explainability_tags": ["string"],
  "recommended_action": "string"
}
```

---

#### Example 1: 🔴 High Execution Risk (Stalled Project + Zero Photographic Proof)

##### cURL Request
```bash
curl -X POST "http://localhost:3000/api/predict/work-delay" \
  -H "Content-Type: application/json" \
  -d '{
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
  }'
```

##### JSON Response (`200 OK`)
```json
{
  "work_id": "WS/MP620/2024-2025/133166",
  "execution_risk_score": 85.0,
  "risk_level": "HIGH_EXECUTION_RISK",
  "is_compliant": false,
  "lifecycle_metrics": {
    "recommended_amount": 497185.0,
    "sanction_amount": 497185.0,
    "amount_disbursed": 448127.0,
    "disbursement_pct": "90.13%",
    "current_stage": "Physical Inspection",
    "approval_latency_days": 1,
    "current_project_age_days": 418,
    "is_stalled": true,
    "has_photo_evidence": false
  },
  "flagged_reasons": [
    "Missing Mandatory Photographic Proof: 90.13% of funds disbursed with NO geo-tagged inspection photos uploaded.",
    "Chronic Project Stalling: Project has been in 'Physical Inspection' stage for 418 days (national threshold: 180 days).",
    "Blocked Public Capital: ₹4.48 Lakh disbursed without final project closure certificate."
  ],
  "explainability_tags": [
    "ZERO_PHOTO_EVIDENCE",
    "CHRONIC_STALLING_365D",
    "PHYSICAL_INSPECTION_BOTTLENECK"
  ],
  "recommended_action": "Issue formal show-cause notice to DHARWAD District Authority and order mandatory on-site physical verification by District Vigilance Officer."
}
```

---

#### Example 2: 🟢 Low Execution Risk (Completed on Time + Photos Verified)

##### cURL Request
```bash
curl -X POST "http://localhost:3000/api/predict/work-delay" \
  -H "Content-Type: application/json" \
  -d '{
    "work_id": "WS/MP418/2024-2025/133409",
    "work_description": "PCC Road from Permeshwar Bhagat house to Ramdev Master house",
    "work_category": "Normal/Others",
    "state": "Bihar",
    "mp_name": "Pradeep Kumar Singh",
    "constituency": "ARARIA",
    "ida": "ARARIA(DISTRICT PLANNING OFFICER ARARIA_IDA)",
    "recommended_amount": 450000.0,
    "recommended_date": "2024-06-01",
    "sanction_amount": 448127.0,
    "sanction_date": "2024-06-15",
    "work_status": "Work Completed",
    "amount_disbursed": 448127.0,
    "completion_date": "2024-09-05",
    "has_photo_evidence": true
  }'
```

##### JSON Response (`200 OK`)
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
    "current_project_age_days": 82,
    "execution_duration_days": 82,
    "is_stalled": false,
    "has_photo_evidence": true
  },
  "flagged_reasons": [],
  "explainability_tags": [
    "VERIFIED_PHOTOS",
    "WITHIN_BUDGET",
    "ON_TIME_COMPLETION"
  ],
  "recommended_action": "Standard audit sign-off and Final Completion Certificate (FCC) approved."
}
```

---

### 🟡 Endpoint 2: High-Throughput Batch Scoring

#### `POST /api/predict/works-delay`

Performs high-speed vectorized inference across multiple works simultaneously. Ideal for loading an MP's full portfolio or analyzing a whole district without per-request network overhead.

#### Request Body Schema (`WorkExecutionBatchInput`)
```json
{
  "works": [
    {
      "work_id": "WS/MP620/2024-2025/133166",
      "work_description": "Construction of Community Bhavan...",
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
    },
    {
      "work_id": "WS/MP418/2024-2025/133409",
      "work_description": "PCC Road construction...",
      "work_category": "Normal/Others",
      "state": "Bihar",
      "mp_name": "Pradeep Kumar Singh",
      "constituency": "ARARIA",
      "ida": "ARARIA(DISTRICT PLANNING OFFICER ARARIA_IDA)",
      "recommended_amount": 450000.0,
      "recommended_date": "2024-06-01",
      "sanction_amount": 448127.0,
      "sanction_date": "2024-06-15",
      "work_status": "Work Completed",
      "amount_disbursed": 448127.0,
      "completion_date": "2024-09-05",
      "has_photo_evidence": true
    }
  ]
}
```

#### Response Body Schema (`WorkExecutionBatchOutput`)
```json
{
  "summary": {
    "total_evaluated": 2,
    "high_risk_count": 1,
    "moderate_risk_count": 0,
    "compliant_count": 1,
    "stalled_count": 1,
    "zero_photo_count": 1
  },
  "results": [
    {
      "work_id": "WS/MP620/2024-2025/133166",
      "work_description": "Construction of Community Bhavan...",
      "state": "Karnataka",
      "mp_name": "Pralhad Venkatesh Joshi",
      "execution_risk_score": 85.0,
      "risk_level": "HIGH_EXECUTION_RISK",
      "is_compliant": false,
      "is_stalled": true,
      "has_photo_evidence": false,
      "current_stage": "Physical Inspection",
      "flagged_reasons": [
        "Missing Mandatory Photographic Proof: 90.13% of funds disbursed with NO geo-tagged inspection photos uploaded.",
        "Chronic Project Stalling: Project has been in 'Physical Inspection' stage for 418 days (national threshold: 180 days).",
        "Blocked Public Capital: ₹4.48 Lakh disbursed without final project closure certificate."
      ],
      "explainability_tags": [
        "ZERO_PHOTO_EVIDENCE",
        "CHRONIC_STALLING_365D",
        "PHYSICAL_INSPECTION_BOTTLENECK"
      ],
      "recommended_action": "Issue formal show-cause notice to DHARWAD District Authority and order mandatory on-site physical verification by District Vigilance Officer."
    },
    {
      "work_id": "WS/MP418/2024-2025/133409",
      "work_description": "PCC Road construction...",
      "state": "Bihar",
      "mp_name": "Pradeep Kumar Singh",
      "execution_risk_score": 12.0,
      "risk_level": "COMPLIANT_LOW_RISK",
      "is_compliant": true,
      "is_stalled": false,
      "has_photo_evidence": true,
      "current_stage": "Work Completed",
      "flagged_reasons": [],
      "explainability_tags": [
        "VERIFIED_PHOTOS",
        "WITHIN_BUDGET",
        "ON_TIME_COMPLETION"
      ],
      "recommended_action": "Standard audit sign-off and Final Completion Certificate (FCC) approved."
    }
  ]
}
```

---

### 🔵 Endpoint 3: System Health Check

#### `GET /health`

Returns operational status and verifies if both Pillar 1 (Expenditure) and Pillar 2 (Execution Delay) models are loaded into RAM.

#### Response (`200 OK`)
```json
{
  "status": "ok",
  "expenditure_model_loaded": true,
  "execution_model_loaded": true
}
```

---

## 4. HTTP Status Codes & Error Handling

| HTTP Code | Reason | Example Response Body |
| :---: | :--- | :--- |
| `200` | **Success** | Returns `WorkExecutionPredictionOutput` or `WorkExecutionBatchOutput`. |
| `400` | **Bad Request** | `{"detail": "No projects provided."}` or invalid date format. |
| `422` | **Unprocessable Entity** | Pydantic validation error (e.g. missing required field `work_id` or negative amount). |
| `503` | **Service Unavailable** | `{"detail": "Execution Delay Engine is not loaded."}` |
| `500` | **Internal Server Error** | `{"detail": "Execution risk scoring failed: <traceback>"}` |

---

## 5. Express.js Backend Integration Snippet

If your Node.js / Express backend proxies requests to FastAPI, you can call the batch endpoint like this:

```javascript
import axios from "axios";

const ML_ENGINE_URL = process.env.ML_API_URL || "http://127.0.0.1:3000";

export async function scoreMPWorksRisk(worksArray) {
  try {
    const payload = {
      works: worksArray.map(w => ({
        work_id: w.work_id,
        work_description: w.work_description,
        work_category: w.work_category || "Normal/Others",
        state: w.state,
        mp_name: w.mp_name,
        constituency: w.constituency,
        ida: w.ida,
        recommended_amount: Number(w.recommended_amount) || 0,
        recommended_date: w.recommended_date,
        sanction_amount: Number(w.sanction_amount) || 0,
        sanction_date: w.sanction_date,
        work_status: w.work_status || "Ongoing",
        amount_disbursed: Number(w.amount_disbursed) || 0,
        completion_date: w.completion_date || null,
        has_photo_evidence: Boolean(w.has_photo_evidence),
      }))
    };

    const response = await axios.post(`${ML_ENGINE_URL}/api/predict/works-delay`, payload, {
      timeout: 5000,
    });

    return response.data;
  } catch (err) {
    console.error("Failed to score execution risk with ML Engine:", err.message);
    throw err;
  }
}
```
