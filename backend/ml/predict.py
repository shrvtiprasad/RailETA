from __future__ import annotations

from functools import lru_cache
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from .contract import DataUnavailableError, require_file


logger = logging.getLogger(__name__)


@lru_cache(maxsize=4)
def load_artifact(model_path: Path) -> dict[str, Any]:
    require_file(model_path, "trained ETA model")
    try:
        import joblib

        artifact = joblib.load(model_path)
    except ImportError as exc:
        raise DataUnavailableError("joblib is not installed; install backend/requirements.txt first.") from exc
    if not isinstance(artifact, dict) or "pipeline" not in artifact:
        raise DataUnavailableError(f"The model artifact at {model_path} is not a valid RailETA artifact.")
    logger.info(
        "ETA model loaded successfully path=%s version=%s",
        model_path,
        artifact.get("model_version", "unknown"),
    )
    return artifact


def predict_delay(model_path: Path, features: pd.DataFrame) -> pd.Series:
    artifact = load_artifact(model_path)
    columns = artifact["categorical_features"] + artifact["numeric_features"]
    missing = [column for column in columns if column not in features.columns]
    if missing:
        raise DataUnavailableError(
            "Prediction features are missing columns from the trained model: "
            + ", ".join(missing)
        )
    predictions = artifact["pipeline"].predict(features[columns])
    return pd.Series(predictions, index=features.index, name="predicted_arrival_delay_minutes")
