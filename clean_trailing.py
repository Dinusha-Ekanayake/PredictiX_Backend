path = r"D:\Project\sharada-user-section-backend\app\kb\kb_documents.py"
with open(path, "r", encoding="utf-8") as f:
    text = f.read()

# Find the start of the KB DOCUMENTS block header and truncate there
idx = text.find("# --------------------------------------------------------------------------------------------------\n# KB DOCUMENTS")
if idx != -1:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text[:idx].strip() + "\n")
    print("Cleaned trailing headers.")
else:
    print("Could not find trailing headers.")
