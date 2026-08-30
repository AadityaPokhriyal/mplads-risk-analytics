"""
Fast CSV-based feature engineering service for MPLADS expenditure anomaly engine.

Uses pre-grouped in-memory index dictionaries built from historical CSV datasets
on server boot (`lifespan`). Enables millisecond feature engineering for new
incoming backend transactions with zero external database dependencies.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional


def _threshold_proximity(amount: float, thresholds: list, decay_rate: float = 0.05) -> float:
    """
    Calculates threshold proximity percentage for given amount and thresholds.
    """
    candidates = [t for t in thresholds if amount <= t]
    if not candidates:
        return 0.0
    nearest = min(candidates)
    gap_fraction = (nearest - amount) / nearest
    return round(100 * float(np.exp(-gap_fraction / decay_rate)), 2)


def build_csv_indexes(
    history_df: pd.DataFrame, alloc_df: pd.DataFrame
) -> Tuple[Dict[str, float], Dict[Tuple[str, str], pd.DataFrame], Dict[Tuple[str, str], int]]:
    """
    Builds high-performance in-memory index dictionaries from historical CSV DataFrames
    during server boot (`lifespan`). Takes ~50ms once on startup.
    """
    # 1. MP budget lookup index
    alloc_clean = alloc_df.iloc[:-1].copy() if len(alloc_df) > 1 else alloc_df.copy()
    mp_budget_lookup = dict(
        zip(
            alloc_clean["MP Name"],
            alloc_clean["Allocated Amount in rupees"].astype(str).str.replace(",", "").astype(float),
        )
    )

    # 2. History DataFrame pre-processing
    hist = history_df.iloc[:-1].copy() if len(history_df) > 1 else history_df.copy()
    hist["Expenditure Date"] = hist["Expenditure Date"].astype(str).str.strip()
    hist["_parsed_date"] = pd.to_datetime(hist["Expenditure Date"], format="%d-%b-%Y", errors="coerce")
    hist["expenditure_amount"] = hist["Fund Disbursed Amount ( ₹ )"].astype(str).str.replace(",", "").astype(float)
    hist["mp_name"] = hist["MP Name"]
    hist["vendor_name"] = hist["Vendor Name"]
    hist["ida"] = hist["IDA"]
    hist["year_month_str"] = hist["_parsed_date"].dt.strftime("%Y-%m")

    # Fast indexed dictionaries
    vendor_history_index = dict(tuple(hist.groupby(["mp_name", "vendor_name"])))
    ida_monthly_index = hist.groupby(["ida", "year_month_str"])["ida"].count().to_dict()

    return mp_budget_lookup, vendor_history_index, ida_monthly_index


def engineer_features_fast(
    new_rows_df: pd.DataFrame,
    mp_budget_lookup: Dict[str, float],
    vendor_history_index: Dict[Tuple[str, str], pd.DataFrame],
    ida_monthly_index: Dict[Tuple[str, str], int],
    approval_thresholds: Optional[List[int]] = None,
) -> Tuple[pd.DataFrame, List[str]]:
    """
    Computes feature engineering for ONLY new incoming backend row(s) in milliseconds
    using the pre-built CSV index dictionaries.
    """
    if approval_thresholds is None:
        approval_thresholds = [50000, 500000, 5000000]

    df = new_rows_df.copy()

    # Standardize column names if raw API names are passed
    col_mapping = {
        "Work ID": "work_id",
        "MP Name": "mp_name",
        "Constituency": "constituency",
        "IDA": "ida",
        "Vendor Name": "vendor_name",
        "Fund Disbursed Amount ( ₹ )": "expenditure_amount",
        "Expenditure Date": "expenditure_date",
    }
    for old_col, new_col in col_mapping.items():
        if old_col in df.columns and new_col not in df.columns:
            df[new_col] = df[old_col]

    df["expenditure_amount"] = df["expenditure_amount"].astype(str).str.replace(",", "").astype(float)
    df["expenditure_date"] = pd.to_datetime(df["expenditure_date"], errors="coerce")

    # 1. Direct mathematical feature: threshold_proximity_pct
    df["threshold_proximity_pct"] = df["expenditure_amount"].apply(
        lambda amt: _threshold_proximity(amt, approval_thresholds)
    )

    # 2. MP budget allocation lookup from CSV index
    df["mp_total_allocation"] = df["mp_name"].map(mp_budget_lookup)
    df["amount_to_mp_budget_pct"] = (
        df["expenditure_amount"] / df["mp_total_allocation"] * 100
    )

    # 3. Vendor Velocity & Cumulative 30d/90d spend lookup from CSV index
    df["vendor_payout_velocity"] = 0
    df["vendor_cumulative_30d"] = 0.0

    for idx, row in df.iterrows():
        mp = row["mp_name"]
        vendor = row["vendor_name"]
        curr_date = row["expenditure_date"]

        window_start = curr_date - pd.Timedelta(days=30)

        # Lookup past expenditures for (mp, vendor) from pre-grouped CSV index
        group_df = vendor_history_index.get((mp, vendor))
        if group_df is not None and len(group_df) > 0:
            hist_mask = (group_df["_parsed_date"] > window_start) & (group_df["_parsed_date"] <= curr_date)
            hist_sub = group_df[hist_mask]
            hist_count = len(hist_sub)
            hist_sum = hist_sub["expenditure_amount"].sum()
        else:
            hist_count = 0
            hist_sum = 0.0

        # Include current row (plus earlier rows in the same new batch)
        batch_mask = (
            (df["mp_name"] == mp) &
            (df["vendor_name"] == vendor) &
            (df["expenditure_date"] > window_start) &
            (df["expenditure_date"] <= curr_date) &
            (df.index <= idx)
        )
        batch_sub = df[batch_mask]
        batch_count = len(batch_sub)
        batch_sum = batch_sub["expenditure_amount"].sum()

        df.loc[idx, "vendor_payout_velocity"] = hist_count + batch_count
        df.loc[idx, "vendor_cumulative_30d"] = hist_sum + batch_sum

    df["cumulative_vendor_spend_vs_threshold_pct"] = df["vendor_cumulative_30d"].apply(
        lambda amt: _threshold_proximity(amt, approval_thresholds)
    )

    # 4. IDA Monthly Transactions lookup from CSV index
    df["year_month_str"] = df["expenditure_date"].dt.strftime("%Y-%m")

    df["ida_monthly_txns"] = 1
    for idx, row in df.iterrows():
        ida = row["ida"]
        ym = row["year_month_str"]
        hist_cnt = ida_monthly_index.get((ida, ym), 0)

        # Count in current batch up to current index
        batch_cnt = len(df[(df["ida"] == ida) & (df["year_month_str"] == ym) & (df.index <= idx)])
        df.loc[idx, "ida_monthly_txns"] = max(1, hist_cnt + batch_cnt)

    feature_cols = [
        "expenditure_amount",
        "threshold_proximity_pct",
        "vendor_payout_velocity",
        "cumulative_vendor_spend_vs_threshold_pct",
        "amount_to_mp_budget_pct",
        "ida_monthly_txns",
    ]

    return df, feature_cols
