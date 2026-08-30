# MPLADS Expenditure Anomaly Engine — FastAPI API Documentation

This document provides a detailed technical analysis and API specification for the **FastAPI Application** powering the **MPLADS Expenditure Anomaly Engine** (`app/main.py`).

---

## 1. Overview & Architecture

The FastAPI application serves as the real-time scoring and inference microservice for **Pillar 1: Expenditure Anomaly Detection** in the MPLADS Risk Analytics platform. It integrates an **Isolation Forest ML model** trained on historical expenditure data with **SHAP (SHapley Additive exPlanations)** to provide real-time risk scoring, anomaly detection, and explainable AI metrics for government fund disbursements.

```
                         +-----------------------------------+
                         |         Incoming Request          |
                         | (Single / Batch Transaction Data) |
                         +-----------------------------------+
                                           |
                                           v
                         +-----------------------------------+
                         |      FastAPI Endpoint Router      |
                         |  /api/predict/expenditure[s]      |
                         +-----------------------------------+
                                           |
                                           v
                         +-----------------------------------+
                         |     Contextual Feature Engine     |
                         |   Merges with rolling history &   |
                         |   computes threshold/velocity     |
                         +-----------------------------------+
                                           |
                                           v
                         +-----------------------------------+
                         |     Isolation Forest Inference    |
                         |    Scores transaction(s) & maps  |
                         |    raw score -> Risk Score 0-100  |
                         +-----------------------------------+
                                           |
               +---------------------------+---------------------------+
               | (Single Txn Only)                                     | (Batch Txn)
               v                                                       v
 +----------------------------+                          +----------------------------+
 |   SHAP Explainability      |                          |  Vectorized Batch Engine   |
 | Extracts top feature risk  |                          | Returns risk scores &      |
 | contribution drivers       |                          | summary statistics         |
 +----------------------------+                          +----------------------------+
               |                                                       |
               +---------------------------+---------------------------+
                                           |
                                           v
                         +-----------------------------------+
                         |        JSON API Response          |
                         +-----------------------------------+
```

### Key Architectural Highlights
- **Lifespan Context Management**: On startup, the application loads the trained `IsolationForest` model (`models/expenditure_anomaly_model.joblib`), loads & cleans the historical transaction dataset, and builds a fast dictionary lookup for MP budget allocations.
- **Dynamic Contextual Feature Engineering**: Incoming transactions are merged with historical transactions (filtered by `LOOKBACK_DAYS`) to dynamically calculate rolling 90-day vendor payout velocity, cumulative vendor spend, threshold proximity, and district authority monthly load.
- **Explainable AI (XAI)**: The single prediction endpoint computes exact SHAP contribution values for each feature to inform audit officers *why* a transaction was flagged.
- **Fast Vectorized Batch Processing**: The batch prediction endpoint bypasses per-row SHAP calculations for high-performance throughput on bulk disbursements.

---

## 2. Configuration & Environment Variables

The application is configured using environment variables (typically defined in a `.env` file at the repository root).

| Variable Name | Required | Default Value | Description |
| :--- | :---: | :--- | :--- |
| `MODEL_PATH` | **Yes** | `models/expenditure_anomaly_model.joblib` | Relative or absolute path to the serialized model state file. |
| `HISTORY_CSV_PATH` | **Yes** | `New Datasets/Expenditures Lok Sabha.csv` | Path to the historical Lok Sabha expenditure CSV file used for rolling-window feature calculations. |
| `ALLOCATION_CSV_PATH` | **Yes** | `New Datasets/Allocated Limit MP Lok Sabha.csv` | Path to the MP budget allocation CSV file used to map `MP Name` -> Total Allocated Rupees. |
| `APPROVAL_THRESHOLDS` | No | `50000,500000,5000000` | Comma-separated financial threshold limits (in ₹) per General Financial Rules (GFR). |
| `LOOKBACK_DAYS` | No | `365` | Number of past days to retain from history when calculating rolling velocity features. |
| `CORS_ORIGINS` | No | `*` | Comma-separated allowed CORS origins (e.g. `http://localhost:3000,http://localhost:5173` or `*`). |

---

