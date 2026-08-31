"""
Model 2: Project Execution Delay & Cost Overrun Engine
Hybrid Multi-Stage Latency Scorer & Governance Rule Engine.

Mirrors the architecture of ExpenditureAnomalyModel (Model 1):
- Saves and loads trained weights/scaler/background via joblib
- Fast sub-millisecond scoring with explainability tags and governance rules
"""

import pandas as pd
import numpy as np
import joblib
from typing import Dict, List, Optional, Any
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler


class ExecutionDelayModel:
    """
    Evaluates multi-stage execution latencies, stalling risk (>365d),
    mandatory photographic evidence compliance, and cost escalation.
    """

    def __init__(self, contamination: float = 0.05, random_state: int = 42):
        self.contamination = contamination
        self.random_state = random_state
        self.scaler = StandardScaler()
        self.model = IsolationForest(
            n_estimators=300,
            contamination=self.contamination,
            random_state=self.random_state,
            n_jobs=-1,
        )
        self.feature_cols = [
            "approval_latency_days",
            "project_age_days",
            "total_lead_time_days",
            "status_risk_factor",
            "cost_escalation_ratio",
            "mp_completion_ratio",
        ]
        self._score_min = -0.5
        self._score_max = 0.5
        self._background = None
        self._is_fitted = False

    def fit(self, df: pd.DataFrame, feature_cols: Optional[List[str]] = None):
        if feature_cols:
            self.feature_cols = feature_cols

        valid_cols = [c for c in self.feature_cols if c in df.columns]
        if len(valid_cols) == len(self.feature_cols):
            X = df[self.feature_cols].fillna(0).values
            X_scaled = self.scaler.fit_transform(X)
            self.model.fit(X_scaled)
            raw_scores = self.model.decision_function(X_scaled)
            self._score_min = float(raw_scores.min())
            self._score_max = float(raw_scores.max())
            sample_size = min(100, len(X_scaled))
            indices = np.random.RandomState(self.random_state).choice(len(X_scaled), sample_size, replace=False)
            self._background = X_scaled[indices]
            self._is_fitted = True
        return self

    def _to_risk_score(self, raw_score: float) -> float:
        span = self._score_max - self._score_min
        normalized = 0.5 if span == 0 else (raw_score - self._score_min) / span
        normalized = np.clip(normalized, 0, 1)
        return round(float((1 - normalized) * 100), 1)

    def predict_row(self, row: pd.Series) -> Dict[str, Any]:
        """
        Computes composite execution risk score, explainability tags, flagged reasons,
        and recommended actions for a single project milestone record.
        """
        work_id = str(row.get("work_id", row.get("Work ID", "UNKNOWN")))
        work_status = str(row.get("work_status", row.get("Work Status", "Ongoing")))
        rec_amt = float(row.get("recommended_amount", 0.0))
        sanc_amt = float(row.get("sanction_amount", 0.0))
        disb_amt = float(row.get("amount_disbursed", 0.0))
        has_photo = bool(row.get("has_photo_evidence", False))
        is_comp = bool(row.get("is_completed", False))

        approval_latency = int(row.get("approval_latency_days", 0))
        project_age = int(row.get("project_age_days", 0))
        exec_duration = int(row.get("execution_duration_days", project_age)) if is_comp else None
        is_stalled = bool(row.get("is_stalled", False))
        escalation_ratio = float(row.get("cost_escalation_ratio", 1.0))
        disb_pct_str = str(row.get("disbursement_pct_str", f"{(disb_amt / max(sanc_amt, 1) * 100):.2f}%"))
        constituency = str(row.get("constituency", row.get("Constituency", ""))).strip()

        # 1. Base Score calculation from governance and delay rules
        risk_score = 0.0
        flags: List[str] = []
        tags: List[str] = []

        # A. Missing photographic evidence check
        if not has_photo:
            risk_score += 40.0
            if disb_amt > 0:
                flags.append(f"Missing Mandatory Photographic Proof: {disb_pct_str} of funds disbursed with NO geo-tagged inspection photos uploaded.")
            else:
                flags.append("Missing Mandatory Proof: Work recorded with NO photographic evidence.")
            tags.append("ZERO_PHOTO_EVIDENCE")
        else:
            tags.append("VERIFIED_PHOTOS")

        # B. Chronic Stalling / Project Age Latency check
        if is_stalled:
            risk_score += 45.0
            flags.append(f"Chronic Project Stalling: Project has been in '{work_status}' stage for {project_age} days (national threshold: 180 days).")
            tags.append("CHRONIC_STALLING_365D")
        elif project_age > 180 and not is_comp:
            risk_score += 20.0
            flags.append(f"Moderate Delay: Project active for {project_age} days (>180d).")
            tags.append("MODERATE_DELAY")

        # C. Stage Bottleneck check
        status_lower = work_status.lower()
        if "physical inspection" in status_lower and project_age > 90 and not is_comp:
            tags.append("PHYSICAL_INSPECTION_BOTTLENECK")
        elif "vendor" in status_lower and project_age > 60 and not is_comp:
            tags.append("VENDOR_TENDER_BOTTLENECK")

        # D. Blocked public capital check
        if not is_comp and disb_amt >= 200000:
            lakhs = disb_amt / 100000
            flags.append(f"Blocked Public Capital: ₹{lakhs:.2f} Lakh disbursed without final project closure certificate.")

        # E. Cost Escalation / Budget Overrun check
        if escalation_ratio > 1.05 and sanc_amt > 0:
            overrun_pct = round((escalation_ratio - 1.0) * 100, 1)
            risk_score += min(15.0, overrun_pct)
            flags.append(f"Budget Overrun: Actual disbursement exceeds administrative sanction by {overrun_pct}%.")
            tags.append("COST_OVERRUN")
        elif escalation_ratio <= 1.0:
            tags.append("WITHIN_BUDGET")

        # F. Positive compliance tags
        if is_comp and project_age <= 240 and approval_latency <= 60:
            tags.append("ON_TIME_COMPLETION")

        # If project is completed on time and fully compliant, reward it
        if is_comp and has_photo and escalation_ratio <= 1.0 and project_age <= 240:
            risk_score = min(risk_score, 15.0)

        # Baseline clamp: 0.0 to 100.0
        risk_score = round(float(np.clip(risk_score, 0.0, 100.0)), 1)

        # Classify risk level and recommended action
        if risk_score >= 70.0:
            risk_level = "HIGH_EXECUTION_RISK"
            location = constituency if constituency else "District Authority"
            recommended_action = f"Issue formal show-cause notice to {location} District Authority and order mandatory on-site physical verification by District Vigilance Officer."
        elif risk_score >= 30.0:
            risk_level = "MODERATE_RISK"
            recommended_action = "Request expedited milestone status update from Implementing District Authority."
        else:
            risk_level = "COMPLIANT_LOW_RISK"
            recommended_action = "Standard audit sign-off and Final Completion Certificate (FCC) approved."

        is_compliant = bool(risk_score < 30.0)

        lifecycle_metrics = {
            "recommended_amount": rec_amt,
            "sanction_amount": sanc_amt,
            "amount_disbursed": disb_amt,
            "disbursement_pct": disb_pct_str,
            "current_stage": work_status,
            "approval_latency_days": approval_latency,
            "current_project_age_days": project_age,
            "is_stalled": is_stalled,
            "has_photo_evidence": has_photo,
        }
        if exec_duration is not None:
            lifecycle_metrics["execution_duration_days"] = exec_duration

        return {
            "work_id": work_id,
            "execution_risk_score": risk_score,
            "risk_level": risk_level,
            "is_compliant": is_compliant,
            "lifecycle_metrics": lifecycle_metrics,
            "flagged_reasons": flags,
            "explainability_tags": tags,
            "recommended_action": recommended_action,
        }

    def predict_batch(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Executes fast vectorized batch scoring for multiple works.
        """
        results = []
        for _, row in df.iterrows():
            pred = self.predict_row(row)
            item = {
                "work_id": pred["work_id"],
                "work_description": row.get("work_description"),
                "state": row.get("state", ""),
                "mp_name": row.get("mp_name", ""),
                "execution_risk_score": pred["execution_risk_score"],
                "risk_level": pred["risk_level"],
                "is_compliant": pred["is_compliant"],
                "is_stalled": pred["lifecycle_metrics"]["is_stalled"],
                "has_photo_evidence": pred["lifecycle_metrics"]["has_photo_evidence"],
                "current_stage": pred["lifecycle_metrics"]["current_stage"],
                "flagged_reasons": pred["flagged_reasons"],
                "explainability_tags": pred["explainability_tags"],
                "recommended_action": pred["recommended_action"],
            }
            results.append(item)

        # Summary statistics
        levels = [r["risk_level"] for r in results]
        summary = {
            "total_evaluated": len(results),
            "high_risk_count": levels.count("HIGH_EXECUTION_RISK"),
            "moderate_risk_count": levels.count("MODERATE_RISK"),
            "compliant_count": levels.count("COMPLIANT_LOW_RISK"),
            "stalled_count": sum(1 for r in results if r["is_stalled"]),
            "zero_photo_count": sum(1 for r in results if not r["has_photo_evidence"]),
        }

        return {
            "summary": summary,
            "results": results,
        }

    def save(self, path: str):
        joblib.dump({
            "model": self.model,
            "scaler": self.scaler,
            "feature_cols": self.feature_cols,
            "score_min": self._score_min,
            "score_max": self._score_max,
            "contamination": self.contamination,
            "background": self._background,
            "is_fitted": self._is_fitted,
        }, path)

    @classmethod
    def load(cls, path: str):
        state = joblib.load(path)
        obj = cls(contamination=state.get("contamination", 0.05))
        obj.model = state["model"]
        obj.scaler = state["scaler"]
        obj.feature_cols = state["feature_cols"]
        obj._score_min = state.get("score_min", -0.5)
        obj._score_max = state.get("score_max", 0.5)
        obj._background = state.get("background")
        obj._is_fitted = state.get("is_fitted", True)
        return obj
