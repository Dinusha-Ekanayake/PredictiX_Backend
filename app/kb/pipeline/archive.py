"""Keep the original files and the processed text in private storage.

Layout in the private bucket (see config.STORAGE_BUCKET):

    raw/<source id>/<sha256>.<ext>          original bytes, never overwritten
    processed/<source id>/<fingerprint>.json extracted blocks and passages

The raw layer is immutable: a path is written once, and a later run that
finds it already present only confirms it. Because the file name is its own
checksum, any copy can be verified with a standard sha256 tool.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Protocol

from app.kb.pipeline.config import STORAGE_BUCKET
from app.kb.pipeline.fetch import Artifact

log = logging.getLogger("predictix.kb.archive")


class ArchiveError(RuntimeError):
    """The original could not be preserved; nothing is loaded without it."""


class Archive(Protocol):
    def read(self, path: str) -> bytes: ...
    def put_raw(self, source_id: str, artifact: Artifact) -> str: ...
    def put_processed(self, source_id: str, fingerprint: str, payload: dict[str, Any]) -> str: ...


def raw_path(source_id: str, artifact: Artifact) -> str:
    return f"raw/{source_id}/{artifact.sha256}.{artifact.extension}"


def processed_path(source_id: str, fingerprint: str) -> str:
    return f"processed/{source_id}/{fingerprint}.json"


class SupabaseArchive:
    """Archive backed by a private Supabase Storage bucket (service-role key)."""

    def __init__(self) -> None:
        url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        if not url or not key:
            raise ArchiveError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required to archive sources")
        from supabase import create_client

        self._client = create_client(url, key)
        self._ensure_private_bucket()

    def _ensure_private_bucket(self) -> None:
        buckets = {b.name: b for b in self._client.storage.list_buckets()}
        bucket = buckets.get(STORAGE_BUCKET)
        if bucket is None:
            self._client.storage.create_bucket(STORAGE_BUCKET, options={"public": False})
            log.info("Created private storage bucket %s", STORAGE_BUCKET)
        elif getattr(bucket, "public", False):
            raise ArchiveError(f"bucket {STORAGE_BUCKET} is public; originals must be kept private")

    def _exists(self, path: str) -> bool:
        folder, _, name = path.rpartition("/")
        entries = self._client.storage.from_(STORAGE_BUCKET).list(folder, {"search": name})
        return any(e.get("name") == name for e in entries or [])

    def _upload(self, path: str, data: bytes, content_type: str) -> str:
        if self._exists(path):
            return path
        try:
            self._client.storage.from_(STORAGE_BUCKET).upload(
                path, data, {"content-type": content_type, "upsert": "false"},
            )
        except Exception as exc:
            raise ArchiveError(f"could not store {path}: {exc}") from exc
        return path

    def read(self, path: str) -> bytes:
        """Bytes of a file in the private bucket (e.g. an uploaded internal document)."""
        return self._client.storage.from_(STORAGE_BUCKET).download(path)

    def put_raw(self, source_id: str, artifact: Artifact) -> str:
        return self._upload(raw_path(source_id, artifact), artifact.content, artifact.content_type)

    def put_processed(self, source_id: str, fingerprint: str, payload: dict[str, Any]) -> str:
        data = json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8")
        return self._upload(processed_path(source_id, fingerprint), data, "application/json")
