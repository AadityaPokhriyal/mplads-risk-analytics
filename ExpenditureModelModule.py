import pandas as pd
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
import joblib
import shap

def _threshold_proximity(amount: float, thresholds: list, decay_rate: float = 0.05) -> float:
    candidates = [t for t in thresholds if amount <= t]
    if not candidates:
        return 0.0
    nearest = min(candidates)
    gap_fraction = (nearest - amount) / nearest
    return round(100 * np.exp(-gap_fraction / decay_rate), 2)

def engineer_features(df: pd.DataFrame, mp_budget_lookup: dict, approval_thresholds: list = None) -> pd.DataFrame:
    if approval_thresholds is None:
        approval_thresholds = [50000, 500000, 5000000]

    df = df.copy()
    df["Expenditure Date"] = (
        df["Expenditure Date"].astype(str).str.strip().replace("", pd.NA)
    )
    df['Expenditure Date'] = pd.to_datetime(df['Expenditure Date'], format='%d-%b-%Y', errors='coerce')
    df = df.sort_values("Expenditure Date")

    df["expenditure_amount"] = df["Fund Disbursed Amount ( ₹ )"].astype(str).str.replace(',', '').astype(float)

    df["threshold_proximity_pct"] = df["expenditure_amount"].apply(
        lambda amt: _threshold_proximity(amt, approval_thresholds)
    )

    df["vendor_payout_velocity"] = 0
    df["vendor_cumulative_30d"] = 0.0
    for (mp, vendor), group in df.groupby(["MP Name", "Vendor Name"]):
        idx = group.index
        dates = group["Expenditure Date"].values
        amounts = group["expenditure_amount"].values
        counts, sums = [], []
        for i, d in enumerate(dates):
            window_start = d - np.timedelta64(90, "D")
            in_window = (dates > window_start) & (dates <= d)
            counts.append(np.sum(in_window))
            sums.append(amounts[in_window].sum())
        df.loc[idx, "vendor_payout_velocity"] = counts
        df.loc[idx, "vendor_cumulative_30d"] = sums

    df["cumulative_vendor_spend_vs_threshold_pct"] = df["vendor_cumulative_30d"].apply(
        lambda amt: _threshold_proximity(amt, approval_thresholds)
    )

    df["mp_total_allocation"] = df["MP Name"].map(mp_budget_lookup)
    df["amount_to_mp_budget_pct"] = (
        df["expenditure_amount"] / df["mp_total_allocation"] * 100
    )

    df["year_month"] = df["Expenditure Date"].dt.to_period("M")
    ida_monthly_counts = df.groupby(["IDA", "year_month"])["IDA"].transform("count")
    df["ida_monthly_txns"] = ida_monthly_counts.fillna(1).astype(int)

    feature_cols = [
        "expenditure_amount",
        "threshold_proximity_pct",
        "vendor_payout_velocity",
        "cumulative_vendor_spend_vs_threshold_pct",
        "amount_to_mp_budget_pct",
        "ida_monthly_txns",
    ]
    return df, feature_cols


def _safe_int(value, field_name: str) -> int:
    if pd.isna(value):
        raise ValueError(f"'{field_name}' is NaN and cannot be cast to int.")
    return int(value)


