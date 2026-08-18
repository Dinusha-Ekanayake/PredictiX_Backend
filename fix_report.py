path = r"D:\Project\sharada-user-section-backend\app\agents\report_agents.py"
with open(path, "r", encoding="utf-8") as f:
    text = f.read()

old_block = """    kb_store = get_kb_store()
    # Inject the FULL source-grouped KB. The curated corpus (26 chunks spanning
    # statutory law, OEM schedules, ISO 55000/55001, SMRP, FMEA and Colombo climate)
    # is small enough to inject completely, guaranteeing no standard is dropped by
    # top-k retrieval \x97 the strongest lever for grounded, high-quality report prose.
    kb_full_context = kb_store.build_full_kb_context()"""

new_block = """    kb_store = get_kb_store()
    
    # Dynamically build a query based on the warehouse's top issues to pull relevant RAG context
    top_shap = ctx.get("top_shap_features", [])
    shap_names = [s["feature"] for s in top_shap]
    query_str = "warehouse maintenance safety standards " + " ".join(shap_names)
    
    # Retrieve top 12 most relevant chunks from the pgvector database
    relevant_chunks = kb_store.retrieve(query_str, top_k=12)
    
    lines = [
        "=" * 64,
        "PREDICTIX KNOWLEDGE BASE - RETRIEVED MAINTENANCE STANDARDS",
        "=" * 64,
    ]
    for chunk in relevant_chunks:
        source = chunk['tags'][1] if chunk.get('tags') and len(chunk['tags']) > 1 else chunk['id']
        lines.append(f"\\n[Source: {source}]")
        lines.append(chunk['text'])
        
    kb_full_context = "\\n".join(lines)"""

if "kb_store.build_full_kb_context()" in text:
    import re
    # We use regex to handle different encodings of the hyphen/emdash
    text = re.sub(
        r"    kb_store = get_kb_store\(\).*?kb_full_context = kb_store\.build_full_kb_context\(\)",
        new_block,
        text,
        flags=re.DOTALL
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print("Replaced successfully.")
else:
    print("Not found.")
