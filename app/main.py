"""
FastAPI service for the MPLADS Expenditure Anomaly Engine.

Endpoints:
    POST /api/predict/expenditure   - score ONE incoming transaction (with SHAP explanation)
    POST /api/predict/expenditures  - score MANY transactions at once (fast, no SHAP by default)

Run with (from the project root, one level ABOVE this file's folder):
    uvicorn app.main:app --reload
"""

import os
from contextlib import asynccontextmanager

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.schemas.expenditure_schema import *
from app.services.feature_engineering import build_csv_indexes, engineer_features_fast
from ExpenditureModelModule import ExpenditureAnomalyModel, engineer_features

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

    return {
        "MODEL_PATH": os.getenv("MODEL_PATH"),
        "HISTORY_CSV_PATH": os.getenv("HISTORY_CSV_PATH"),
        "ALLOCATION_CSV_PATH": os.getenv("ALLOCATION_CSV_PATH"),
        "APPROVAL_THRESHOLDS": approval_thresholds,
        "LOOKBACK_DAYS": lookback_days,
    }


# ---------------------------------------------------------------------------
# App state
# ---------------------------------------------------------------------------

_state = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = _load_config()
    _state["config"] = config

    _state["engine"] = ExpenditureAnomalyModel.load(config["MODEL_PATH"])

    # Load historical CSVs and build high-performance in-memory indexes (~50ms on boot)
    history_df = pd.read_csv(config["HISTORY_CSV_PATH"])
    alloc_df = pd.read_csv(config["ALLOCATION_CSV_PATH"])

    mp_budget_lookup, vendor_history_index, ida_monthly_index = build_csv_indexes(history_df, alloc_df)

    _state["mp_budget_lookup"] = mp_budget_lookup
    _state["vendor_history_index"] = vendor_history_index
    _state["ida_monthly_index"] = ida_monthly_index

    yield
    _state.clear()


app = FastAPI(title="MPLADS Expenditure Anomaly Engine", lifespan=lifespan)

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
# Helpers
# ---------------------------------------------------------------------------

def _to_raw_date_string(date_str: str) -> str:
    """
    Normalizes whatever date format the API caller sends into the exact
    '%d-%b-%Y' string format the historical CSV and engineer_features()
    both expect (e.g. '02-Jul-2026'). Accepts common formats (ISO, etc.)
    and re-emits them consistently so history and new rows always align
    on the same string convention before engineer_features ever runs.
    """
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
    """
    Computes feature engineering for new incoming transaction(s) using fast
    in-memory CSV index lookups, executing in milliseconds with zero external DBs.
    """
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
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/api/predict/expenditure", response_model=PredictionOutput, response_model_by_alias=True)
def predict_single(txn: ExpenditureInput):
    """
    Score ONE incoming transaction. Includes a SHAP-based explanation of
    which features drove the score.
    """
    engine: ExpenditureAnomalyModel = _state["engine"]

    try:
        row_dict = _raw_input_to_row(txn)
        if row_dict["Expenditure Date"] is None:
            raise HTTPException(status_code=400, detail="expenditure_date could not be parsed.")

        new_df = pd.DataFrame([row_dict])
        scored = _score_context(new_df)

        if len(scored) == 0:
            raise HTTPException(
                status_code=422,
                detail="Could not compute features for this transaction — the row was "
                       "dropped during feature engineering. Check server logs for a "
                       "specific WARNING about invalid dates or missing fields.",
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
def predict_batch(payload: ExpenditureBatchInput):
    """
    Score MANY transactions at once. Uses vectorized predict_batch() —
    no per-row SHAP — so this stays fast even for large payloads.
    """
    engine: ExpenditureAnomalyModel = _state["engine"]

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


@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": "engine" in _state}