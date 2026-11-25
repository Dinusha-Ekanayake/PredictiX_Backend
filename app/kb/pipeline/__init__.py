"""Knowledge-base ingestion pipeline.

Stages, each in its own module:

    registry   load and validate kb/sources.yaml (what may be loaded)
    fetch      download each source, verify its type, checksum it
    archive    keep the original bytes and the processed text in private storage
    extract    turn PDF or eCFR XML into text blocks with page and section
    chunking   split blocks into passages that fit the embedding model
    embedding  turn passages into normalised vectors
    store      replace a source's rows in kb_sources / kb_chunks atomically
    references generate the reference list from the registry and ingest state

Run it with ``python -m app.kb.pipeline --help``. kb/README.md explains the
flow end to end.
"""
