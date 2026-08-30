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

    # --- Historical expenditures ---
    # Last row in this CSV is a totals/summary row, not a real transaction —
    # drop it, or it would be treated as one giant fake vendor payment and
    # badly distort every rolling-window feature.
    history = pd.read_csv(config["HISTORY_CSV_PATH"])
    history = history.iloc[:-1].copy()

    # IMPORTANT: keep "Expenditure Date" as the SAME raw string format the
    # CSV already uses ("%d-%b-%Y", per engineer_features' hardcoded parse
    # format). Do NOT convert to datetime here — engineer_features is the
    # single place that parses dates, and re-stringifying an already-parsed
    # Timestamp produces a different format that its format='%d-%b-%Y' would
    # fail to re-parse, silently turning every row into NaT.
    history["Expenditure Date"] = history["Expenditure Date"].astype(str).str.strip()

    n_before = len(history)
    parsed_check = pd.to_datetime(history["Expenditure Date"], format="%d-%b-%Y", errors="coerce")
    n_bad = parsed_check.isna().sum()
    if n_bad:
        print(f"WARNING: {n_bad} of {n_before} historical row(s) have a date that "
              f"doesn't match format '%d-%b-%Y'. These rows will still be passed "
              f"through, but engineer_features will treat their date as invalid.")

    _state["history"] = history

    # --- MP allocation lookup ---
    # Same totals-row issue applies here.
    alloc_df = pd.read_csv(config["ALLOCATION_CSV_PATH"])
    alloc_df = alloc_df.iloc[:-1].copy()
    _state["mp_budget_lookup"] = dict(
        zip(
            alloc_df["MP Name"],
            alloc_df["Allocated Amount in rupees"].astype(str).str.replace(",", "").astype(float),
        )
    )

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
        # Kept as a string (not float) so it concatenates cleanly with the
        # historical CSV's comma-formatted string column — engineer_features
        # calls .str.replace(',', '') on this column, which requires every
        # value to be a string, not a mix of strings and floats.
        "Fund Disbursed Amount ( ₹ )": str(txn.expenditure_amount),
        "Expenditure Date": date_str,
    }


def _score_context(new_rows_df: pd.DataFrame) -> pd.DataFrame:
    """
    Merges new transaction(s) with recent historical transactions so
    rolling-window features have context, then runs engineer_features ONCE
    on the combined raw data and returns only the new rows.
    """
    history = _state["history"]
    mp_budget_lookup = _state["mp_budget_lookup"]
    config = _state["config"]

    new_rows_df = new_rows_df.copy()
    new_rows_df["_is_new"] = True

    hist = history.copy()
    hist["_is_new"] = False

    # Lookback filtering needs real datetime comparison, done on a temporary
    # column only — the actual "Expenditure Date" column stays as the raw
    # '%d-%b-%Y' string all the way into engineer_features.
    hist["_parsed_date_tmp"] = pd.to_datetime(hist["Expenditure Date"], format="%d-%b-%Y", errors="coerce")
    new_parsed = pd.to_datetime(new_rows_df["Expenditure Date"], format="%d-%b-%Y", errors="coerce")
    min_needed_date = new_parsed.min() - pd.Timedelta(days=config["LOOKBACK_DAYS"])
    hist = hist[hist["_parsed_date_tmp"] >= min_needed_date].drop(columns=["_parsed_date_tmp"])

    combined = pd.concat([hist, new_rows_df], ignore_index=True)
    combined_features, feature_cols = engineer_features(
        combined, mp_budget_lookup, approval_thresholds=config["APPROVAL_THRESHOLDS"]
    )

    return combined_features[combined_features["_is_new"] == True].copy()


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