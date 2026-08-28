"""Scoring engine: Feature engineering, Isolation Forest inference, and rule-weighted risk classification."""

import logging
from typing import List, Dict, Any, Tuple
import numpy as np
import pandas as pd

from app.schemas.work import (
    WorkInput,
    WorkMetrics,
    WorkRiskResponse,
    BatchRiskSummary,
    BatchRiskResponse
)
from app.models.loader import get_registry

logger = logging.getLogger("fastapi_app.services.scoring")


def _calculate_features_for_work(
    work: WorkInput,
    cat_stats: Dict[str, Any],
    mp_rates: Dict[str, float]
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Calculates quantitative features and metadata metrics for a single work."""
    # 1. Cost escalation
    rec_amt = float(work.recommended_amount)
    final_amt = float(work.final_amount)
    rec_safe = rec_amt if rec_amt > 0 else (final_amt if final_amt > 0 else 1.0)
    cost_ratio = final_amt / rec_safe
    cost_ratio_clipped = float(np.clip(cost_ratio, 0.1, 10.0))
    cost_delta = final_amt - rec_amt
    cost_pct_val = ((cost_ratio - 1.0) * 100) if rec_safe > 0 else 0.0
    cost_escalation_pct = f"{'+' if cost_pct_val >= 0 else ''}{cost_pct_val:.2f}%"

    # 2. Execution duration
    c_date = pd.to_datetime(work.completed_date, errors="coerce")
    r_date = pd.to_datetime(work.recommendation_date, errors="coerce")
    if pd.notnull(c_date) and pd.notnull(r_date):
        duration_days = max((c_date - r_date).days, 1)
    else:
        duration_days = 180  # Default median baseline
    duration_clipped = int(np.clip(duration_days, 1, 2000))

    # 3. Missing photo penalty
    has_photo = bool(work.has_images)
    missing_photo_penalty = 1.0 if not has_photo else 0.0

    # 4. MP completion rate
    mp_name_clean = str(work.mp_name or "").strip().upper()
    global_rate = mp_rates.get("_GLOBAL", 51.63)
    mp_completion_rate = float(mp_rates.get(mp_name_clean, global_rate))

    # 5. Category cost deviation (Z-Score)
    cat_name = str(work.category or "Normal/Others")
    cat_info = cat_stats.get(cat_name, cat_stats.get("_GLOBAL", {"mean": 547000.0, "std": 1024000.0}))
    std_val = float(cat_info["std"]) if float(cat_info["std"]) > 0 else 1.0
    mean_val = float(cat_info["mean"])
    z_score = (final_amt - mean_val) / std_val
    z_score_clipped = float(np.clip(z_score, -3.0, 10.0))

    feat_vector = np.array([
        cost_ratio_clipped,
        duration_clipped,
        missing_photo_penalty,
        mp_completion_rate,
        z_score_clipped
    ], dtype=np.float64)

    metrics_dict = {
        "recommended_cost": rec_amt,
        "final_settled_cost": final_amt,
        "cost_escalation_pct": cost_escalation_pct,
        "cost_escalation_ratio": round(cost_ratio, 4),
        "execution_duration_days": duration_days,
        "has_photo_evidence": has_photo,
        "mp_completion_rate_pct": round(mp_completion_rate, 2),
        "category_z_score": round(z_score, 2),
        "cost_delta": cost_delta
    }

    return feat_vector, metrics_dict


def _compute_risk_score_and_reasons(
    raw_decision: float,
    metrics: Dict[str, Any]
) -> Tuple[float, str, bool, List[str], List[str], str]:
    """Blends ML anomaly output with governance compliance rules."""
    has_photo = metrics["has_photo_evidence"]
    cost_ratio = metrics["cost_escalation_ratio"]
    duration = metrics["execution_duration_days"]
    z_score = metrics["category_z_score"]
    cost_delta = metrics["cost_delta"]
    cost_pct = metrics["cost_escalation_pct"]

    # Base ML score from Isolation Forest (decision function roughly in [-0.25, 0.20])
    # Mapping: -0.20 (outlier) -> 80+, +0.15 (inlier) -> ~10
    base_ml_score = np.clip((0.20 - raw_decision) / 0.40 * 60.0 + 10.0, 5.0, 95.0)

    # Rule-based modifiers
    rule_penalty = 0.0
    flagged_reasons: List[str] = []
    explainability_tags: List[str] = []

    # Check 1: Photographic evidence
    if not has_photo:
        rule_penalty += 35.0
        flagged_reasons.append(
            "Missing Mandatory Proof: Project signed off as completed with NO photographic evidence (Has Images = False)"
        )
        explainability_tags.append("ZERO_PHOTO_EVIDENCE")
    else:
        explainability_tags.append("VERIFIED_PHOTOS")

    # Check 2: Cost overrun
    if cost_ratio > 1.25:
        overrun_add = min(25.0, (cost_ratio - 1.0) * 50.0)
        rule_penalty += overrun_add
        flagged_reasons.append(
            f"Cost Escalation: Final settled cost exceeded recommended estimate by {cost_pct} (₹{abs(cost_delta):,.0f} overrun)"
        )
        explainability_tags.append("COST_OVERRUN")
    elif cost_ratio > 1.05:
        rule_penalty += 10.0
        flagged_reasons.append(
            f"Minor Cost Variance: Final settled cost exceeded estimate by {cost_pct} (₹{abs(cost_delta):,.0f})"
        )
        explainability_tags.append("COST_OVERRUN")
    else:
        explainability_tags.append("BUDGET_COMPLIANT")

    # Check 3: Execution delay
    if duration > 365:
        delay_add = min(20.0, (duration - 365) / 30.0 * 2.5)
        rule_penalty += delay_add
        flagged_reasons.append(
            f"Prolonged Duration: Project took {duration} days against state average benchmark of 180 days"
        )
        explainability_tags.append("CHRONIC_DELAY")
    else:
        explainability_tags.append("ON_TIME_COMPLETION")

    # Check 4: Category spending outlier
    if z_score > 2.0:
        rule_penalty += min(15.0, (z_score - 2.0) * 5.0)
        flagged_reasons.append(
            f"Sector Spending Outlier: Settled expenditure is {z_score:.2f} standard deviations above sector mean"
        )
        explainability_tags.append("CATEGORY_SPENDING_SPIKE")

    # Blended score: 45% ML Isolation Forest + 55% Governance Rule Engine
    final_risk = float(np.clip(base_ml_score * 0.45 + rule_penalty * 0.55, 0.0, 100.0))
    final_risk = round(final_risk, 1)

    # Classification thresholds
    if final_risk >= 70.0:
        risk_level = "HIGH_EXECUTION_RISK"
        is_compliant = False
        recommended_action = "Withhold contractor final retention money and mandate geo-tagged physical inspection by District Vigilance Officer."
    elif final_risk >= 31.0:
        risk_level = "MODERATE_RISK"
        is_compliant = (has_photo and cost_ratio <= 1.20)
        recommended_action = "Issue administrative query for cost/duration variance before final accounting closure."
    else:
        risk_level = "COMPLIANT_LOW_RISK"
        is_compliant = True
        recommended_action = "Standard audit closure approved."

    return final_risk, risk_level, is_compliant, flagged_reasons, explainability_tags, recommended_action


def score_single_work(work: WorkInput) -> WorkRiskResponse:
    """Scores an individual work and returns detailed diagnostic response."""
    registry = get_registry()
    model = registry.get_model()
    scaler = registry.get_scaler()
    cat_stats = registry.get_category_stats()
    mp_rates = registry.get_mp_completion_rates()

    feat_vector, metrics_raw = _calculate_features_for_work(work, cat_stats, mp_rates)
    
    # Scale feature vector
    feat_scaled = scaler.transform(feat_vector.reshape(1, -1))
    raw_dec = float(model.decision_function(feat_scaled)[0])

    (
        risk_score,
        risk_level,
        is_compliant,
        flagged_reasons,
        explainability_tags,
        recommended_action
    ) = _compute_risk_score_and_reasons(raw_dec, metrics_raw)

    metrics = WorkMetrics(
        recommended_cost=metrics_raw["recommended_cost"],
        final_settled_cost=metrics_raw["final_settled_cost"],
        cost_escalation_pct=metrics_raw["cost_escalation_pct"],
        cost_escalation_ratio=metrics_raw["cost_escalation_ratio"],
        execution_duration_days=metrics_raw["execution_duration_days"],
        has_photo_evidence=metrics_raw["has_photo_evidence"],
        mp_completion_rate_pct=metrics_raw["mp_completion_rate_pct"],
        category_z_score=metrics_raw["category_z_score"]
    )

    return WorkRiskResponse(
        work_id=work.work_id,
        execution_risk_score=risk_score,
        risk_level=risk_level,
        is_compliant=is_compliant,
        metrics=metrics,
        flagged_reasons=flagged_reasons,
        explainability_tags=explainability_tags,
        recommended_action=recommended_action
    )


def score_batch_works(works: List[WorkInput]) -> BatchRiskResponse:
    """Batch-scores a list of works with vectorized scaling, model scoring, and aggregate metrics."""
    if not works:
        return BatchRiskResponse(
            summary=BatchRiskSummary(
                total_works=0,
                average_risk_score=0.0,
                high_risk_count=0,
                moderate_risk_count=0,
                compliant_count=0,
                missing_photos_count=0,
                cost_overrun_works_count=0,
                delayed_works_count=0,
                total_recommended_amount=0.0,
                total_final_amount=0.0,
                total_cost_overrun_amount=0.0
            ),
            flagged_works=[],
            all_works=[]
        )

    registry = get_registry()
    model = registry.get_model()
    scaler = registry.get_scaler()
    cat_stats = registry.get_category_stats()
    mp_rates = registry.get_mp_completion_rates()

    feature_matrix = []
    metrics_list = []

    for work in works:
        feat_vector, metrics_raw = _calculate_features_for_work(work, cat_stats, mp_rates)
        feature_matrix.append(feat_vector)
        metrics_list.append(metrics_raw)

    feature_matrix = np.array(feature_matrix, dtype=np.float64)
    scaled_matrix = scaler.transform(feature_matrix)
    decision_scores = model.decision_function(scaled_matrix)

    all_works: List[WorkRiskResponse] = []
    high_risk_count = 0
    moderate_risk_count = 0
    compliant_count = 0
    missing_photos_count = 0
    cost_overrun_count = 0
    delayed_count = 0
    total_rec_amt = 0.0
    total_final_amt = 0.0
    total_cost_overrun_amt = 0.0
    total_risk_score = 0.0

    for i, work in enumerate(works):
        raw_dec = float(decision_scores[i])
        metrics_raw = metrics_list[i]

        (
            risk_score,
            risk_level,
            is_compliant,
            flagged_reasons,
            explainability_tags,
            recommended_action
        ) = _compute_risk_score_and_reasons(raw_dec, metrics_raw)

        metrics = WorkMetrics(
            recommended_cost=metrics_raw["recommended_cost"],
            final_settled_cost=metrics_raw["final_settled_cost"],
            cost_escalation_pct=metrics_raw["cost_escalation_pct"],
            cost_escalation_ratio=metrics_raw["cost_escalation_ratio"],
            execution_duration_days=metrics_raw["execution_duration_days"],
            has_photo_evidence=metrics_raw["has_photo_evidence"],
            mp_completion_rate_pct=metrics_raw["mp_completion_rate_pct"],
            category_z_score=metrics_raw["category_z_score"]
        )

        response_item = WorkRiskResponse(
            work_id=work.work_id,
            execution_risk_score=risk_score,
            risk_level=risk_level,
            is_compliant=is_compliant,
            metrics=metrics,
            flagged_reasons=flagged_reasons,
            explainability_tags=explainability_tags,
            recommended_action=recommended_action
        )
        all_works.append(response_item)

        # Aggregate metrics
        total_risk_score += risk_score
        total_rec_amt += metrics_raw["recommended_cost"]
        total_final_amt += metrics_raw["final_settled_cost"]
        if metrics_raw["cost_delta"] > 0:
            total_cost_overrun_amt += metrics_raw["cost_delta"]

        if risk_level == "HIGH_EXECUTION_RISK":
            high_risk_count += 1
        elif risk_level == "MODERATE_RISK":
            moderate_risk_count += 1
        else:
            compliant_count += 1

        if not metrics_raw["has_photo_evidence"]:
            missing_photos_count += 1
        if metrics_raw["cost_escalation_ratio"] > 1.05:
            cost_overrun_count += 1
        if metrics_raw["execution_duration_days"] > 365:
            delayed_count += 1

    avg_risk = round(total_risk_score / len(works), 1) if works else 0.0
    
    # Filter flagged works (elevated risk or non-compliant), sorted descending by risk score
    flagged_works = [w for w in all_works if w.execution_risk_score >= 31.0 or not w.is_compliant]
    flagged_works.sort(key=lambda w: w.execution_risk_score, reverse=True)

    summary = BatchRiskSummary(
        total_works=len(works),
        average_risk_score=avg_risk,
        high_risk_count=high_risk_count,
        moderate_risk_count=moderate_risk_count,
        compliant_count=compliant_count,
        missing_photos_count=missing_photos_count,
        cost_overrun_works_count=cost_overrun_count,
        delayed_works_count=delayed_count,
        total_recommended_amount=round(total_rec_amt, 2),
        total_final_amount=round(total_final_amt, 2),
        total_cost_overrun_amount=round(total_cost_overrun_amt, 2)
    )

    return BatchRiskResponse(
        summary=summary,
        flagged_works=flagged_works,
        all_works=all_works
    )
