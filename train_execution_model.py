"""
Training script for Model 2: Project Execution Delay & Stalling Engine.
Reads historical works CSVs, engineers features, trains the Isolation Forest baseline,
and saves the model artifact to `models/execution_delay_model.joblib`.

Run with:
    python train_execution_model.py
"""

import os
import pandas as pd
import numpy as np
from app.services.execution_feature_engineering import (
    build_execution_indexes,
    engineer_execution_features_fast,
)
from ExecutionModelModule import ExecutionDelayModel


def train_and_save_model():
    print("=" * 60)
    print("Training Model 2: Project Execution Delay Engine")
    print("=" * 60)

    # 1. Paths
    rec_path = os.getenv("WORKS_RECOMMENDED_CSV_PATH", "New Datasets/Works Recommended.csv")
    sanc_path = os.getenv("WORKS_SANCTIONED_CSV_PATH", "New Datasets/Works Sanctioned.csv")
    comp_path = os.getenv("WORKS_COMPLETED_CSV_PATH", "New Datasets/Works Completed.csv")
    model_output_dir = "models"
    model_output_path = os.path.join(model_output_dir, "execution_delay_model.joblib")

    os.makedirs(model_output_dir, exist_ok=True)

    # 2. Load historical CSVs
    print(f"Loading datasets:\n  - {rec_path}\n  - {sanc_path}\n  - {comp_path}")
    rec_df = pd.read_csv(rec_path) if os.path.exists(rec_path) else pd.DataFrame()
    sanc_df = pd.read_csv(sanc_path) if os.path.exists(sanc_path) else pd.DataFrame()
    comp_df = pd.read_csv(comp_path) if os.path.exists(comp_path) else pd.DataFrame()

    print(f"Loaded {len(rec_df)} recommended, {len(sanc_df)} sanctioned, {len(comp_df)} completed works.")

    # 3. Build execution indexes
    print("Building in-memory statistical baselines & MP indexes...")
    execution_indexes = build_execution_indexes(rec_df, sanc_df, comp_df)

    # 4. Prepare training samples from sanctioned & completed works
    training_rows = []

    # Map sanctioned works
    if len(sanc_df) > 0:
        for _, r in sanc_df.iterrows():
            training_rows.append({
                "work_id": str(r.get("Work", "UNKNOWN")),
                "work_description": str(r.get("Work description", "")),
                "work_category": str(r.get("Work category", "Normal/Others")),
                "state": str(r.get("State", "")),
                "mp_name": str(r.get("Hon'ble Members of Parliament", "")),
                "constituency": str(r.get("Constituency", "")),
                "ida": str(r.get("IDA", "")),
                "recommended_amount": r.get("Sanction Amount ( ₹ )", 0),
                "recommended_date": r.get("Recommended date", ""),
                "sanction_amount": r.get("Sanction Amount ( ₹ )", 0),
                "sanction_date": r.get("Sanction Date", ""),
                "work_status": r.get("Work Status", "Ongoing"),
                "amount_disbursed": r.get("Sanction Amount ( ₹ )", 0),
                "completion_date": None,
                "has_photo_evidence": False,
            })

    # Map completed works
    if len(comp_df) > 0:
        for _, r in comp_df.iterrows():
            training_rows.append({
                "work_id": str(r.get("Work", "UNKNOWN")),
                "work_description": str(r.get("Work Description", "")),
                "work_category": str(r.get("Work Category", "Normal/Others")),
                "state": str(r.get("State", "")),
                "mp_name": str(r.get("Hon'ble Members of Parliament", "")),
                "constituency": str(r.get("Constituency", "")),
                "ida": str(r.get("IDA", "")),
                "recommended_amount": r.get("Amount Disbursed ( ₹ )", 0),
                "recommended_date": r.get("Completion Date", ""),
                "sanction_amount": r.get("Amount Disbursed ( ₹ )", 0),
                "sanction_date": r.get("Completion Date", ""),
                "work_status": "Work Completed",
                "amount_disbursed": r.get("Amount Disbursed ( ₹ )", 0),
                "completion_date": r.get("Completion Date", ""),
                "has_photo_evidence": True if str(r.get("Image", "")).strip().lower() not in ["n/a", "na", "nan", ""] else False,
            })

    train_df = pd.DataFrame(training_rows)
    print(f"Constructed training dataset with {len(train_df)} works.")

    # 5. Feature Engineering
    print("Running feature engineering pipeline...")
    features_df, feature_cols = engineer_execution_features_fast(train_df, execution_indexes)
    print(f"Engineered feature columns: {feature_cols}")

    # 6. Fit Isolation Forest & Scorer
    print("Fitting Isolation Forest model...")
    model = ExecutionDelayModel(contamination=0.05, random_state=42)
    model.fit(features_df)

    # 7. Save Model Artifact
    print(f"Saving trained model to {model_output_path}...")
    model.save(model_output_path)
    print("[SUCCESS] Model 2 successfully trained and saved!")


if __name__ == "__main__":
    train_and_save_model()
