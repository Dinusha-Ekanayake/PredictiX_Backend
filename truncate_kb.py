path = r"D:\Project\sharada-user-section-backend\app\kb\kb_documents.py"
with open(path, "r", encoding="utf-8") as f:
    lines = f.readlines()

# Find the start of KB_DOCUMENTS
start_idx = -1
for i, line in enumerate(lines):
    if line.startswith("KB_DOCUMENTS: list[dict] = ["):
        start_idx = i
        break

if start_idx != -1:
    # Truncate
    new_lines = lines[:start_idx]
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
    print("Successfully removed KB_DOCUMENTS")
else:
    print("Could not find KB_DOCUMENTS")
