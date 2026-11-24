"""Embed passages with the same model that embeds queries at search time.

Bulk ingestion uses the local model only. If it cannot load, the run stops:
silently mixing vectors from a different source would make similarity scores
meaningless.
"""
from __future__ import annotations

import math

from app.kb.pipeline.config import EMBEDDING_DIM, EMBEDDING_MODEL, MODEL_MAX_TOKENS


class EmbeddingError(RuntimeError):
    """The model is unavailable or produced an invalid vector."""


class Embedder:
    def __init__(self) -> None:
        from app.chatbot.knowledge_service import _get_local_model

        model = _get_local_model()
        if model is None:
            raise EmbeddingError(
                f"Local embedding model {EMBEDDING_MODEL} is not available. "
                "Install sentence-transformers and cache the model before ingesting."
            )
        if getattr(model, "max_seq_length", MODEL_MAX_TOKENS) < MODEL_MAX_TOKENS:
            raise EmbeddingError("embedding model input limit is lower than the chunker assumes")
        self._model = model
        self.model_name = EMBEDDING_MODEL
        # count_tokens measures over-long sentences before the chunker splits
        # them; the tokenizer's "longer than 256" warning is expected there.
        from transformers.utils import logging as hf_logging

        hf_logging.set_verbosity_error()

    def count_tokens(self, text: str) -> int:
        """Word pieces the model reads for `text`, including [CLS] and [SEP]."""
        return len(self._model.tokenizer(text, add_special_tokens=True, truncation=False)["input_ids"])

    def embed(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        vectors = self._model.encode(
            texts, batch_size=batch_size, normalize_embeddings=True, show_progress_bar=False,
        )
        result = [[float(x) for x in v] for v in vectors]
        for i, vector in enumerate(result):
            validate_vector(vector, where=f"passage {i}")
        return result


def validate_vector(vector: list[float], *, where: str = "vector") -> None:
    """A usable unit-length vector of the expected size, or EmbeddingError."""
    if len(vector) != EMBEDDING_DIM:
        raise EmbeddingError(f"{where}: {len(vector)} dimensions, expected {EMBEDDING_DIM}")
    if not all(math.isfinite(x) for x in vector):
        raise EmbeddingError(f"{where}: contains NaN or infinity")
    norm = math.sqrt(sum(x * x for x in vector))
    if not 0.99 <= norm <= 1.01:
        raise EmbeddingError(f"{where}: norm {norm:.3f}, expected a normalised vector")
