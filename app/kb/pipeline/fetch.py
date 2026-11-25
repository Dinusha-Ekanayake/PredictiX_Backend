"""Download a source and prove it is what it claims to be.

A response is accepted only if it is HTTP 200, within the size limit and
starts with the file signature of the declared format; publishers sometimes
answer with an HTML error or bot-check page and a 200 status. Every accepted
download is checksummed (SHA-256) and cached under kb/.cache so a re-run does
not hit the publisher again unless asked to.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.kb.pipeline.config import (
    CACHE_DIR,
    FETCH_BACKOFF_SECONDS,
    FETCH_RETRIES,
    FETCH_TIMEOUT_SECONDS,
    MAX_DOWNLOAD_BYTES,
    USER_AGENT,
)
from app.kb.pipeline.registry import FetchSpec

log = logging.getLogger("predictix.kb.fetch")

_EXTENSIONS = {"pdf": "pdf", "ecfr_xml": "xml", "markdown": "md", "db_ticket_patterns": "json"}


class FetchError(RuntimeError):
    """The source could not be downloaded or is not the declared format."""


@dataclass(frozen=True)
class Artifact:
    url: str
    format: str
    content: bytes
    sha256: str
    retrieved_at: datetime

    @property
    def extension(self) -> str:
        return _EXTENSIONS[self.format]

    @property
    def content_type(self) -> str:
        return {"pdf": "application/pdf", "ecfr_xml": "application/xml",
                "markdown": "text/markdown"}.get(self.format, "application/json")


def looks_like(fmt: str, content: bytes) -> bool:
    """True when `content` starts with the signature of `fmt`."""
    head = content[:1024].lstrip()
    if fmt == "pdf":
        return content[:5] == b"%PDF-"
    if fmt == "ecfr_xml":
        return head.startswith(b"<?xml") or head.startswith(b"<DIV") or head.startswith(b"<ECFR")
    if fmt == "markdown":
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            return False
        return not head.lower().startswith((b"<!doctype", b"<html", b"%pdf"))
    return False


def _cache_paths(url: str) -> tuple[Path, Path]:
    key = hashlib.sha256(url.encode()).hexdigest()[:24]
    return CACHE_DIR / f"{key}.bin", CACHE_DIR / f"{key}.json"


def _from_cache(spec: FetchSpec) -> Artifact | None:
    data_path, meta_path = _cache_paths(spec.url)
    if not (data_path.exists() and meta_path.exists()):
        return None
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    content = data_path.read_bytes()
    if hashlib.sha256(content).hexdigest() != meta["sha256"]:
        log.warning("Cached copy of %s is corrupt; downloading again.", spec.url)
        return None
    return Artifact(spec.url, spec.format, content, meta["sha256"], datetime.fromisoformat(meta["retrieved_at"]))


def _to_cache(artifact: Artifact) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    data_path, meta_path = _cache_paths(artifact.url)
    data_path.write_bytes(artifact.content)
    meta_path.write_text(json.dumps({
        "url": artifact.url, "sha256": artifact.sha256, "retrieved_at": artifact.retrieved_at.isoformat(),
    }), encoding="utf-8")


def _download(client: httpx.Client, spec: FetchSpec) -> Artifact:
    last_error = "no attempt made"
    for attempt in range(FETCH_RETRIES):
        if attempt:
            time.sleep(FETCH_BACKOFF_SECONDS[min(attempt - 1, len(FETCH_BACKOFF_SECONDS) - 1)])
        try:
            response = client.get(spec.url)
        except httpx.HTTPError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            continue
        if response.status_code in (401, 403, 404, 410):
            # The publisher refused or removed it; retrying will not help and
            # working around a refusal is not acceptable.
            raise FetchError(f"{spec.url} returned HTTP {response.status_code}")
        if response.status_code != 200:
            last_error = f"HTTP {response.status_code}"
            continue
        content = response.content
        if len(content) > MAX_DOWNLOAD_BYTES:
            raise FetchError(f"{spec.url} is larger than {MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB")
        if not looks_like(spec.format, content):
            # Often a rate-limit or bot-check page served with status 200.
            last_error = f"response is not a {spec.format} file"
            continue
        return Artifact(
            url=spec.url,
            format=spec.format,
            content=content,
            sha256=hashlib.sha256(content).hexdigest(),
            retrieved_at=datetime.now(timezone.utc),
        )
    raise FetchError(f"{spec.url}: {last_error} after {FETCH_RETRIES} attempts")


def fetch(spec: FetchSpec, *, refresh: bool = False, client: httpx.Client | None = None) -> Artifact:
    """The artifact for `spec`, from the cache unless `refresh` is set."""
    if not refresh:
        cached = _from_cache(spec)
        if cached is not None:
            return cached
    owns_client = client is None
    client = client or httpx.Client(
        headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=FETCH_TIMEOUT_SECONDS,
    )
    try:
        artifact = _download(client, spec)
    finally:
        if owns_client:
            client.close()
    _to_cache(artifact)
    log.info("Fetched %s (%d KB, sha256 %s)", spec.url, len(artifact.content) // 1024, artifact.sha256[:12])
    return artifact


def from_storage(spec: FetchSpec, archive) -> Artifact:
    """An uploaded internal document, read from the private bucket and verified."""
    try:
        content = archive.read(spec.storage_path)
    except Exception as exc:
        raise FetchError(f"could not read {spec.storage_path} from private storage: {exc}") from exc
    if len(content) > MAX_DOWNLOAD_BYTES:
        raise FetchError(f"{spec.storage_path} is larger than {MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB")
    if not looks_like(spec.format, content):
        raise FetchError(f"{spec.storage_path} is not a {spec.format} file")
    return Artifact(
        url=f"kb-sources:{spec.storage_path}",
        format=spec.format,
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
        retrieved_at=datetime.now(timezone.utc),
    )


def snapshot(spec: FetchSpec, db_factory) -> Artifact:
    """An internal source's content, built from the database at this moment.

    The snapshot plays the role of a downloaded file: it is checksummed,
    fingerprinted and archived, so the exact data behind every passage is kept.
    """
    from app.kb.pipeline.internal import INTERNAL_FORMATS

    with db_factory() as db:
        content = INTERNAL_FORMATS[spec.format][0](db)
    return Artifact(
        url=f"predictix-db:{spec.format}",
        format=spec.format,
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
        retrieved_at=datetime.now(timezone.utc),
    )


def combined_sha256(artifacts: list[Artifact]) -> str:
    """One checksum for a source made of several files, in registry order.

    A single-file source keeps that file's own checksum, so it can be checked
    against the archived original with any sha256 tool.
    """
    if len(artifacts) == 1:
        return artifacts[0].sha256
    digest = hashlib.sha256()
    for artifact in artifacts:
        digest.update(artifact.sha256.encode())
    return digest.hexdigest()
