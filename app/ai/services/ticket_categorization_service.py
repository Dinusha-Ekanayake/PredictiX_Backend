import os
from functools import lru_cache

import torch
from dotenv import load_dotenv
from transformers import AutoModelForSequenceClassification, AutoTokenizer

load_dotenv()

HF_TOKEN = os.getenv("HF_TOKEN")
MODEL_REPO = os.getenv("HF_TICKET_CATEGORIZATION_REPO")

if not HF_TOKEN:
    print("WARNING: HF_TOKEN is not set in .env. Ticket categorization will be unavailable.")

if not MODEL_REPO:
    print("WARNING: HF_TICKET_CATEGORIZATION_REPO is not set in .env. Ticket categorization will be unavailable.")

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


@lru_cache(maxsize=1)
def get_ticket_categorizer_tokenizer():
    return AutoTokenizer.from_pretrained(
        MODEL_REPO,
        token=HF_TOKEN,
    )


@lru_cache(maxsize=1)
def get_ticket_categorizer_model():
    model = AutoModelForSequenceClassification.from_pretrained(
        MODEL_REPO,
        token=HF_TOKEN,
    )
    model.to(DEVICE)
    model.eval()
    return model


def categorize_ticket_text(title: str, description: str) -> dict:
    title = (title or "").strip()
    description = (description or "").strip()

    if not title and not description:
        raise ValueError("Both title and description cannot be empty.")

    text = f"Title: {title}\nDescription: {description}"

    tokenizer = get_ticket_categorizer_tokenizer()
    model = get_ticket_categorizer_model()

    inputs = tokenizer(
        text,
        return_tensors="pt",
        truncation=True,
        padding=True,
        max_length=256,
    )
    inputs = {k: v.to(DEVICE) for k, v in inputs.items()}

    with torch.no_grad():
        outputs = model(**inputs)
        probs = torch.softmax(outputs.logits, dim=-1)[0]

    pred_idx = int(torch.argmax(probs).item())
    confidence = float(probs[pred_idx].item())

    id2label = getattr(model.config, "id2label", {}) or {}
    predicted_label = id2label.get(pred_idx, str(pred_idx))

    scores = [
        {
            "label": id2label.get(i, str(i)),
            "score": round(float(score), 4),
        }
        for i, score in enumerate(probs.tolist())
    ]
    scores.sort(key=lambda item: item["score"], reverse=True)

    return {
        "predicted_label": predicted_label,
        "confidence": round(confidence, 4),
        "scores": scores,
    }


def warmup_ticket_categorizer() -> None:
    get_ticket_categorizer_tokenizer()
    get_ticket_categorizer_model()