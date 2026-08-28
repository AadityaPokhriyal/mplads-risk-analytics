"""
MPLADS Risk Analytics - Model 2: Project Execution Delay & Cost Overrun Engine
Phase 0: Training Pipeline

This script:
1. Ingests completed works, recommended works, and MP summary datasets.
2. Computes category-level statistics (mean/std of final settled amount).
3. Computes MP-level completion rates.
4. Engineers the 5-dimensional feature matrix:
   - cost_escalation_ratio
   - execution_days
   - missing_photo_penalty
   - mp_completion_rate
   - category_cost_deviation (Z-Score)
5. Fits and exports StandardScaler and IsolationForest model artifacts.
6. Runs validation tests against reference benchmarks.
"""

import os
import json
import logging
from pathlib import Path
import numpy as np
import pandas as pd
import joblib
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("train_models")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "Datasets"
MODELS_DIR = BASE_DIR / "models"


def load_datasets():
    """Load raw MPLADS CSV datasets from Datasets directory."""
    logger.info("Loading datasets from %s...", DATA_DIR)
    
    comp_path = DATA_DIR / "mplads_completed_works_2026-08-22.csv"
    rec_path = DATA_DIR / "mplads_recommended_works_2026-08-22.csv"
    mp_path = DATA_DIR / "mplads_mp_summary_2026-08-22.csv"
    
    if not comp_path.exists():
        raise FileNotFoundError(f"Completed works file not found: {comp_path}")
    if not rec_path.exists():
        raise FileNotFoundError(f"Recommended works file not found: {rec_path}")
    if not mp_path.exists():
        raise FileNotFoundError(f"MP summary file not found: {mp_path}")
        
    df_comp = pd.read_csv(comp_path, encoding="utf-8")
    df_rec = pd.read_csv(rec_path, encoding="utf-8")
    df_mp = pd.read_csv(mp_path, encoding="utf-8")
    
    logger.info(
        "Loaded: %d completed works, %d recommended works, %d MP summaries",
        len(df_comp), len(df_rec), len(df_mp)
    )
    return df_comp, df_rec, df_mp


def compute_and_save_category_stats(df_comp: pd.DataFrame, output_path: Path) -> dict:
    """Compute per-category mean and std of Final Amount (₹) for Z-score calculation."""
    logger.info("Computing category-level cost statistics...")
    
    cat_group = df_comp.groupby("Category")["Final Amount (₹)"]
    means = cat_group.mean().to_dict()
    stds = cat_group.std().to_dict()
    
    global_mean = float(df_comp["Final Amount (₹)"].mean())
    global_std = float(df_comp["Final Amount (₹)"].std())
    
    stats = {}
    for cat in means:
        cat_mean = float(means[cat])
        cat_std = float(stds.get(cat, 1.0))
        if np.isnan(cat_std) or cat_std <= 0:
            cat_std = global_std if global_std > 0 else 100000.0
            
        stats[str(cat)] = {
            "mean": round(cat_mean, 2),
            "std": round(cat_std, 2)
        }
        
    stats["_GLOBAL"] = {
        "mean": round(global_mean, 2),
        "std": round(global_std, 2)
    }
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)
        
    logger.info("Category stats saved to %s (categories: %d)", output_path, len(stats) - 1)
    return stats


def compute_and_save_mp_completion_rates(df_mp: pd.DataFrame, output_path: Path) -> dict:
    """Compute per-MP completion rates mapping (clean MP name -> rate %)."""
    logger.info("Computing MP-level completion rates...")
    
    rates = {}
    for _, row in df_mp.iterrows():
        mp_name = str(row["MP Name"]).strip().upper()
        rate = float(row.get("Completion Rate %", 50.0))
        if np.isnan(rate):
            rate = 50.0
        rates[mp_name] = round(rate, 2)
        
    global_rate = float(df_mp["Completion Rate %"].dropna().mean())
    rates["_GLOBAL"] = round(global_rate, 2)
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(rates, f, indent=2, ensure_ascii=False)
        
    logger.info("MP completion rates saved to %s (MPs: %d)", output_path, len(rates) - 1)
    return rates