## 3. Pydantic Request & Response Schemas

All schemas are defined in `app/schemas/expenditure_schema.py`.

### 3.1 Input Schemas

#### `ExpenditureInput`
Represents a single transaction payload submitted for analysis.

```python
class ExpenditureInput(BaseModel):
    work_id: str                      # Unique identifier for the MPLADS work order
    mp_name: str                      # Name of the Hon'ble Member of Parliament
    constituency: str                 # Parliamentary Constituency name
    ida: str                          # Implementing District Authority name
    vendor: str                       # Vendor or contractor name receiving disbursement
    expenditure_amount: float         # Disbursed amount in ₹ (must be > 0)
    expenditure_date: str             # Transaction date (any parseable format, e.g. "2026-07-02", "02-Jul-2026")
    work_description: Optional[str]   # Optional work description
```

#### `ExpenditureBatchInput`
Payload for scoring multiple transactions in bulk.

```python
class ExpenditureBatchInput(BaseModel):
    transactions: List[ExpenditureInput]
```

---

### 3.2 Output Schemas

#### `FeatureContribution`
Detail of an individual feature's contribution to the overall risk score (SHAP explanation).

```python
class FeatureContribution(BaseModel):
    feature: str                    # Name of the engineered feature
    value: float                    # Actual numeric feature value for this row
    contribution_to_risk: float     # SHAP risk contribution score (positive values increase risk)
```

#### `PredictionOutput`
Full response object returned for a single transaction prediction (`POST /api/predict/expenditure`).

```python
class PredictionOutput(BaseModel):
    work_id: str = Field(..., alias="Work ID")    # Work ID string
    risk_score: float                              # Risk score (0.0 to 100.0)
    risk_level: str                                # Risk classification label
    is_anomaly: bool                               # True if Isolation Forest flags as anomaly
    metrics: dict                                  # Key computed feature metrics
    raw_anomaly_score: float                       # Raw IsolationForest decision_function value
    top_contributing_features: Optional[List[FeatureContribution]] = None  # Top SHAP reasons
```

#### `BatchPredictionItem`
Individual item result inside a batch response.

```python
class BatchPredictionItem(BaseModel):
    work_id: str
    mp_name: str
    vendor: str
    expenditure_amount: float
    risk_score: float
    risk_level: str
    is_anomaly: bool
```

#### `BatchPredictionOutput`
Response object returned for a batch prediction (`POST /api/predict/expenditures`).

```python
class BatchPredictionOutput(BaseModel):
    summary: dict                        # Aggregate breakdown by risk level (e.g. {"LOW_RISK": 10, "CRITICAL_ANOMALY": 2})
    results: List[BatchPredictionItem]   # List of transaction predictions maintaining submission order
```

---

## 4. Endpoint Specifications

### 4.1 Health Check Endpoint

#### `GET /health`
Checks whether the FastAPI application is running and verifies if the machine learning model is loaded into memory.

- **URL**: `/health`
- **Method**: `GET`
- **Authentication**: None required

#### Success Response (`200 OK`)
```json
{
  "status": "ok",
  "model_loaded": true
}
```

---

### 4.2 Single Expenditure Anomaly Scoring (with SHAP Explainability)

#### `POST /api/predict/expenditure`
Scores a single incoming transaction and generates a SHAP explanation detailing the top 3 feature drivers behind the score.

- **URL**: `/api/predict/expenditure`
- **Method**: `POST`
- **Headers**: `Content-Type: application/json`

#### Example Request Body
```json
{
  "work_id": "WS/MP18239/2025-2026/214753",
  "mp_name": "ZIA UR REHMAN",
  "constituency": "Sambhal",
  "ida": "District Magistrate Sambhal",
  "vendor": "R G SUPLLIER",
  "expenditure_amount": 49800.0,
  "expenditure_date": "2026-07-02",
  "work_description": "Construction of Interlocking Road"
}
```

