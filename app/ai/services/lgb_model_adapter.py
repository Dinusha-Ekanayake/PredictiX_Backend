"""Loader + inference adapter for the v7 LightGBM PdM models.

The v7 classifier and regressor are plain ``lgb.Booster`` text files
(``Booster.save_model()``), not pickled sklearn-style estimators like the
old v5/v6 CatBoost/XGBoost bundles. This module wraps a ``Booster`` in a
small adapter exposing ``.predict_proba()`` / ``.predict()`` so the rest of
the codebase (batch + single-asset prediction services) can call it the
same way regardless of which model generation is loaded.

Categorical handling: LightGBM boosters trained on a pandas DataFrame with
``pandas_categorical`` metadata require inference-time categorical columns
to be ``pd.Categorical`` with the *same* category vocabulary (order
included) as training — passing raw strings/ints raises "train and valid
dataset categorical_feature do not match". ``LgbModelBundle.categories``
holds that vocabulary, extracted once at load time via
``Booster.pandas_categorical``, and ``build_frame()`` applies it.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import lightgbm as lgb


class LgbModelBundle:
    """One loaded LightGBM booster + everything needed to build its input frame."""

    def __init__(self, model_path: Path):
        self.booster = lgb.Booster(model_file=str(model_path))
        self.feature_names: list[str] = self.booster.feature_name()

        cat_idx = self._parse_categorical_indices()
        self.categorical_cols: list[str] = [self.feature_names[i] for i in cat_idx]

        # Booster.pandas_categorical is the ordered list of category vocabularies
        # (one list per categorical column, in the same order they appear among
        # the categorical columns) saved from the training DataFrame.
        raw_categories = self.booster.pandas_categorical or []
        self.categories: dict[str, list] = {
            col: list(vocab) for col, vocab in zip(self.categorical_cols, raw_categories)
        }

    def _parse_categorical_indices(self) -> list[int]:
        params = self.booster.dump_model().get("pandas_categorical")
        # Fallback: parse the "categorical_feature" line straight from the
        # booster's own text dump if the JSON dump doesn't carry it.
        model_str = self.booster.model_to_string()
        for line in model_str.splitlines():
            line = line.strip()
            if line.startswith("[categorical_feature:"):
                inner = line[len("[categorical_feature:"):-1].strip()
                if not inner:
                    return []
                return [int(x) for x in inner.split(",")]
        return []

    def build_frame(self, feature_dicts: list[dict[str, Any]]) -> pd.DataFrame:
        """One row per item in ``feature_dicts``, columns = training feature order.

        Numeric columns are coerced to float64 (missing -> NaN, which LightGBM
        treats as a native missing value). Categorical columns are cast to
        ``pd.Categorical`` using the exact training-time vocabulary; values not
        seen during training become NaN (LightGBM's native "unseen category"
        handling) instead of raising.
        """
        cat_set = set(self.categorical_cols)
        rows = [
            {f: fd.get(f, "" if f in cat_set else 0) for f in self.feature_names}
            for fd in feature_dicts
        ]
        df = pd.DataFrame(rows, columns=self.feature_names)

        for col in self.feature_names:
            if col in cat_set:
                df[col] = pd.Categorical(
                    df[col].astype(str), categories=self.categories.get(col, [])
                )
            else:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        return df

    def predict_proba_positive(self, df: pd.DataFrame) -> np.ndarray:
        """Binary-classifier positive-class probability per row."""
        return np.asarray(self.booster.predict(df), dtype=float)

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        return np.asarray(self.booster.predict(df), dtype=float)

    def shap_top_factors(self, df: pd.DataFrame, top_n: int = 5) -> list[list[dict]]:
        """SHAP-style per-row feature contributions via LightGBM's native
        ``pred_contrib``. Returns one list of ``{"feature", "impact"}`` dicts
        per row, sorted by |impact| descending, dropping the trailing bias term.
        """
        contrib = self.booster.predict(df, pred_contrib=True)
        contrib = np.asarray(contrib)
        # For binary classification, LightGBM returns (n_rows, n_features + 1);
        # last column is the base/bias value, not a feature contribution.
        feature_contrib = contrib[:, :-1]

        results: list[list[dict]] = []
        for row in feature_contrib:
            ranked = sorted(
                zip(self.feature_names, row), key=lambda x: abs(x[1]), reverse=True
            )
            results.append(
                [
                    {"feature": feat, "impact": round(float(val), 4)}
                    for feat, val in ranked[:top_n]
                ]
            )
        return results