class ExpenditureAnomalyModel:
    def __init__(self, contamination: float = 0.03, random_state: int = 42):
        self.contamination = contamination
        self.random_state = random_state
        self.scaler = StandardScaler()
        self.model = IsolationForest(
            n_estimators=300, contamination=self.contamination,
            random_state=self.random_state, n_jobs=-1,
        )
        self.feature_cols = None
        self._score_min = None
        self._score_max = None
        self._background = None
        self.explainer = None

    def fit(self, df: pd.DataFrame, feature_cols: list):
        self.feature_cols = feature_cols
        X = df[feature_cols].values
        X_scaled = self.scaler.fit_transform(X)
        self.model.fit(X_scaled)
        raw_scores = self.model.decision_function(X_scaled)
        self._score_min = raw_scores.min()
        self._score_max = raw_scores.max()
        self._background = shap.sample(X_scaled, min(100, len(X_scaled)), random_state=self.random_state)
        self._build_explainer()
        return self

    def _build_explainer(self):
        self.explainer = shap.Explainer(
            self.model.decision_function, self._background,
            feature_names=self.feature_cols, algorithm="permutation",
        )

    def _to_risk_score(self, raw_score: float) -> float:
        span = self._score_max - self._score_min
        normalized = 0.5 if span == 0 else (raw_score - self._score_min) / span
        normalized = np.clip(normalized, 0, 1)
        return round(float((1 - normalized) * 100), 1)

    def explain_row(self, row: pd.Series, top_n: int = None) -> list:
        X = row[self.feature_cols].values.reshape(1, -1)
        X_scaled = self.scaler.transform(X)
        shap_values = self.explainer(X_scaled)
        contributions = [
            {"feature": feat, "value": row[feat], "contribution_to_risk": round(float(-shap_val), 4)}
            for feat, shap_val in zip(self.feature_cols, shap_values.values[0])
        ]
        contributions.sort(key=lambda c: abs(c["contribution_to_risk"]), reverse=True)
        return contributions[:top_n] if top_n else contributions

    def predict_row(self, row: pd.Series, explain: bool = True, top_n_reasons: int = 3) -> dict:
        X = row[self.feature_cols].values.reshape(1, -1)
        X_scaled = self.scaler.transform(X)
        raw_score = float(self.model.decision_function(X_scaled)[0])
        prediction_label = int(self.model.predict(X_scaled)[0])
        risk_score = self._to_risk_score(raw_score)
        is_anomaly = bool(prediction_label == -1)

        if risk_score >= 75:
            risk_level = "CRITICAL_ANOMALY"
        elif risk_score >= 40:
            risk_level = "MEDIUM_RISK"
        else:
            risk_level = "LOW_RISK"

        output = {
            "Work ID": row['Work ID'],
            "risk_score": risk_score,
            "risk_level": risk_level,
            "is_anomaly": is_anomaly,
            "metrics": {
                "amount": float(row["expenditure_amount"]),
                "threshold_proximity_pct": float(row["threshold_proximity_pct"]),
                "vendor_30d_frequency": _safe_int(row["vendor_payout_velocity"], "vendor_payout_velocity"),
                "cumulative_vendor_spend_vs_threshold_pct": float(row["cumulative_vendor_spend_vs_threshold_pct"]),
                "budget_impact_pct": round(float(row["amount_to_mp_budget_pct"]), 2),
                "ida_monthly_txns": _safe_int(row["ida_monthly_txns"], "ida_monthly_txns"),
            },
            "raw_anomaly_score": round(raw_score, 4),
        }
        if explain:
            output["top_contributing_features"] = self.explain_row(row, top_n=top_n_reasons)
        return output

    def predict_batch(self, df: pd.DataFrame) -> pd.DataFrame:
        X = df[self.feature_cols].values
        X_scaled = self.scaler.transform(X)
        raw_scores = self.model.decision_function(X_scaled)
        labels = self.model.predict(X_scaled)
        span = self._score_max - self._score_min
        normalized = np.full_like(raw_scores, 0.5) if span == 0 else np.clip((raw_scores - self._score_min) / span, 0, 1)
        risk_scores = np.round((1 - normalized) * 100, 1)
        out = df.copy()
        out["raw_anomaly_score"] = raw_scores
        out["risk_score"] = risk_scores
        out["is_anomaly"] = labels == -1
        out["risk_level"] = np.select(
            [risk_scores >= 75, risk_scores >= 40],
            ["CRITICAL_ANOMALY", "MEDIUM_RISK"], default="LOW_RISK",
        )
        return out

    def save(self, path: str):
        joblib.dump({
            "model": self.model, "scaler": self.scaler, "feature_cols": self.feature_cols,
            "score_min": self._score_min, "score_max": self._score_max,
            "contamination": self.contamination, "background": self._background,
        }, path)

    @classmethod
    def load(cls, path: str):
        state = joblib.load(path)
        obj = cls(contamination=state["contamination"])
        obj.model = state["model"]
        obj.scaler = state["scaler"]
        obj.feature_cols = state["feature_cols"]
        obj._score_min = state["score_min"]
        obj._score_max = state["score_max"]
        obj._background = state["background"]
        obj._build_explainer()
        return obj