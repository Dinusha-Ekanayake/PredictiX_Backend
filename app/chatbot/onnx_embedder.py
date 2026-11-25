"""all-MiniLM-L6-v2 query embeddings through ONNX Runtime, without torch.

The EC2 instance cannot hold torch (1 GB RAM, 8 GB disk), and the hosted
Hugging Face embedding endpoint is not reliably available, so the server
embeds chatbot queries with the model's official ONNX export instead. It
produces the vectors sentence-transformers does (same weights, same
tokenizer, mean pooling over the attention mask, L2 normalisation), which is
what the stored passages were embedded with; test_onnx_embedder checks that
the two agree.

Only queries use this path. Bulk ingestion keeps sentence-transformers
(app/kb/pipeline/embedding.py), so stored vectors always come from the
reference implementation.

    python -m app.chatbot.onnx_embedder   # fetch the model into the HF cache
"""
from __future__ import annotations

import os
import sys

MODEL_REPO = "sentence-transformers/all-MiniLM-L6-v2"
# Pinned to the commit the stored passages were embedded with (the local
# sentence-transformers cache), so the weights cannot change underneath them.
MODEL_REVISION = os.getenv("EMBEDDING_ONNX_REVISION", "1110a243fdf4706b3f48f1d95db1a4f5529b4d41")
MODEL_FILE = "onnx/model.onnx"
TOKENIZER_FILE = "tokenizer.json"
MAX_TOKENS = 256  # sentence-transformers' max_seq_length for this model


class OnnxMiniLM:
    """Callable embedder: text -> 384 floats, unit length."""

    def __init__(self, model_path: str, tokenizer_path: str) -> None:
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self._tokenizer = Tokenizer.from_file(tokenizer_path)
        self._tokenizer.enable_truncation(max_length=MAX_TOKENS)
        self._tokenizer.no_padding()

        options = ort.SessionOptions()
        # Two vCPUs on the instance; leave one for the web server.
        options.intra_op_num_threads = int(os.getenv("EMBEDDING_ONNX_THREADS", "1"))
        options.inter_op_num_threads = 1
        self._session = ort.InferenceSession(model_path, options, providers=["CPUExecutionProvider"])
        self._input_names = {i.name for i in self._session.get_inputs()}

    def encode(self, text: str) -> list[float]:
        import numpy as np

        encoding = self._tokenizer.encode(text)
        feeds = {
            "input_ids": np.array([encoding.ids], dtype=np.int64),
            "attention_mask": np.array([encoding.attention_mask], dtype=np.int64),
            "token_type_ids": np.array([encoding.type_ids], dtype=np.int64),
        }
        hidden = self._session.run(None, {k: v for k, v in feeds.items() if k in self._input_names})[0]
        return pool(hidden, feeds["attention_mask"])


def pool(hidden, attention_mask) -> list[float]:
    """Mean of the token vectors the mask marks as real, scaled to unit length."""
    import numpy as np

    mask = attention_mask[..., None].astype(np.float32)
    summed = (hidden * mask).sum(axis=1)
    counts = np.clip(mask.sum(axis=1), 1e-9, None)
    mean = (summed / counts)[0]
    norm = float(np.linalg.norm(mean))
    return [float(x) for x in (mean / max(norm, 1e-12))]


def fetch_model_files() -> tuple[str, str]:
    """Local paths of the model and tokenizer, downloading them on first use."""
    from huggingface_hub import hf_hub_download

    kwargs = {"repo_id": MODEL_REPO, "revision": MODEL_REVISION}
    return hf_hub_download(filename=MODEL_FILE, **kwargs), hf_hub_download(filename=TOKENIZER_FILE, **kwargs)


def load() -> OnnxMiniLM:
    """The embedder from the local Hugging Face cache (or a download if allowed)."""
    model_path, tokenizer_path = fetch_model_files()
    return OnnxMiniLM(model_path, tokenizer_path)


def main() -> int:
    """Download the model into the cache. Safe to run repeatedly."""
    os.environ["HF_HUB_OFFLINE"] = "0"
    model_path, tokenizer_path = fetch_model_files()
    vector = OnnxMiniLM(model_path, tokenizer_path).encode("brake inspection interval")
    print(f"ONNX embedding model ready: {model_path} ({len(vector)} dimensions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
