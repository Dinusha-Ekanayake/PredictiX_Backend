import os
from dotenv import load_dotenv
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch

load_dotenv()

HF_TOKEN = os.getenv("HF_TOKEN")
REPO_ID = os.getenv("HF_TICKET_CATEGORIZATION_REPO")

tokenizer = AutoTokenizer.from_pretrained(REPO_ID, token=HF_TOKEN)
model = AutoModelForSequenceClassification.from_pretrained(REPO_ID, token=HF_TOKEN)

text = "Forklift engine overheating and hydraulic pressure warning"
inputs = tokenizer(text, return_tensors="pt", truncation=True, padding=True)

with torch.no_grad():
    outputs = model(**inputs)
    probs = torch.softmax(outputs.logits, dim=-1)[0]
    pred_idx = int(torch.argmax(probs).item())

print("Predicted index:", pred_idx)
print("Confidence:", float(probs[pred_idx]))
print("Labels:", getattr(model.config, "id2label", {}))