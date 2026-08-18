path = r"D:\Project\sharada-user-section-backend\app\agents\report_agents.py"
with open(path, "r", encoding="utf-8") as f:
    text = f.read()

text = text.replace(
    "_latest_evt = db.query(func.max(MaintenanceEvent.performed_at)).scalar()",
    "_latest_evt = db.query(func.max(MaintenanceEvent.performed_at)).join(Asset).filter(Asset.warehouse_id == warehouse_id).scalar()"
)

with open(path, "w", encoding="utf-8") as f:
    f.write(text)
print("Fixed _latest_evt")
