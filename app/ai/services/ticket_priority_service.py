import os
import io
import re
from functools import lru_cache

import joblib
import nltk
import pandas as pd
import requests
from dotenv import load_dotenv
from fastapi import HTTPException
from nltk.corpus import stopwords
from nltk.stem import PorterStemmer

load_dotenv(override=True)

_MODEL_FILENAME = "xgboost_vehicle_priority_model_3class.pkl"
_ENCODER_FILENAME = "priority_label_encoder.pkl"

nltk.download("stopwords", quiet=True)
_stop_words = set(stopwords.words("english"))
_stemmer = PorterStemmer()


def _clean_text(text: str) -> str:
    text = str(text).lower()
    text = text.replace("pls", "please").replace("asap", "as soon as possible")
    text = text.replace("veh.", "vehicle").replace("maint.", "maintenance")
    text = text.replace("warn.", "warning").replace("temp", "temperature")
    text = re.sub(r"http\S+|www\S+", " ", text)
    text = re.sub(r"[^a-zA-Z\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    important_short_terms = {"ac", "abs", "rpm"}
    out = []
    for tok in text.split():
        if tok in important_short_terms:
            out.append(tok)
        elif tok not in _stop_words and len(tok) > 2:
            out.append(_stemmer.stem(tok))
    return " ".join(out)



def _get_hf_config() -> tuple[str, str]:
    token = os.getenv("HF_TOKEN")
    repo = os.getenv("HF_TICKET_PRIORITIZATION_REPO")
    if not token:
        raise RuntimeError("HF_TOKEN is not set in .env")
    if not repo:
        raise RuntimeError("HF_TICKET_PRIORITIZATION_REPO is not set in .env")
    return token, repo


@lru_cache(maxsize=1)
def _load_model_and_encoder():
    token, repo = _get_hf_config()

    def _download(filename: str) -> bytes:
        url = f"https://huggingface.co/{repo}/resolve/main/{filename}"
        resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=60)
        resp.raise_for_status()
        return resp.content

    try:
        model = joblib.load(io.BytesIO(_download(_MODEL_FILENAME)))
        print(f"[PriorityService] Loaded model: {_MODEL_FILENAME}")
    except Exception as e:
        raise RuntimeError(f"Failed to load priority model: {e}") from e

    try:
        encoder = joblib.load(io.BytesIO(_download(_ENCODER_FILENAME)))
        print(f"[PriorityService] Loaded label encoder: {_ENCODER_FILENAME}")
    except Exception as e:
        raise RuntimeError(f"Failed to load label encoder: {e}") from e

    return model, encoder


_LOW_KEYWORDS = {
    "scratch", "dent", "cosmetic", "minor", "small crack", "paint", "sticker",
    "mirror", "wiper", "next service", "next scheduled", "no rush", "low urgency",
    "seat cover", "floor mat", "trim", "logo", "decal", "cleaning",
}

_HIGH_KEYWORDS = {
    "fire", "smoke", "explosion", "fuel leak", "brake failure", "no brakes",
    "engine seized", "total failure", "accident", "crash", "rollover",
    "unsafe to drive", "cannot drive", "vehicle stopped", "complete breakdown",
    "coolant leak", "overheating", "electrical fire", "cannot start",
}


def _rule_based_override(text: str) -> str | None:
    lower = text.lower()
    if any(kw in lower for kw in _HIGH_KEYWORDS):
        return "High"
    if any(kw in lower for kw in _LOW_KEYWORDS):
        return "Low"
    return None


def classify_ticket_priority(
    text: str,
    vehicle_type: str = "Truck",
    issue_category: str = "Engine",
    sensor_alert: str = "Check engine light",
    operating_environment: str = "Urban",
    weather_condition: str = "Normal",
    vehicle_age: int = 5,
    mileage_km: int = 100000,
    downtime_hours: float = 0.0,
    maintenance_overdue_days: int = 0,
    previous_failures: int = 0,
) -> str:
    try:
        override = _rule_based_override(text)
        if override:
            return override

        model, encoder = _load_model_and_encoder()
        row = pd.DataFrame([{
            "combined_text": _clean_text(text),
            "vehicle_type": vehicle_type,
            "issue_category": issue_category,
            "sensor_alert": sensor_alert,
            "operating_environment": operating_environment,
            "weather_condition": weather_condition,
            "vehicle_age": vehicle_age,
            "mileage_km": mileage_km,
            "downtime_hours": downtime_hours,
            "maintenance_overdue_days": maintenance_overdue_days,
            "previous_failures": previous_failures,
        }])
        pred = model.predict(row)[0]
        return encoder.inverse_transform([pred])[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Priority classification failed: {e}")


def warmup_priority_model() -> None:
    _load_model_and_encoder()
