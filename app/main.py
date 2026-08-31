"""
FastAPI service for the MPLADS Multi-Model Risk Analytics Platform:
- Pillar 1: Expenditure Anomaly Engine (Isolation Forest + SHAP)
- Pillar 2: Project Execution Delay & Stalling Engine (Multi-Stage Latency + Governance Checks)

Endpoints:
    POST /api/predict/expenditure   - score ONE incoming transaction (with SHAP explanation)
    POST /api/predict/expenditures  - score MANY transactions at once (fast, no SHAP by default)
    POST /api/predict/work-delay    - score ONE work execution & stalling risk (Pillar 2)
    POST /api/predict/works-delay   - score MANY work executions & stalling risk in batch (Pillar 2)
    GET  /health                    - system and model health status

Run with (from the project root):
    python -m app.main
  or:
    uvicorn app.main:app --reload
"""

import os
from contextlib import asynccontextmanager

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# Model 1 (Expenditure)
from app.schemas.expenditure_schema import (
    ExpenditureInput,
    ExpenditureBatchInput,
    PredictionOutput,
    BatchPredictionOutput,
    BatchPredictionItem,
)
from app.services.feature_engineering import build_csv_indexes, engineer_features_fast
from ExpenditureModelModule import ExpenditureAnomalyModel

