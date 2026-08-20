path = r"D:\Project\sharada-user-section-backend\app\agents\report_agents.py"
with open(path, "r", encoding="utf-8") as f:
    text = f.read()

import re

queries = re.findall(r"(db\.query[^\n]*\n(?:[ \t]+[^\n]*\n){0,3})", text)
execs = re.findall(r"(db\.execute[^\n]*\n(?:[ \t]+[^\n]*\n){0,3})", text)

for q in queries:
    if "warehouse_id" not in q and "asset_code" not in q and "AssetFailurePrediction" not in q and "ticket_id" not in q:
        print("POTENTIAL LEAK:", q.strip())
        
for e in execs:
    if "warehouse_id" not in e:
        print("POTENTIAL LEAK:", e.strip())

