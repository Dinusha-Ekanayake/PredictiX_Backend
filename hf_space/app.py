"""HF Space — serve the fine-tuned BART summariser (ONNX) over a Gradio API.

The model files (encoder_model.onnx, decoder_model_merged.onnx, tokenizer, config)
live in this Space's root, so we load them locally with Optimum + ONNX Runtime —
no download at request time. The SAME app.py works for both the asset- and
ticket-summary Spaces; each Space holds its own model.

Exposes one API endpoint: POST /run/predict  (client: api_name="/predict").
"""
import gradio as gr
from transformers import AutoTokenizer
from optimum.onnxruntime import ORTModelForSeq2SeqLM

# Model files are in the Space root ("."), already present — nothing to download.
_tok = AutoTokenizer.from_pretrained(".")
_model = ORTModelForSeq2SeqLM.from_pretrained(".")


def summarize(input_text: str) -> str:
    if not input_text or not input_text.strip():
        return ""
    inputs = _tok(input_text, return_tensors="pt", max_length=512, truncation=True)
    ids = _model.generate(
        inputs["input_ids"],
        max_new_tokens=200,
        min_new_tokens=40,
        num_beams=4,
        no_repeat_ngram_size=3,
        length_penalty=1.3,
        early_stopping=True,
    )
    return _tok.decode(ids[0], skip_special_tokens=True).strip()


demo = gr.Interface(
    fn=summarize,
    inputs=gr.Textbox(label="input_text"),
    outputs=gr.Textbox(label="summary"),
    title="PredictiX Summariser",
    description="Fine-tuned BART (ONNX) summariser. Send pipe-separated fields.",
)

if __name__ == "__main__":
    demo.launch()
