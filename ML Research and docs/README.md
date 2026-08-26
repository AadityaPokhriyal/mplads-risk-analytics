# ML Research & Documentation

This directory contains the machine learning architecture, detailed pillar-by-pillar research notes, and hackathon presentation guides for the **MPLADS AI Risk Analytics** platform (SIH 2026).

---

## 📚 Documentation Index

### 🌟 Master Overview & Defense Guide
* [**`ML_RESEARCH_AND_HACKATHON_GUIDE.md`**](file:///c:/Users/DIVYA/OneDrive/Desktop/3_Projects_and_Development/Projects/SIH/mplads-risk-analytics/Ml%20research%20and%20docs/ML_RESEARCH_AND_HACKATHON_GUIDE.md)
  * Complete end-to-end ML architecture.
  * Why Isolation Forest is the right choice for unlabeled data.
  * Composite Risk Score (0–100) aggregation formula.
  * 30-Second Elevator Pitch & Top 5 Judge Q&A.
* [**`WHY_ML_OVER_RULE_BASED_SYSTEMS.md`**](file:///c:/Users/DIVYA/OneDrive/Desktop/3_Projects_and_Development/Projects/SIH/mplads-risk-analytics/Ml%20research%20and%20docs/WHY_ML_OVER_RULE_BASED_SYSTEMS.md)
  * **Judge FAQ Defense:** Why simple `if/else` rules fail against adaptive fraud, multi-dimensional interactions, context-aware distributions, and the hybrid "Rules as Features $\rightarrow$ ML as the Brain" architecture.

---

### 🔌 Model Input & Output (I/O) Specifications
* [**`MODEL_1_EXPENDITURE_ANOMALY_IO_SPEC.md`**](file:///c:/Users/DIVYA/OneDrive/Desktop/3_Projects_and_Development/Projects/SIH/mplads-risk-analytics/Ml%20research%20and%20docs/MODEL_1_EXPENDITURE_ANOMALY_IO_SPEC.md)
  * Exact feature vector, raw CSV fields, live JSON request payload, and response schema (Risk score, Smurfing flags, explainability tags, and UI mappings) for **Isolation Forest**.
* [**`MODEL_2_EXECUTION_DELAY_IO_SPEC.md`**](file:///c:/Users/DIVYA/OneDrive/Desktop/3_Projects_and_Development/Projects/SIH/mplads-risk-analytics/Ml%20research%20and%20docs/MODEL_2_EXECUTION_DELAY_IO_SPEC.md)
  * Exact input deltas (cost escalation %, duration, photo flags) and output JSON schema (Execution Risk score, compliance status, audit recommendations) for **Project Execution Scorer**.

---

### 🏛️ The 4 Individual AI/ML Pillars

| Pillar Document | Core Technique | Focus Problem | Key Dataset Evidence |
| :--- | :---: | :--- | :--- |
| 1. [**`PILLAR_1_EXPENDITURE_ANOMALY.md`**](file:///c:/Users/DIVYA/OneDrive/Desktop/3_Projects_and_Development/Projects/SIH/mplads-risk-analytics/Ml%20research%20and%20docs/PILLAR_1_EXPENDITURE_ANOMALY.md) | **Isolation Forest** | Invoice splitting (Smurfing), threshold evasion, sudden fund dumping | Median transaction across 106K rows is exactly **₹1,99,999.00** |
| 2. [**`PILLAR_2_PROJECT_DELAY_AND_COST_OVERRUN.md`**](file:///c:/Users/DIVYA/OneDrive/Desktop/3_Projects_and_Development/Projects/SIH/mplads-risk-analytics/Ml%20research%20and%20docs/PILLAR_2_PROJECT_DELAY_AND_COST_OVERRUN.md) | **Outlier Scoring** | Stalled projects, inflated final costs, zero-proof completions | **12,747 completed works (29.5%)** have zero photo proof |
| 3. [**`PILLAR_3_DUPLICATE_AND_GHOST_WORKS.md`**](file:///c:/Users/DIVYA/OneDrive/Desktop/3_Projects_and_Development/Projects/SIH/mplads-risk-analytics/Ml%20research%20and%20docs/PILLAR_3_DUPLICATE_AND_GHOST_WORKS.md) | **NLP (TF-IDF + Cosine)** | Rephrased proposals, duplicate Work IDs, double billing | **30 duplicate Work IDs** present in recommended works |
| 4. [**`PILLAR_4_VENDOR_MONOPOLY_AND_CARTELS.md`**](file:///c:/Users/DIVYA/OneDrive/Desktop/3_Projects_and_Development/Projects/SIH/mplads-risk-analytics/Ml%20research%20and%20docs/PILLAR_4_VENDOR_MONOPOLY_AND_CARTELS.md) | **Herfindahl Index (HHI)** | Contractor monopolies, cartel collusion, lack of competitive bidding | Top 10 vendors capture over **₹1.71 Billion** across districts |

---

### 📊 Dataset Catalog & Schemas
* [**`Datasets/README.md`**](file:///c:/Users/DIVYA/OneDrive/Desktop/3_Projects_and_Development/Projects/SIH/mplads-risk-analytics/Datasets/README.md)
  * Schema data dictionary, ER diagrams, numerical stats, and data cleaning rules for all 7 raw CSV/JSON files.
