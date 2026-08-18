import re

with open("D:/Project/sharada-user-section-backend/app/agents/report_agents.py", "r") as f:
    code = f.read()

# Replace db.query(func.count(Asset.id))
code = code.replace(
    "total_assets = db.query(func.count(Asset.id)).scalar() or 0",
    "total_assets = db.query(func.count(Asset.id)).filter(Asset.warehouse_id == warehouse_id if warehouse_id else True).scalar() or 0"
)

# Replace asset group queries
for q in ["Asset.status", "Asset.vehicle_type", "Asset.category"]:
    code = code.replace(
        f"db.query({q}, func.count(Asset.id)).group_by({q}).all()",
        f"db.query({q}, func.count(Asset.id)).filter(Asset.warehouse_id == warehouse_id if warehouse_id else True).group_by({q}).all()"
    )

code = code.replace(
    "avg_vehicle_age = db.query(func.avg(Asset.vehicle_age_years)).scalar() or 0",
    "avg_vehicle_age = db.query(func.avg(Asset.vehicle_age_years)).filter(Asset.warehouse_id == warehouse_id if warehouse_id else True).scalar() or 0"
)

with open("D:/Project/sharada-user-section-backend/app/agents/report_agents.py", "w") as f:
    f.write(code)
