"""Model and statistical artifact loader for FastAPI server."""

import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional
import joblib

logger = logging.getLogger("fastapi_app.models.loader")

# Base directory for artifacts
BASE_DIR = Path(__file__).resolve().parent.parent.parent
MODELS_DIR = BASE_DIR / "models"


class ModelRegistry:
    """Singleton registry holding loaded machine learning artifacts in memory."""
    
    _instance: Optional["ModelRegistry"] = None
    
    def __init__(self):
        self.model = None
        self.scaler = None
        self.category_stats: Dict[str, Any] = {}
        self.mp_completion_rates: Dict[str, float] = {}
        self.loaded: bool = False

    @classmethod
    def get_instance(cls) -> "ModelRegistry":
        if cls._instance is None:
            cls._instance = ModelRegistry()
        return cls._instance

    def load_artifacts(self, models_path: Optional[Path] = None):
        """Loads all model and metadata artifacts into RAM."""
        target_dir = models_path or MODELS_DIR
        logger.info("Loading model artifacts from %s...", target_dir)
        
        model_file = target_dir / "execution_model.joblib"
        scaler_file = target_dir / "scaler.joblib"
        cat_file = target_dir / "category_stats.json"
        mp_file = target_dir / "mp_completion_rates.json"

        if not model_file.exists():
            raise FileNotFoundError(f"Model artifact not found at {model_file}. Run train_models.py first.")
        if not scaler_file.exists():
            raise FileNotFoundError(f"Scaler artifact not found at {scaler_file}. Run train_models.py first.")
        if not cat_file.exists():
            raise FileNotFoundError(f"Category stats artifact not found at {cat_file}. Run train_models.py first.")
        if not mp_file.exists():
            raise FileNotFoundError(f"MP completion rates artifact not found at {mp_file}. Run train_models.py first.")

        # Load Isolation Forest
        self.model = joblib.load(model_file)
        logger.info("Loaded IsolationForest model artifact.")

        # Load Scaler
        self.scaler = joblib.load(scaler_file)
        logger.info("Loaded StandardScaler artifact.")

        # Load Category Stats JSON
        with open(cat_file, "r", encoding="utf-8") as f:
            self.category_stats = json.load(f)
        logger.info("Loaded %d category statistics entries.", len(self.category_stats))

        # Load MP Completion Rates JSON
        with open(mp_file, "r", encoding="utf-8") as f:
            self.mp_completion_rates = json.load(f)
        logger.info("Loaded %d MP completion rate entries.", len(self.mp_completion_rates))

        self.loaded = True
        logger.info("All model artifacts successfully initialized in RAM.")

    def get_model(self):
        if not self.loaded or self.model is None:
            self.load_artifacts()
        return self.model

    def get_scaler(self):
        if not self.loaded or self.scaler is None:
            self.load_artifacts()
        return self.scaler

    def get_category_stats(self) -> Dict[str, Any]:
        if not self.loaded:
            self.load_artifacts()
        return self.category_stats

    def get_mp_completion_rates(self) -> Dict[str, float]:
        if not self.loaded:
            self.load_artifacts()
        return self.mp_completion_rates

    def is_loaded(self) -> bool:
        return self.loaded


# Helper functions for dependency injection
def get_registry() -> ModelRegistry:
    return ModelRegistry.get_instance()
