"""
Feature engineering service for Model 2: Project Execution Delay & Stalling Engine.

Builds in-memory index statistics from historical CSVs (Works Recommended, Works Sanctioned, Works Completed)
and calculates multi-stage latencies, stalling indicators, photo compliance penalties, and escalation ratios.
"""

import pandas as pd
import numpy as np
import datetime
from typing import Dict, List, Tuple, Optional, Any


def _parse_dates_robust(series: pd.Series) -> pd.Series:
    """
    Robustly parses dates across standard formats ('08-Jul-2024', '2024-07-08', '05-Sep-24', etc.)
    """
    clean_series = series.astype(str).str.strip().replace(["nan", "None", "N/A", "NA", ""], pd.NA)
    return pd.to_datetime(clean_series, errors="coerce")


def build_execution_indexes(
    recommended_df: pd.DataFrame,
    sanctioned_df: pd.DataFrame,
    completed_df: pd.DataFrame,
) -> Dict[str, Any]:
    """
    Builds in-memory statistical lookups from historical CSVs on application boot.
    Returns:
        - mp_completion_index: Dict[mp_name, completion_rate (0.0 - 1.0)]
        - state_latency_index: Dict[state, avg_approval_latency_days]
        - ida_latency_index: Dict[ida, avg_approval_latency_days]
    """
    # 1. MP completion rate index
    sanc_mp_counts = {}
    if "Hon'ble Members of Parliament" in sanctioned_df.columns:
        sanc_mp_counts = sanctioned_df["Hon'ble Members of Parliament"].astype(str).str.strip().value_counts().to_dict()
    elif "mp_name" in sanctioned_df.columns:
        sanc_mp_counts = sanctioned_df["mp_name"].astype(str).str.strip().value_counts().to_dict()

    comp_mp_counts = {}
    if "Hon'ble Members of Parliament" in completed_df.columns:
        comp_mp_counts = completed_df["Hon'ble Members of Parliament"].astype(str).str.strip().value_counts().to_dict()
    elif "mp_name" in completed_df.columns:
        comp_mp_counts = completed_df["mp_name"].astype(str).str.strip().value_counts().to_dict()

    mp_completion_index = {}
    for mp, total_sanc in sanc_mp_counts.items():
        if total_sanc > 0:
            total_comp = comp_mp_counts.get(mp, 0)
            mp_completion_index[mp] = round(min(1.0, total_comp / total_sanc), 4)

    # 2. State & IDA approval latency baseline from Sanctioned / Recommended
    state_latency_index = {}
    ida_latency_index = {}

    if "Recommended date" in sanctioned_df.columns and "Sanction Date" in sanctioned_df.columns:
        sanc_clean = sanctioned_df.copy()
        sanc_clean["_rec_date"] = _parse_dates_robust(sanc_clean["Recommended date"])
        sanc_clean["_sanc_date"] = _parse_dates_robust(sanc_clean["Sanction Date"])
        sanc_clean["_latency"] = (sanc_clean["_sanc_date"] - sanc_clean["_rec_date"]).dt.days
        valid_latencies = sanc_clean[sanc_clean["_latency"].between(0, 1000)]

        if "State" in valid_latencies.columns:
            state_latency_index = valid_latencies.groupby("State")["_latency"].mean().round(1).to_dict()
        if "IDA" in valid_latencies.columns:
            ida_latency_index = valid_latencies.groupby("IDA")["_latency"].mean().round(1).to_dict()

    return {
        "mp_completion_index": mp_completion_index,
        "state_latency_index": state_latency_index,
        "ida_latency_index": ida_latency_index,
        "national_avg_latency": 30.0,
    }


def _get_status_risk_factor(status: Optional[str]) -> float:
    if not status or pd.isna(status):
        return 0.5
    s = str(status).strip().lower()
    if "physical inspection" in s or "inspection" in s:
        return 0.8
    if "vendor identification" in s or "tender" in s or "vendor" in s:
        return 0.7
    if "partially completed" in s or "ongoing" in s or "in progress" in s:
        return 0.5
    if "sanction" in s:
        return 0.4
    if "completed" in s:
        return 0.0
    return 0.3


