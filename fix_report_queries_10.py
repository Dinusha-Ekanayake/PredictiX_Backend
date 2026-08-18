path = r"D:\Project\sharada-user-section-backend\app\agents\report_agents.py"
with open(path, "r", encoding="utf-8") as f:
    text = f.read()

text = text.replace(
    "age_rows = db.query(Asset.manufacture_year, func.count(Asset.id))\\\n            .filter(Asset.manufacture_year.isnot(None)).group_by(Asset.manufacture_year).all()",
    "age_rows = db.query(Asset.manufacture_year, func.count(Asset.id))\\\n            .filter(Asset.manufacture_year.isnot(None), Asset.warehouse_id == warehouse_id).group_by(Asset.manufacture_year).all()"
)

with open(path, "w", encoding="utf-8") as f:
    f.write(text)
print("Fixed age_rows")