def build_training_features(df_comp: pd.DataFrame, df_rec: pd.DataFrame, cat_stats: dict, mp_rates: dict) -> pd.DataFrame:
    """Engineer feature vectors for training the Isolation Forest model."""
    logger.info("Engineering feature vectors...")
    
    df_comp_work = df_comp.copy()
    df_rec_work = df_rec.copy()
    
    # Standardize keys for matching
    df_comp_work["clean_desc"] = df_comp_work["Work Description"].astype(str).str.strip().str.upper()
    df_rec_work["clean_desc"] = df_rec_work["Work Description"].astype(str).str.strip().str.upper()
    df_comp_work["clean_mp"] = df_comp_work["MP Name"].astype(str).str.strip().str.upper()
    df_rec_work["clean_mp"] = df_rec_work["MP Name"].astype(str).str.strip().str.upper()
    
    # Deduplicate recommended works on [clean_mp, clean_desc] for merging
    rec_lookup = df_rec_work.groupby(["clean_mp", "clean_desc"]).first().reset_index()
    
    # Left merge completed works with recommended details
    merged = pd.merge(
        df_comp_work,
        rec_lookup[["clean_mp", "clean_desc", "Recommended Amount (₹)", "Recommendation Date"]],
        on=["clean_mp", "clean_desc"],
        how="left"
    )
    
    # 1. Feature: cost_escalation_ratio = Final Amount / Recommended Amount
    # If recommended amount is missing or <= 0, default to final amount (ratio = 1.0)
    rec_amt = merged["Recommended Amount (₹)"].fillna(merged["Final Amount (₹)"])
    rec_amt = rec_amt.replace(0, np.nan).fillna(merged["Final Amount (₹)"].replace(0, 1.0))
    cost_ratio = (merged["Final Amount (₹)"] / rec_amt).clip(0.1, 10.0).fillna(1.0)
    
    # 2. Feature: execution_days = (Completed Date - Recommendation Date)
    comp_date = pd.to_datetime(merged["Completed Date"], errors="coerce")
    rec_date = pd.to_datetime(merged["Recommendation Date"], errors="coerce")
    days = (comp_date - rec_date).dt.days
    # For missing or negative dates, impute realistic default median of ~180 days
    days = days.fillna(180).clip(1, 2000)
    
    # 3. Feature: missing_photo_penalty = 1.0 if not Has Images, else 0.0
    missing_photo = (~merged["Has Images"].fillna(False).astype(bool)).astype(float)
    
    # 4. Feature: mp_completion_rate
    global_rate = mp_rates.get("_GLOBAL", 51.63)
    mp_rate_feat = merged["clean_mp"].map(lambda mp: mp_rates.get(mp, global_rate)).fillna(global_rate)
    
    # 5. Feature: category_cost_deviation (Z-Score)
    global_stat = cat_stats.get("_GLOBAL", {"mean": 547000.0, "std": 1024000.0})
    def compute_z(row):
        cat = str(row["Category"])
        st = cat_stats.get(cat, global_stat)
        mean_val = st["mean"]
        std_val = st["std"] if st["std"] > 0 else 1.0
        return (float(row["Final Amount (₹)"]) - mean_val) / std_val
        
    z_scores = merged.apply(compute_z, axis=1).clip(-3.0, 10.0).fillna(0.0)
    
    features_df = pd.DataFrame({
        "cost_escalation_ratio": cost_ratio,
        "execution_days": days,
        "missing_photo_penalty": missing_photo,
        "mp_completion_rate": mp_rate_feat,
        "category_cost_deviation": z_scores
    })
    
    logger.info("Engineered %d feature vectors across 5 features.", len(features_df))
    logger.info("Feature Summary:\n%s", features_df.describe().to_string())
    return features_df


def train_and_save_models(features_df: pd.DataFrame, scaler_path: Path, model_path: Path):
    """Fit StandardScaler and IsolationForest on features and save artifacts."""
    logger.info("Fitting StandardScaler...")
    scaler = StandardScaler()
    scaled_matrix = scaler.fit_transform(features_df)
    
    joblib.dump(scaler, scaler_path)
    logger.info("Saved StandardScaler to %s", scaler_path)
    
    logger.info("Training IsolationForest (n_estimators=150, contamination=0.10)...")
    model = IsolationForest(
        n_estimators=150,
        contamination=0.10,
        random_state=42,
        n_jobs=-1
    )
    model.fit(scaled_matrix)
    
    joblib.dump(model, model_path)
    logger.info("Saved IsolationForest model to %s", model_path)
    
    # Test scoring distribution
    decision_scores = model.decision_function(scaled_matrix)
    logger.info(
        "Decision function summary: min=%.4f, max=%.4f, mean=%.4f, std=%.4f",
        decision_scores.min(), decision_scores.max(), decision_scores.mean(), decision_scores.std()
    )
    return scaler, model


