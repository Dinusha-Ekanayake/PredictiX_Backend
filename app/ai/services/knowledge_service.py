import logging
import os
import requests
from app.db.supabase_client import supabase

log = logging.getLogger("predictix.knowledge")

# Serverless inference moved behind the Inference Providers router; the legacy
# ``api-inference.huggingface.co`` host was retired and no longer resolves at
# all (DNS getaddrinfo failure), so a deployment still carrying the old value in
# HF_INFERENCE_API_URL failed every knowledge lookup — silently, because the
# handler below returns an empty list on error and the chatbot answers without
# its knowledge base rather than reporting that RAG was unavailable.
_EMBEDDING_REPO = "sentence-transformers/all-MiniLM-L6-v2"
# The ``/pipeline/feature-extraction`` suffix is required, not decorative: this
# repo's default pipeline on the router is sentence-similarity, which rejects
# a bare {"inputs": [...]} body with "SentenceSimilarityPipeline.__call__()
# missing 1 required positional argument: 'sentences'". Naming the pipeline
# returns the (1, 384) embedding this function expects to index with [0].
_DEFAULT_EMBEDDING_URL = (
    f"https://router.huggingface.co/hf-inference/models/{_EMBEDDING_REPO}"
    "/pipeline/feature-extraction"
)
_RETIRED_HOST = "api-inference.huggingface.co"


def _embedding_url() -> str:
    """Resolve the embedding endpoint, ignoring a retired configured host.

    The env var is still honoured so the endpoint stays deployment-controlled,
    but a value pointing at the dead host is worse than no value at all — it
    guarantees failure — so it is replaced rather than used.
    """
    configured = os.getenv("HF_INFERENCE_API_URL")
    if not configured:
        return _DEFAULT_EMBEDDING_URL
    if _RETIRED_HOST in configured:
        log.warning(
            "HF_INFERENCE_API_URL points at the retired host %s; using %s "
            "instead. Update the environment variable to silence this.",
            _RETIRED_HOST, _DEFAULT_EMBEDDING_URL,
        )
        return _DEFAULT_EMBEDDING_URL
    return configured


def embed_text(text: str) -> list[float]:
    """Generate a 384-dim embedding vector for the given text.

    Uses the same HuggingFace Inference API endpoint as search_knowledge,
    so articles and queries are embedded in the same vector space.
    Raises on failure so the caller can decide whether to proceed without
    an embedding or abort.
    """
    api_url = _embedding_url()
    headers = {}
    if token := os.getenv("HF_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"

    response = requests.post(
        api_url, headers=headers,
        json={"inputs": [text[:2000]], "options": {"wait_for_model": True}},
        timeout=60,
    )
    if response.status_code != 200:
        raise RuntimeError(f"HF embedding API returned {response.status_code}: {response.text[:200]}")

    return response.json()[0]


def search_knowledge(query: str, match_count: int = 3) -> list:
    try:
        # Use Hugging Face Inference API instead of heavy local torch/transformers models
        api_url = _embedding_url()

        headers = {}
        if token := os.getenv("HF_TOKEN"):
            headers["Authorization"] = f"Bearer {token}"
            
        # wait_for_model can legitimately take a while on a cold HF endpoint,
        # but with no timeout at all a hanging endpoint blocked the calling
        # request (chat/report generation) indefinitely instead of failing
        # over to the empty-results path below.
        response = requests.post(
            api_url, headers=headers,
            json={"inputs": [query], "options": {"wait_for_model": True}},
            timeout=60,
        )
        if response.status_code != 200:
            log.warning("HF embedding API returned %s: %s",
                        response.status_code, response.text[:300])
            return []
            
        # The feature-extraction pipeline for sentence-transformers returns a 1D array per input
        embedding = response.json()[0]
        
        response = supabase.rpc("match_knowledge", {
            "query_embedding": embedding,
            "match_count": match_count
        }).execute()
        return response.data if response.data else []
    except Exception as e:
        # Deliberately non-fatal: the assistant can still answer from the
        # database tools without the knowledge base. Logged at error level so a
        # persistently dead embedding endpoint is visible in the logs rather
        # than only showing up as vaguer answers.
        log.error("Knowledge search failed (%s): %s", type(e).__name__, e)
        return []