# Model 2 (Execution Delay)
from app.schemas.execution_schema import (
    WorkExecutionInput,
    WorkExecutionBatchInput,
    WorkExecutionPredictionOutput,
    WorkExecutionBatchOutput,
)
from app.services.execution_feature_engineering import (
    build_execution_indexes,
    engineer_execution_features_fast,
)
from ExecutionModelModule import ExecutionDelayModel

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _load_config() -> dict:
    required = ["MODEL_PATH", "HISTORY_CSV_PATH", "ALLOCATION_CSV_PATH"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise RuntimeError(f"Missing required environment variable(s): {', '.join(missing)}")

    thresholds_raw = os.getenv("APPROVAL_THRESHOLDS", "50000,500000,5000000")
    try:
        approval_thresholds = [int(x.strip()) for x in thresholds_raw.split(",") if x.strip()]
    except ValueError as e:
        raise RuntimeError(f"APPROVAL_THRESHOLDS must be comma-separated integers, got '{thresholds_raw}'") from e

    try:
        lookback_days = int(os.getenv("LOOKBACK_DAYS", "365"))
    except ValueError as e:
        raise RuntimeError(f"LOOKBACK_DAYS must be an integer, got '{os.getenv('LOOKBACK_DAYS')}'") from e

    try:
        port = int(os.getenv("PORT", "3000"))
    except ValueError as e:
        raise RuntimeError(f"PORT must be an integer, got '{os.getenv('PORT')}'") from e

    return {
        "MODEL_PATH": os.getenv("MODEL_PATH"),
        "EXECUTION_MODEL_PATH": os.getenv("EXECUTION_MODEL_PATH", "models/execution_delay_model.joblib"),
        "HISTORY_CSV_PATH": os.getenv("HISTORY_CSV_PATH"),
        "ALLOCATION_CSV_PATH": os.getenv("ALLOCATION_CSV_PATH"),
        "APPROVAL_THRESHOLDS": approval_thresholds,
        "LOOKBACK_DAYS": lookback_days,
        "PORT": port,
        "WORKS_RECOMMENDED_CSV_PATH": os.getenv("WORKS_RECOMMENDED_CSV_PATH", "New Datasets/Works Recommended.csv"),
        "WORKS_SANCTIONED_CSV_PATH": os.getenv("WORKS_SANCTIONED_CSV_PATH", "New Datasets/Works Sanctioned.csv"),
        "WORKS_COMPLETED_CSV_PATH": os.getenv("WORKS_COMPLETED_CSV_PATH", "New Datasets/Works Completed.csv"),
    }


# ---------------------------------------------------------------------------
# App state & Lifespan
# ---------------------------------------------------------------------------

_state = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = _load_config()
    _state["config"] = config

    # 1. Load Model 1 (Expenditure Anomaly Engine)
    _state["engine"] = ExpenditureAnomalyModel.load(config["MODEL_PATH"])

    history_df = pd.read_csv(config["HISTORY_CSV_PATH"])
    alloc_df = pd.read_csv(config["ALLOCATION_CSV_PATH"])

    mp_budget_lookup, vendor_history_index, ida_monthly_index = build_csv_indexes(history_df, alloc_df)
    _state["mp_budget_lookup"] = mp_budget_lookup
    _state["vendor_history_index"] = vendor_history_index
    _state["ida_monthly_index"] = ida_monthly_index

    # 2. Load Model 2 (Execution Delay & Stalling Engine)
    rec_path = config["WORKS_RECOMMENDED_CSV_PATH"]
    sanc_path = config["WORKS_SANCTIONED_CSV_PATH"]
    comp_path = config["WORKS_COMPLETED_CSV_PATH"]

    rec_df = pd.read_csv(rec_path) if os.path.exists(rec_path) else pd.DataFrame()
    sanc_df = pd.read_csv(sanc_path) if os.path.exists(sanc_path) else pd.DataFrame()
    comp_df = pd.read_csv(comp_path) if os.path.exists(comp_path) else pd.DataFrame()

    execution_indexes = build_execution_indexes(rec_df, sanc_df, comp_df)
    _state["execution_indexes"] = execution_indexes

    model_joblib_path = config.get("EXECUTION_MODEL_PATH", "models/execution_delay_model.joblib")
    if os.path.exists(model_joblib_path):
        execution_model = ExecutionDelayModel.load(model_joblib_path)
    else:
        execution_model = ExecutionDelayModel()
        if len(sanc_df) > 0:
            hist_sample = sanc_df.copy().head(5000)
            hist_sample["work_id"] = hist_sample.get("Work", "UNKNOWN")
            hist_sample["recommended_amount"] = hist_sample.get("Sanction Amount ( ₹ )", 0)
            hist_sample["sanction_amount"] = hist_sample.get("Sanction Amount ( ₹ )", 0)
            hist_sample["amount_disbursed"] = hist_sample.get("Sanction Amount ( ₹ )", 0)
            hist_sample["recommended_date"] = hist_sample.get("Recommended date", "")
            hist_sample["sanction_date"] = hist_sample.get("Sanction Date", "")
            hist_sample["work_status"] = hist_sample.get("Work Status", "Ongoing")
            hist_sample["has_photo_evidence"] = False
            hist_sample["state"] = hist_sample.get("State", "")
            hist_sample["mp_name"] = hist_sample.get("Hon'ble Members of Parliament", "")
            hist_sample["ida"] = hist_sample.get("IDA", "")
            hist_sample["constituency"] = hist_sample.get("Constituency", "")

            try:
                feats, _ = engineer_execution_features_fast(hist_sample, execution_indexes)
                execution_model.fit(feats)
            except Exception:
                pass

    _state["execution_engine"] = execution_model

    yield
    _state.clear()


app = FastAPI(title="MPLADS Risk Analytics Engine", lifespan=lifespan)

# ---------------------------------------------------------------------------
# CORS Middleware
# ---------------------------------------------------------------------------

cors_origins_raw = os.getenv("CORS_ORIGINS", "*")
origins = [o.strip() for o in cors_origins_raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins if origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Model 1 Helpers
# ---------------------------------------------------------------------------

def _to_raw_date_string(date_str: str) -> str:
    parsed = pd.to_datetime(date_str, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.strftime("%d-%b-%Y")


def _raw_input_to_row(txn: ExpenditureInput) -> dict:
    date_str = _to_raw_date_string(txn.expenditure_date)
    return {
        "Work ID": txn.work_id,
        "MP Name": txn.mp_name,
        "Constituency": txn.constituency,
        "IDA": txn.ida,
        "Vendor Name": txn.vendor,
        "Fund Disbursed Amount ( ₹ )": str(txn.expenditure_amount),
        "Expenditure Date": date_str,
    }


def _score_context(new_rows_df: pd.DataFrame) -> pd.DataFrame:
    config = _state["config"]
    scored, _ = engineer_features_fast(
        new_rows_df=new_rows_df,
        mp_budget_lookup=_state["mp_budget_lookup"],
        vendor_history_index=_state["vendor_history_index"],
        ida_monthly_index=_state["ida_monthly_index"],
        approval_thresholds=config["APPROVAL_THRESHOLDS"],
    )
    return scored


# ---------------------------------------------------------------------------
# Model 1 Endpoints (Expenditure Anomaly Engine)
# ---------------------------------------------------------------------------

@app.post("/api/predict/expenditure", response_model=PredictionOutput, response_model_by_alias=True)
def predict_single_expenditure(txn: ExpenditureInput):
    """
    Score ONE incoming expenditure transaction (with SHAP explanation).
    """
    engine: ExpenditureAnomalyModel = _state.get("engine")
    if not engine:
        raise HTTPException(status_code=503, detail="Expenditure engine is not loaded.")

    try:
        row_dict = _raw_input_to_row(txn)
        if row_dict["Expenditure Date"] is None:
            raise HTTPException(status_code=400, detail="expenditure_date could not be parsed.")

        new_df = pd.DataFrame([row_dict])
        scored = _score_context(new_df)

        if len(scored) == 0:
            raise HTTPException(
                status_code=422,
                detail="Could not compute features for this transaction — check date format or required fields.",
            )

        row = scored.iloc[0]
        result = engine.predict_row(row, explain=True, top_n_reasons=3)
        return result

    except HTTPException:
        raise
    except KeyError as e:
        raise HTTPException(status_code=400, detail=f"Unknown MP or missing allocation data: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scoring failed: {e}")


@app.post("/api/predict/expenditures", response_model=BatchPredictionOutput)
def predict_batch_expenditures(payload: ExpenditureBatchInput):
    """
    Score MANY expenditure transactions at once (high throughput).
    """
    engine: ExpenditureAnomalyModel = _state.get("engine")
    if not engine:
        raise HTTPException(status_code=503, detail="Expenditure engine is not loaded.")

    if not payload.transactions:
        raise HTTPException(status_code=400, detail="No transactions provided.")

    try:
        rows = [_raw_input_to_row(txn) for txn in payload.transactions]
        new_df = pd.DataFrame(rows)
        new_df["_submission_order"] = range(len(new_df))

        bad_rows = new_df.index[new_df["Expenditure Date"].isna()].tolist()
        if bad_rows:
            raise HTTPException(status_code=400, detail=f"expenditure_date could not be parsed for row(s): {bad_rows}")

        scored = _score_context(new_df)
        if len(scored) == 0:
            raise HTTPException(status_code=422, detail="No rows survived feature engineering.")

        scored_with_scores = engine.predict_batch(scored)
        scored_with_scores = scored_with_scores.sort_values("_submission_order")

        results = [
            BatchPredictionItem(
                work_id=r["Work ID"],
                mp_name=r["MP Name"],
                vendor=r["Vendor Name"],
                expenditure_amount=float(r["expenditure_amount"]),
                risk_score=float(r["risk_score"]),
                risk_level=r["risk_level"],
                is_anomaly=bool(r["is_anomaly"]),
            )
            for _, r in scored_with_scores.iterrows()
        ]

        summary = scored_with_scores["risk_level"].value_counts().to_dict()
        return BatchPredictionOutput(summary=summary, results=results)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Batch scoring failed: {e}")


# ---------------------------------------------------------------------------
# Model 2 Endpoints (Project Execution Delay & Stalling Engine)
# ---------------------------------------------------------------------------

@app.post("/api/predict/work-delay", response_model=WorkExecutionPredictionOutput)
def predict_single_work_delay(work: WorkExecutionInput):
    """
    Score ONE project for execution latency, stalling risk (>365d),
    mandatory photographic evidence compliance, and cost escalation.
    """
    execution_engine: ExecutionDelayModel = _state.get("execution_engine")
    execution_indexes = _state.get("execution_indexes", {})

    if not execution_engine:
        raise HTTPException(status_code=503, detail="Execution Delay Engine is not loaded.")

    try:
        work_dict = work.model_dump()
        work_df = pd.DataFrame([work_dict])

        scored_df, _ = engineer_execution_features_fast(work_df, execution_indexes)
        if len(scored_df) == 0:
            raise HTTPException(status_code=422, detail="Failed to engineer execution features.")

        row = scored_df.iloc[0]
        result = execution_engine.predict_row(row)
        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Execution risk scoring failed: {e}")


@app.post("/api/predict/works-delay", response_model=WorkExecutionBatchOutput)
def predict_batch_works_delay(payload: WorkExecutionBatchInput):
    """
    Score MULTIPLE projects for execution latency, stalling risk,
    and compliance in batch mode.
    """
    execution_engine: ExecutionDelayModel = _state.get("execution_engine")
    execution_indexes = _state.get("execution_indexes", {})

    if not execution_engine:
        raise HTTPException(status_code=503, detail="Execution Delay Engine is not loaded.")

    if not payload.works:
        raise HTTPException(status_code=400, detail="No projects provided.")

    try:
        rows = [w.model_dump() for w in payload.works]
        works_df = pd.DataFrame(rows)

        scored_df, _ = engineer_execution_features_fast(works_df, execution_indexes)
        if len(scored_df) == 0:
            raise HTTPException(status_code=422, detail="Failed to engineer features for batch.")

        batch_result = execution_engine.predict_batch(scored_df)
        return batch_result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Batch execution scoring failed: {e}")


# ---------------------------------------------------------------------------
# Health & Status Endpoint
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {
        "status": "ok",
        "expenditure_model_loaded": "engine" in _state,
        "execution_model_loaded": "execution_engine" in _state,
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")
    uvicorn.run("app.main:app", host=host, port=port, reload=True)