def run_benchmark_verification(scaler, model, cat_stats: dict, mp_rates: dict):
    """Run benchmark tests matching MODEL_2_EXECUTION_DELAY_IO_SPEC.md."""
    logger.info("=== Running Benchmark Verification ===")
    
    # Case 1: High Execution Risk (Zero Photo Proof + Cost Overrun + Delayed)
    case_1 = {
        "work_id": 134703,
        "category": "Normal/Others",
        "mp_name": "DAGGUMALLA PRASADA RAO",
        "recommended_amount": 350000.0,
        "final_amount": 499993.0,
        "recommendation_date": "2024-01-10T00:00:00.000Z",
        "completed_date": "2025-01-31T00:00:00.000Z",
        "has_images": False
    }
    
    # Case 2: Low Execution Risk (Completed on Time with Photos)
    case_2 = {
        "work_id": 134704,
        "category": "Normal/Others",
        "mp_name": "DAGGUMALLA PRASADA RAO",
        "recommended_amount": 500000.0,
        "final_amount": 495000.0,
        "recommendation_date": "2024-06-01T00:00:00.000Z",
        "completed_date": "2024-09-29T00:00:00.000Z",
        "has_images": True
    }
    
    def score_single(item):
        cost_ratio = float(item["final_amount"]) / max(float(item["recommended_amount"]), 1.0)
        c_date = pd.to_datetime(item["completed_date"])
        r_date = pd.to_datetime(item["recommendation_date"])
        days = max((c_date - r_date).days, 1)
        missing_photo = 1.0 if not item["has_images"] else 0.0
        
        mp_clean = str(item["mp_name"]).strip().upper()
        mp_rate = mp_rates.get(mp_clean, mp_rates.get("_GLOBAL", 51.63))
        
        cat_info = cat_stats.get(item["category"], cat_stats.get("_GLOBAL"))
        std_val = cat_info["std"] if cat_info["std"] > 0 else 1.0
        z_score = (item["final_amount"] - cat_info["mean"]) / std_val
        
        feat_vector = np.array([[
            np.clip(cost_ratio, 0.1, 10.0),
            np.clip(days, 1, 2000),
            missing_photo,
            mp_rate,
            np.clip(z_score, -3.0, 10.0)
        ]])
        
        feat_scaled = scaler.transform(feat_vector)
        raw_dec = float(model.decision_function(feat_scaled)[0])
        
        # Base ML score (decision function roughly [-0.25, 0.25] -> mapped to [90, 10])
        base_ml = np.clip((0.20 - raw_dec) / 0.40 * 60.0 + 10.0, 5.0, 95.0)
        
        # Rule penalties
        penalty = 0.0
        if not item["has_images"]:
            penalty += 35.0
        if cost_ratio > 1.25:
            penalty += min(25.0, (cost_ratio - 1.0) * 50.0)
        elif cost_ratio > 1.05:
            penalty += 10.0
        if days > 365:
            penalty += min(20.0, (days - 365) / 30.0 * 2.5)
            
        final_risk = float(np.clip(base_ml * 0.45 + penalty * 0.55, 0.0, 100.0))
        risk_level = "HIGH_EXECUTION_RISK" if final_risk >= 70.0 else ("MODERATE_RISK" if final_risk >= 31.0 else "COMPLIANT_LOW_RISK")
        return {
            "work_id": item["work_id"],
            "execution_risk_score": round(final_risk, 1),
            "risk_level": risk_level,
            "cost_escalation_ratio": round(cost_ratio, 4),
            "execution_days": days,
            "has_images": item["has_images"]
        }
        
    res_1 = score_single(case_1)
    res_2 = score_single(case_2)
    
    logger.info("Benchmark Case 1 (Expected High Risk): %s", res_1)
    logger.info("Benchmark Case 2 (Expected Low Risk): %s", res_2)
    
    assert res_1["execution_risk_score"] > res_2["execution_risk_score"], "Case 1 score should be higher than Case 2!"
    assert res_1["risk_level"] in ["HIGH_EXECUTION_RISK", "MODERATE_RISK"], "Case 1 should be flagged as elevated risk!"
    assert res_2["risk_level"] == "COMPLIANT_LOW_RISK", "Case 2 should be low risk!"
    logger.info("Benchmark verification PASSED successfully!")


def main():
    logger.info("Starting Phase 0 Model Training...")
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    
    # 1. Load data
    df_comp, df_rec, df_mp = load_datasets()
    
    # 2. Compute category statistics
    cat_stats_path = MODELS_DIR / "category_stats.json"
    cat_stats = compute_and_save_category_stats(df_comp, cat_stats_path)
    
    # 3. Compute MP completion rates
    mp_rates_path = MODELS_DIR / "mp_completion_rates.json"
    mp_rates = compute_and_save_mp_completion_rates(df_mp, mp_rates_path)
    
    # 4. Engineer features
    features_df = build_training_features(df_comp, df_rec, cat_stats, mp_rates)
    
    # 5. Train & save models
    scaler_path = MODELS_DIR / "scaler.joblib"
    model_path = MODELS_DIR / "execution_model.joblib"
    scaler, model = train_and_save_models(features_df, scaler_path, model_path)
    
    # 6. Verify against benchmark
    run_benchmark_verification(scaler, model, cat_stats, mp_rates)
    
    logger.info("=== Phase 0 Complete: All 4 artifacts successfully generated in models/ ===")


if __name__ == "__main__":
    main()
