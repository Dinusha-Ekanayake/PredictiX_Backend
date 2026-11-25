"""Pipeline settings. Values that change retrieval behaviour live here, in one place."""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
KB_DIR = REPO_ROOT / "kb"
REGISTRY_PATH = KB_DIR / "sources.yaml"
CACHE_DIR = KB_DIR / ".cache"
REPORT_DIR = KB_DIR / "reports"
REFERENCES_MD = KB_DIR / "REFERENCES.md"
REFERENCES_BIB = KB_DIR / "references.bib"

#: Bump when extraction or chunking logic changes, so every source is
#: re-processed on the next run even though its file has not changed.
PIPELINE_VERSION = "1"

#: Private Supabase Storage bucket for originals (raw/) and processed text (processed/).
STORAGE_BUCKET = "kb-sources"

# Embedding model. Imported from the query-side module so passages and queries
# can never be embedded with different models.
from app.chatbot.knowledge_service import EMBEDDING_DIM, EMBEDDING_MODEL  # noqa: E402

# all-MiniLM-L6-v2 reads at most 256 word pieces and silently drops the rest,
# so every embedded passage (heading line + text) stays under that limit.
MODEL_MAX_TOKENS = 256
MAX_EMBED_TOKENS = 240
TARGET_CHUNK_TOKENS = 180
OVERLAP_TOKENS = 30
MIN_CHUNK_TOKENS = 25
MAX_HEADER_TOKENS = 40

# Fetching.
USER_AGENT = "PredictiX-KB-Ingest/1.0 (knowledge base builder)"
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024
FETCH_RETRIES = 3
FETCH_BACKOFF_SECONDS = (5, 15)
FETCH_TIMEOUT_SECONDS = 60

# Quality gates applied to each source before anything is written.
MIN_SOURCE_CHARS = 500
MIN_CHARS_PER_PDF_PAGE = 200      # lower usually means a scanned (image-only) PDF
MAX_DUPLICATE_CHUNK_RATIO = 0.30
