"""ONNX query embeddings: same vectors as sentence-transformers, and used when it is absent."""
from __future__ import annotations

import importlib.util
import math

import numpy as np
import pytest

import app.chatbot.knowledge_service as ks
from app.chatbot import onnx_embedder

SENTENCES = [
    "How often should forklift brakes be inspected?",
    "Tyre pressure check before a long haul",
    "කොළඹ ගබඩාවේ නඩත්තු කාලසටහන",  # Sinhala: maintenance schedule at the Colombo warehouse
    "x",
    # Longer than the model's 256-token window, so truncation must match too.
    "Daily pre-use inspection covers forks, chains, mast, hydraulics and lights. " * 30,
]


def test_pooling_averages_only_real_tokens_and_normalises():
    hidden = np.array([[[3.0, 4.0], [100.0, 100.0]]], dtype=np.float32)  # second token is padding
    vector = onnx_embedder.pool(hidden, np.array([[1, 0]]))
    assert vector == pytest.approx([0.6, 0.8])
    assert math.isclose(sum(x * x for x in vector), 1.0, rel_tol=1e-6)


def test_embed_text_uses_onnx_when_sentence_transformers_is_absent(monkeypatch):
    fake = type("Fake", (), {"encode": lambda self, text: [1.0] + [0.0] * 383})()
    monkeypatch.setattr(ks, "_get_local_model", lambda: None)
    monkeypatch.setattr(ks, "_get_onnx_model", lambda: fake)
    monkeypatch.setattr(ks, "_embed_hosted", lambda v: pytest.fail("hosted endpoint must not be called"))
    assert ks.embed_text("brakes")[0] == 1.0


def test_embed_text_falls_back_to_the_hosted_endpoint_last(monkeypatch):
    monkeypatch.setattr(ks, "_get_local_model", lambda: None)
    monkeypatch.setattr(ks, "_get_onnx_model", lambda: None)
    monkeypatch.setattr(ks, "_embed_hosted", lambda v: [0.5] * 384)
    assert ks.embed_text("brakes") == [0.5] * 384


@pytest.fixture(scope="module")
def onnx_model():
    try:
        return onnx_embedder.load()
    except Exception as exc:  # noqa: BLE001 - no onnxruntime, or no cached model and no network
        pytest.skip(f"ONNX model not available: {exc}")


def test_onnx_vectors_are_unit_length_and_384_wide(onnx_model):
    for sentence in SENTENCES:
        vector = onnx_model.encode(sentence)
        assert len(vector) == ks.EMBEDDING_DIM
        assert math.isclose(sum(x * x for x in vector), 1.0, rel_tol=1e-5)


@pytest.mark.skipif(importlib.util.find_spec("sentence_transformers") is None,
                    reason="reference model not installed (server install)")
def test_onnx_matches_sentence_transformers(onnx_model):
    reference = ks._get_local_model()
    if reference is None:
        pytest.skip("sentence-transformers model not cached")
    for sentence in SENTENCES:
        expected = reference.encode(sentence, normalize_embeddings=True, show_progress_bar=False)
        actual = np.array(onnx_model.encode(sentence))
        assert float(np.dot(expected, actual)) >= 0.9999, sentence[:40]
