path = r"D:\Project\sharada-user-section-backend\app\agents\report_agents.py"
with open(path, "r", encoding="utf-8") as f:
    text = f.read()

import re

queries = re.findall(r"(db\.query[^\n]*\n(?:[ \t]+[^\n]*\n){0,10})", text)
execs = re.findall(r"(db\.execute[^\n]*\n(?:[ \t]+[^\n]*\n){0,10})", text)

print("--- ORM QUERIES ---")
for q in queries:
    print(q.strip())
    print("-" * 40)
    
print("\n--- RAW SQL QUERIES ---")
for e in execs:
    print(e.strip())
    print("-" * 40)