#### Example Success Response (`200 OK`)
```json
{
  "Work ID": "WS/MP18239/2025-2026/214753",
  "risk_score": 78.4,
  "risk_level": "CRITICAL_ANOMALY",
  "is_anomaly": true,
  "metrics": {
    "amount": 49800.0,
    "threshold_proximity_pct": 96.08,
    "vendor_30d_frequency": 18,
    "cumulative_vendor_spend_vs_threshold_pct": 88.25,
    "budget_impact_pct": 0.1,
    "ida_monthly_txns": 84
  },
  "raw_anomaly_score": -0.1423,
  "top_contributing_features": [
    {
      "feature": "threshold_proximity_pct",
      "value": 96.08,
      "contribution_to_risk": 0.0842
    },
    {
      "feature": "vendor_payout_velocity",
      "value": 18.0,
      "contribution_to_risk": 0.0615
    },
    {
      "feature": "cumulative_vendor_spend_vs_threshold_pct",
      "value": 88.25,
      "contribution_to_risk": 0.0431
    }
  ]
}
```

---

### 4.3 Batch Expenditure Anomaly Scoring (High-Performance)

#### `POST /api/predict/expenditures`
Scores multiple incoming transactions concurrently using vectorized inference. SHAP calculation is omitted for high performance.

- **URL**: `/api/predict/expenditures`
- **Method**: `POST`
- **Headers**: `Content-Type: application/json`

#### Example Request Body
```json
{
  "transactions": [
    {
      "work_id": "WS/MP18225/2024-2025/144260",
      "mp_name": "PUSHPENDRA SAROJ",
      "constituency": "Kaushambi",
      "ida": "District Magistrate Kaushambi",
      "vendor": "VIVEK ENTERPRISES",
      "expenditure_amount": 44356.0,
      "expenditure_date": "2026-06-15"
    },
    {
      "work_id": "WS/MP18239/2025-2026/214753",
      "mp_name": "ZIA UR REHMAN",
      "constituency": "Sambhal",
      "ida": "District Magistrate Sambhal",
      "vendor": "R G SUPLLIER",
      "expenditure_amount": 36159.0,
      "expenditure_date": "2026-07-02"
    }
  ]
}
```

#### Example Success Response (`200 OK`)
```json
{
  "summary": {
    "LOW_RISK": 2
  },
  "results": [
    {
      "work_id": "WS/MP18225/2024-2025/144260",
      "mp_name": "PUSHPENDRA SAROJ",
      "vendor": "VIVEK ENTERPRISES",
      "expenditure_amount": 44356.0,
      "risk_score": 20.3,
      "risk_level": "LOW_RISK",
      "is_anomaly": false
    },
    {
      "work_id": "WS/MP18239/2025-2026/214753",
      "mp_name": "ZIA UR REHMAN",
      "vendor": "R G SUPLLIER",
      "expenditure_amount": 36159.0,
      "risk_score": 11.7,
      "risk_level": "LOW_RISK",
      "is_anomaly": false
    }
  ]
}
```

---

## 5. Engineered Features & Scoring Logic

The underlying feature engineering logic (`ExpenditureModelModule.py`) creates 6 behavioral features designed to identify red flags in expenditure disbursements:

| Feature Name | Type | Description | Behavioral Risk Target |
| :--- | :---: | :--- | :--- |
| `expenditure_amount` | Float | Raw rupee amount of the transaction. | Outlier transactions of abnormally high value. |
| `threshold_proximity_pct` | Float | Proximity to approval limits (`₹50,000`, `₹5,00,000`, `₹50,00,000`) calculated via exponential decay: $$100 \times e^{-\frac{\text{gap}}{\text{threshold} \times 0.05}}$$ | **Threshold Splitting / Smurfing**: Catching invoices priced just below financial sanction limits (e.g. ₹49,800 to bypass ₹50,000 approval). |
| `vendor_payout_velocity` | Integer | Count of payouts made to the same vendor by the same MP within a rolling 90-day window. | **Rapid Payouts / Vendor Favoritism**: High transaction frequency to a single entity. |
| `cumulative_vendor_spend_vs_threshold_pct` | Float | Proximity percentage of cumulative 90-day vendor spend against financial approval thresholds. | **Cumulative Threshold Evasion**: Multiple smaller disbursements to one vendor that collectively breach sanction tiers. |
| `amount_to_mp_budget_pct` | Float | Percentage of total MP allocated budget spent in this single payment. | **Budget Depletion Risk**: Over-allocation to single works. |
| `ida_monthly_txns` | Integer | Total transaction count handled by the Implementing District Authority (IDA) in that month. | **Administrative Overload**: Extreme spikes in district monthly processing volume. |

