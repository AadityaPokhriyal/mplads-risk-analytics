# Model 1: Expenditure Anomaly Engine — Input & Output Specification

> **Model Type:** **Isolation Forest (Unsupervised Anomaly Detection)**  
> **Target Scope:** Detecting Smurfing (Invoice Splitting), Payout Surges, and Unusual Expenditure Sizes  
> **File Location:** `Ml research and docs/MODEL_1_EXPENDITURE_ANOMALY_IO_SPEC.md`

---

## 1. Overview
This specification details the exact input features and output structure for **Model 1 (Pillar 1)**. It covers both **batch training data** and **live real-time REST API payloads**.

---

## 2. Model Inputs

### A. Raw Source Fields (from [`mplads_expenditures_2026-08-22.csv`](file:///c:/Users/DIVYA/OneDrive/Desktop/3_Projects_and_Development/Projects/SIH/mplads-risk-analytics/Datasets/mplads_expenditures_2026-08-22.csv))

| Field Name | Type | Description | Sample Value |
| :--- | :---: | :--- | :--- |
| `MP Name` | String | Recommending Member of Parliament | `"ATUL GARG"` |
| `Constituency` | String | Target constituency | `"GHAZIABAD"` |
| `IDA` | String | Implementing District Authority | `"GHAZIABAD(DISTRICT MAGISTRAE...)"` |
| `Vendor` | String | Contractor receiving funds | `"DARSH BUILDCON"` |
| `Expenditure Amount (₹)`| Float | Transaction payout value | `199999.0` |
| `Expenditure Date` | String | ISO timestamp of payment | `"2026-07-02T00:00:00.000Z"` |
| `Payment Status` | String | Clearance status | `"Payment Success"` |

---

### B. Engineered Feature Vector (Fed directly into Isolation Forest)

| Feature Name | Type | Calculation / Logic | Purpose | Range |
| :--- | :---: | :--- | :--- | :---: |
| `expenditure_amount` | Float | Raw transaction value in ₹ | Captures payout magnitude | `₹1` to `₹3.25 Cr` |
| `is_threshold_smurf` | Int (0/1)| `1` if amount is between ₹1.95L–₹1.999L or ₹4.90L–₹4.999L | Catches sanction-limit evasion | `0` or `1` |
| `vendor_payout_velocity`| Int | Number of payouts to same vendor by same MP in last 30 days | Detects rapid fund dumping | `1` to `50+` |
| `amount_to_mp_budget_pct`| Float | `(Transaction Amount / Total MP Allocation) * 100` | Checks budget share impact | `0.001%` to `20%` |
| `ida_monthly_txns` | Int | Total transactions processed by this IDA in current month | Detects unusual district spikes| `1` to `500+` |

---

### C. Live Real-Time API Input (JSON Request to `POST /api/predict/transaction`)

```json
{
  "mp_name": "ATUL GARG",
  "constituency": "GHAZIABAD",
  "ida": "GHAZIABAD(DISTRICT MAGISTRAE GHAZIABAD_IDA)",
  "vendor": "DARSH BUILDCON",
  "expenditure_amount": 199999.0,
  "expenditure_date": "2026-07-02T00:00:00.000Z",
  "work_description": "Construction of CC road and pathway"
}
```

---

## 3. Model Outputs

### A. Raw Model Output
* **`raw_anomaly_score`:** Continuous float from `IsolationForest.decision_function()` (e.g. `-0.245`).
* **`prediction_label`:** `-1` (Anomaly / Outlier) or `1` (Normal / Inlier).

---

### B. Processed JSON Response (Sent to Frontend)

#### 🔴 Case 1: High-Risk Anomaly (Red Flag Detected)
```json
{
  "transaction_id": "TXN_106263",
  "risk_score": 88.5,
  "risk_level": "CRITICAL_ANOMALY",
  "is_anomaly": true,
  "metrics": {
    "amount": 199999.0,
    "threshold_proximity": "₹1 below ₹2.00 Lakh fast-track limit",
    "vendor_30d_frequency": 6,
    "budget_impact_pct": 0.13
  },
  "flagged_reasons": [
    "Threshold Skimming: Transaction amount is ₹1,99,999 (structured to bypass ₹2 Lakh administrative approval threshold)",
    "High Velocity: 6th payout issued to 'DARSH BUILDCON' within 30 days",
    "Repetitive Structure: Identical amount paid multiple times in same district"
  ],
  "explainability_tags": ["SMURFING_SUSPECTED", "HIGH_VENDOR_FREQUENCY"],
  "recommended_action": "Withhold payment release and audit whether work was split into smaller tenders."
}
```

#### 🟢 Case 2: Low-Risk Normal Transaction
```json
{
  "transaction_id": "TXN_106264",
  "risk_score": 14.2,
  "risk_level": "LOW_RISK",
  "is_anomaly": false,
  "metrics": {
    "amount": 75000.0,
    "threshold_proximity": "Normal",
    "vendor_30d_frequency": 1,
    "budget_impact_pct": 0.05
  },
  "flagged_reasons": [],
  "explainability_tags": ["COMPLIANT"],
  "recommended_action": "Standard processing. No anomalies detected."
}
```

---

## 4. Frontend UI Component Mapping

| Output Field | UI Component | Visual Representation |
| :--- | :--- | :--- |
| `risk_score` (88.5) | **Speedometer Gauge / Progress Bar** | Red needle pointing to 88.5/100 |
| `risk_level` (`CRITICAL_ANOMALY`) | **Status Badge** | Red Pill Badge (`🔴 CRITICAL`) |
| `flagged_reasons` | **Alert Modal / Accordion** | Expandable warning list with exclamation icons |
| `recommended_action` | **Auditor Action Box** | Text card with a button *"Generate Audit Notice"* |
