"""Command line for the knowledge-base pipeline.

    python -m app.kb.pipeline validate                 check kb/sources.yaml
    python -m app.kb.pipeline ingest --dry-run         fetch, extract, chunk, check; write nothing
    python -m app.kb.pipeline ingest                   full run for every active source
    python -m app.kb.pipeline ingest --only S01,S07    selected sources
    python -m app.kb.pipeline sync                     withdraw sources no longer active in the registry
    python -m app.kb.pipeline references               rebuild kb/REFERENCES.md and kb/references.bib
    python -m app.kb.pipeline status                   what is loaded now
    python -m app.kb.pipeline gaps --days 30           questions the knowledge base could not answer

Exit code is non-zero when any source fails, so CI can gate on it.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv


def _setup() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "sentence_transformers", "pypdf"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def cmd_validate(args) -> int:
    from app.kb.pipeline.registry import load_registry

    registry = load_registry()
    print(f"Registry v{registry.registry_version}: {len(registry.sources)} sources, "
          f"{len(registry.active)} active, {len(registry.excluded)} excluded")
    for s in registry.sources:
        scope = "network" if s.scope == "network" else ",".join(s.warehouses)
        print(f"  {s.id}  {s.status:<9} {s.jurisdiction:<3} {s.doc_type:<16} {scope:<8} "
              f"audience={','.join(s.audience):<22} {s.title[:60]}")
    return 0


def cmd_ingest(args) -> int:
    from app.db.session import SessionLocal
    from app.kb.pipeline.archive import SupabaseArchive
    from app.kb.pipeline.config import REPORT_DIR
    from app.kb.pipeline.embedding import Embedder
    from app.kb.pipeline.ingest import SourceReport, ingest_source
    from app.kb.pipeline.registry import load_registry

    registry = load_registry()
    wanted = {s.strip() for s in args.only.split(",")} if args.only else None
    sources = [s for s in registry.active if wanted is None or s.id in wanted]
    if wanted and wanted - {s.id for s in sources}:
        print(f"Unknown or inactive source ids: {sorted(wanted - {s.id for s in sources})}")
        return 2

    embedder = Embedder()
    archive = None if args.dry_run else SupabaseArchive()
    reports: list[SourceReport] = []
    for source in sources:
        try:
            report = ingest_source(source, embedder=embedder, db_factory=SessionLocal, archive=archive,
                                   dry_run=args.dry_run, force=args.force, refresh=args.refresh)
        except Exception as exc:  # one bad source must not stop the others
            logging.getLogger("predictix.kb").error("%s failed: %s", source.id, exc)
            report = SourceReport(source.id, outcome="failed", detail=f"{type(exc).__name__}: {exc}")
        reports.append(report)
        print(f"  {report.source_id}: {report.outcome:<9} chunks={report.chunks:<4} "
              f"pages={report.pages:<4} sections={report.sections:<4} tokens(max/mean)="
              f"{report.max_tokens}/{report.mean_tokens} dupes={report.duplicates_removed} {report.detail}")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = REPORT_DIR / f"ingest-{stamp}{'-dry-run' if args.dry_run else ''}.json"
    path.write_text(json.dumps([r.__dict__ for r in reports], indent=2, default=str), encoding="utf-8")
    failed = [r.source_id for r in reports if r.outcome == "failed"]
    print(f"\nReport: {path}\n{len(reports) - len(failed)} ok, {len(failed)} failed {failed or ''}")
    return 1 if failed else 0


def cmd_sync(args) -> int:
    from app.db.session import SessionLocal
    from app.kb.pipeline import store
    from app.kb.pipeline.registry import load_registry

    registry = load_registry()
    wanted = {s.id: s.status for s in registry.sources}
    with SessionLocal() as db:
        changed = []
        for row in store.stored_sources(db):
            target = wanted.get(row["id"], "withdrawn")
            if store.set_status(db, row["id"], target):
                changed.append(f"{row['id']} -> {target}")
        db.commit()
    print("Status changes:", changed or "none")
    return 0


def cmd_references(args) -> int:
    from app.db.session import SessionLocal
    from app.kb.pipeline import store
    from app.kb.pipeline.config import REFERENCES_BIB, REFERENCES_MD
    from app.kb.pipeline.references import render_bibtex, render_markdown
    from app.kb.pipeline.registry import load_registry

    registry = load_registry()
    with SessionLocal() as db:
        state = {row["id"]: row for row in store.stored_sources(db)}
    REFERENCES_MD.write_text(render_markdown(registry, state), encoding="utf-8")
    REFERENCES_BIB.write_text(render_bibtex(registry, state), encoding="utf-8")
    print(f"Wrote {REFERENCES_MD} and {REFERENCES_BIB}")
    return 0


def cmd_status(args) -> int:
    from app.db.session import SessionLocal
    from app.kb.pipeline import store

    with SessionLocal() as db:
        rows = store.stored_sources(db)
    for r in rows:
        print(f"  {r['id']}  {r['status']:<9} v{r['version']}  chunks={r['chunk_count']:<4} "
              f"sha256={(r['sha256'] or '')[:12]}  ingested={r['ingested_at']}")
    print(f"{len(rows)} sources, {sum(r['chunk_count'] for r in rows)} passages")
    return 0


def cmd_gaps(args) -> int:
    from app.db.session import SessionLocal
    from app.kb.gaps import gap_report
    from app.kb.pipeline.config import REPORT_DIR

    with SessionLocal() as db:
        report = gap_report(db, days=args.days)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / f"gaps-{datetime.now(timezone.utc).strftime('%Y%m%d')}.md"
    path.write_text(report, encoding="utf-8")
    print(report)
    print(f"Saved to {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.kb.pipeline", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    ingest = sub.add_parser("ingest")
    ingest.add_argument("--only", help="comma-separated source ids")
    ingest.add_argument("--dry-run", action="store_true", help="fetch, extract, chunk and check; write nothing")
    ingest.add_argument("--force", action="store_true", help="re-load even if the fingerprint is unchanged")
    ingest.add_argument("--refresh", action="store_true", help="download again instead of using the cache")
    sub.add_parser("sync")
    sub.add_parser("references")
    sub.add_parser("status")
    gaps = sub.add_parser("gaps")
    gaps.add_argument("--days", type=int, default=30)
    args = parser.parse_args(argv)
    _setup()
    return {"validate": cmd_validate, "ingest": cmd_ingest, "sync": cmd_sync,
            "references": cmd_references, "status": cmd_status, "gaps": cmd_gaps}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