### Risk Level Mapping
Raw decision function outputs from `IsolationForest` are inverted and scaled into a standardized `risk_score` from `0.0` to `100.0`:

$$\text{Risk Score} = 100 \times \left(1 - \text{Clip}\left(\frac{\text{raw\_score} - \text{min}}{\text{max} - \text{min}}, 0, 1\right)\right)$$

| Risk Level | Score Range | Description & Action |
| :--- | :---: | :--- |
| `CRITICAL_ANOMALY` | **≥ 75.0** | High probability of irregularity or GFR threshold evasion. Immediate audit required. |
| `MEDIUM_RISK` | **40.0 – 74.9** | Elevated risk indicators (e.g., high velocity or budget impact). Secondary review recommended. |
| `LOW_RISK` | **< 40.0** | Standard transaction parameters within historical norms. |

---

## 6. Error Handling & HTTP Status Codes

| HTTP Code | Exception Cause | Example Response Detail |
| :---: | :--- | :--- |
| `400 Bad Request` | Unparseable `expenditure_date` string format. | `{"detail": "expenditure_date could not be parsed."}` |
| `400 Bad Request` | Unknown MP Name or unmapped allocation data. | `{"detail": "Unknown MP or missing allocation data: 'JOHN DOE'"}` |
| `400 Bad Request` | Empty payload submitted to batch endpoint. | `{"detail": "No transactions provided."}` |
| `422 Unprocessable Entity` | Row dropped during feature engineering due to invalid date/data. | `{"detail": "Could not compute features for this transaction..."}` |
| `500 Internal Error` | Internal model prediction runtime failure. | `{"detail": "Scoring failed: [error traceback]"}` |

---

## 7. How to Run & Test

### 7.1 Start the Server

Run from the repository root:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Interactive OpenAPI documentation will be available at:
- **Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)

### 7.2 Example `curl` Commands

#### Test Health Endpoint:
```bash
curl -X GET http://localhost:8000/health
```

#### Test Single Transaction Endpoint:
```bash
curl -X POST http://localhost:8000/api/predict/expenditure \
  -H "Content-Type: application/json" \
  -d '{
    "work_id": "WS/MP18239/2025-2026/214753",
    "mp_name": "ZIA UR REHMAN",
    "constituency": "Sambhal",
    "ida": "District Magistrate Sambhal",
    "vendor": "R G SUPLLIER",
    "expenditure_amount": 49800.0,
    "expenditure_date": "2026-07-02"
  }'
```

#### Test Batch Transaction Endpoint:
```bash
curl -X POST http://localhost:8000/api/predict/expenditures \
  -H "Content-Type: application/json" \
  -d '{
    "transactions": [
      {
        "work_id": "WS/MP18225/2024-2025/144260",
        "mp_name": "PUSHPENDRA SAROJ",
        "constituency": "Kaushambi",
        "ida": "District Magistrate Kaushambi",
        "vendor": "VIVEK ENTERPRISES",
        "expenditure_amount": 44356.0,
        "expenditure_date": "2026-06-15"
      }
    ]
  }'
```

### 7.3 Python Client Example

```python
import requests

url = "http://localhost:8000/api/predict/expenditure"
payload = {
    "work_id": "WS/MP18239/2025-2026/214753",
    "mp_name": "ZIA UR REHMAN",
    "constituency": "Sambhal",
    "ida": "District Magistrate Sambhal",
    "vendor": "R G SUPLLIER",
    "expenditure_amount": 49800.0,
    "expenditure_date": "2026-07-02"
}

response = requests.post(url, json=payload)
data = response.json()

print(f"Risk Score: {data['risk_score']} ({data['risk_level']})")
print("Top Contributing Features:")
for feat in data.get("top_contributing_features", []):
    print(f" - {feat['feature']}: {feat['value']} (Risk Impact: {feat['contribution_to_risk']})")
```
