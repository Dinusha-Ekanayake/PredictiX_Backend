import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

# Load .env file from project root
env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)


def get_hf_credentials():
    """Get HuggingFace credentials from environment variables"""
    hf_token = os.getenv("HF_TOKEN")
    model_repo = os.getenv("HF_ASSET_SUMMARIZATION_REPO")
    
    if not hf_token:
        raise RuntimeError("HF_TOKEN is not set in .env")
    
    if not model_repo:
        raise RuntimeError("HF_ASSET_SUMMARIZATION_REPO is not set in .env")
    
    return hf_token, model_repo


@lru_cache(maxsize=1)
def get_asset_summary_model():
    """Load Seq2Seq model and tokenizer from Hugging Face"""
    try:
        hf_token, model_repo = get_hf_credentials()
        
        # Load tokenizer
        tokenizer = AutoTokenizer.from_pretrained(
            model_repo,
            token=hf_token,
        )
        
        # Load model
        model = AutoModelForSeq2SeqLM.from_pretrained(
            model_repo,
            token=hf_token,
        )
        
        print(f"Asset summary model loaded successfully from HuggingFace: {model_repo}")
        return {"model": model, "tokenizer": tokenizer}
    except Exception as e:
        print(f"Failed to load asset summary model from HuggingFace: {e}")
        raise


def generate_asset_summary(input_text: str) -> str:
    """
    Generate summary for an asset using the Seq2Seq model
    
    Args:
        input_text: Formatted input text (pipe-separated vehicle/asset attributes)
                   Example: "Vehicle: SLW0225 | Type: Light Truck 3.5T | Model: Mitsubishi Canter | ..."
        
    Returns:
        Generated summary string
    """
    try:
        model_data = get_asset_summary_model()
        
        if model_data is None:
            raise RuntimeError("Asset summary model not loaded")
        
        if not input_text or not input_text.strip():
            raise ValueError("input_text cannot be empty")
        
        model = model_data["model"]
        tokenizer = model_data["tokenizer"]
        
        # Tokenize input
        inputs = tokenizer(input_text, return_tensors="pt", max_length=512, truncation=True)
        
        # Generate summary
        summary_ids = model.generate(
            inputs["input_ids"],
            max_length=256,
            min_length=50,
            num_beams=4,
            early_stopping=True
        )
        
        # Decode summary
        summary = tokenizer.decode(summary_ids[0], skip_special_tokens=True)
        
        return summary
    except Exception as e:
        raise RuntimeError(f"Summary generation failed: {e}")

def warmup_asset_summary_model():
    """Pre-load the model on application startup"""
    try:
        get_asset_summary_model()
        print("Asset summary model warmed up successfully")
    except Exception as e:
        print(f"Asset summary model warmup failed: {e}")
        raise