def engineer_execution_features_fast(
    new_rows_df: pd.DataFrame,
    execution_indexes: Dict[str, Any],
    reference_date: Optional[datetime.date] = None,
) -> Tuple[pd.DataFrame, List[str]]:
    """
    Transforms raw live API inputs into an engineered feature vector for Model 2 scoring.
    """
    df = new_rows_df.copy()
    if reference_date is None:
        reference_date = datetime.date.today()
    ref_ts = pd.to_datetime(reference_date)

    # Standardize column names if needed
    col_mapping = {
        "work_id": "work_id",
        "work_description": "work_description",
        "work_category": "work_category",
        "state": "state",
        "mp_name": "mp_name",
        "constituency": "constituency",
        "ida": "ida",
        "recommended_amount": "recommended_amount",
        "recommended_date": "recommended_date",
        "sanction_amount": "sanction_amount",
        "sanction_date": "sanction_date",
        "work_status": "work_status",
        "amount_disbursed": "amount_disbursed",
        "completion_date": "completion_date",
        "has_photo_evidence": "has_photo_evidence",
    }
    for old_col, new_col in col_mapping.items():
        if old_col in df.columns and new_col not in df.columns:
            df[new_col] = df[old_col]

    # Numeric conversion
    df["recommended_amount"] = pd.to_numeric(df["recommended_amount"], errors="coerce").fillna(0.0)
    df["sanction_amount"] = pd.to_numeric(df["sanction_amount"], errors="coerce").fillna(0.0)
    df["amount_disbursed"] = pd.to_numeric(df["amount_disbursed"], errors="coerce").fillna(0.0)
    df["has_photo_evidence"] = df["has_photo_evidence"].astype(bool)

    # Date parsing
    df["_rec_date"] = _parse_dates_robust(df["recommended_date"])
    df["_sanc_date"] = _parse_dates_robust(df["sanction_date"])
    df["_comp_date"] = _parse_dates_robust(df["completion_date"])

    # 1. Approval Latency (rec to sanc)
    df["approval_latency_days"] = (df["_sanc_date"] - df["_rec_date"]).dt.days
    df["approval_latency_days"] = df["approval_latency_days"].apply(lambda d: max(0, int(d)) if pd.notna(d) else 0)

    # 2. Project Age & Execution Duration
    is_comp = df["_comp_date"].notna()
    df["is_completed"] = is_comp

    comp_durations = (df["_comp_date"] - df["_sanc_date"]).dt.days
    ongoing_ages = (ref_ts - df["_sanc_date"]).dt.days

    df["project_age_days"] = np.where(is_comp, comp_durations, ongoing_ages)
    df["project_age_days"] = df["project_age_days"].apply(lambda d: max(0, int(d)) if pd.notna(d) else 0)

    df["execution_duration_days"] = np.where(is_comp, comp_durations, np.nan)

    # 3. Total Lead Time (recommended to completion / current)
    comp_lead = (df["_comp_date"] - df["_rec_date"]).dt.days
    ongoing_lead = (ref_ts - df["_rec_date"]).dt.days
    df["total_lead_time_days"] = np.where(is_comp, comp_lead, ongoing_lead)
    df["total_lead_time_days"] = df["total_lead_time_days"].apply(lambda d: max(0, int(d)) if pd.notna(d) else 0)

    # 4. Stalling detection
    df["is_stalled"] = (~is_comp) & (df["project_age_days"] > 365)
    df["is_stalled_365"] = df["is_stalled"].astype(int)

    # 5. Missing Photo Penalty
    # If not has_photo_evidence -> missing_photo_penalty is 40.0, else 0.0
    df["missing_photo_penalty"] = np.where(~df["has_photo_evidence"], 40.0, 0.0)

    # 6. Status Risk Factor
    df["status_risk_factor"] = df["work_status"].apply(_get_status_risk_factor)

    # 7. Cost Escalation Ratio & Disbursement Pct
    df["cost_escalation_ratio"] = np.where(
        df["sanction_amount"] > 0,
        df["amount_disbursed"] / df["sanction_amount"],
        1.0
    )
    df["disbursement_pct_num"] = np.clip(df["cost_escalation_ratio"] * 100, 0, 500)
    df["disbursement_pct_str"] = df["disbursement_pct_num"].apply(lambda p: f"{p:.2f}%")

    # 8. MP Completion Ratio & State Latency Lookups
    mp_index = execution_indexes.get("mp_completion_index", {})
    state_index = execution_indexes.get("state_latency_index", {})
    national_avg = execution_indexes.get("national_avg_latency", 30.0)

    df["mp_completion_ratio"] = df["mp_name"].map(lambda m: mp_index.get(str(m).strip(), 0.70))
    df["state_baseline_latency"] = df["state"].map(lambda s: state_index.get(str(s).strip(), national_avg))

    # Latency deviation from state baseline
    df["approval_latency_deviation"] = df["approval_latency_days"] - df["state_baseline_latency"]

    feature_cols = [
        "approval_latency_days",
        "project_age_days",
        "total_lead_time_days",
        "is_stalled_365",
        "missing_photo_penalty",
        "status_risk_factor",
        "cost_escalation_ratio",
        "mp_completion_ratio",
        "approval_latency_deviation",
    ]

    return df, feature_cols
