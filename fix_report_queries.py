import re

path = r"D:\Project\sharada-user-section-backend\app\agents\report_agents.py"
with open(path, "r", encoding="utf-8") as f:
    text = f.read()

# Asset Queries
text = text.replace(
    "asset_category_rows = db.query(Asset.category, func.count(Asset.id)).group_by(Asset.category).all()",
    "asset_category_rows = db.query(Asset.category, func.count(Asset.id)).filter(Asset.warehouse_id == warehouse_id).group_by(Asset.category).all()"
)
text = text.replace(
    "avg_vehicle_age = db.query(func.avg(Asset.vehicle_age_years)).scalar() or 0",
    "avg_vehicle_age = db.query(func.avg(Asset.vehicle_age_years)).filter(Asset.warehouse_id == warehouse_id).scalar() or 0"
)

# pdm_batch_predictions
text = re.sub(
    r"pdm_rows = db\.query\(PdmBatchPrediction\)\.all\(\)",
    r"pdm_rows = db.query(PdmBatchPrediction).join(Asset).filter(Asset.warehouse_id == warehouse_id).all()",
    text
)

# MaintenanceEvent Queries
text = re.sub(
    r"m_cost = db\.query\(func\.sum\(MaintenanceEvent\.cost_amount\)\)\.filter\(",
    r"m_cost = db.query(func.sum(MaintenanceEvent.cost_amount)).join(Asset).filter(\n            Asset.warehouse_id == warehouse_id,",
    text
)
text = re.sub(
    r"m_count = db\.query\(func\.count\(MaintenanceEvent\.id\)\)\.filter\(",
    r"m_count = db.query(func.count(MaintenanceEvent.id)).join(Asset).filter(\n            Asset.warehouse_id == warehouse_id,",
    text
)
text = re.sub(
    r"avg_downtime = db\.query\(func\.avg\(MaintenanceEvent\.downtime_hours\)\)\.filter\(",
    r"avg_downtime = db.query(func.avg(MaintenanceEvent.downtime_hours)).join(Asset).filter(\n        Asset.warehouse_id == warehouse_id,",
    text
)
text = re.sub(
    r"maintenance_type_rows = db\.query\(\s*MaintenanceEvent\.event_type, func\.count\(MaintenanceEvent\.id\)\s*\)\.filter\(",
    r"maintenance_type_rows = db.query(\n        MaintenanceEvent.event_type, func.count(MaintenanceEvent.id)\n    ).join(Asset).filter(\n        Asset.warehouse_id == warehouse_id,",
    text
)

# Ticket Queries
text = text.replace(
    "total_tickets    = db.query(func.count(Ticket.id)).scalar() or 0",
    "total_tickets    = db.query(func.count(Ticket.id)).join(Asset).filter(Asset.warehouse_id == warehouse_id).scalar() or 0"
)
text = text.replace(
    "open_tickets     = db.execute(text(\"SELECT COUNT(*) FROM tickets WHERE status = 'open'\")).scalar() or 0",
    "open_tickets     = db.execute(text(\"SELECT COUNT(tickets.id) FROM tickets JOIN assets ON tickets.asset_id = assets.id WHERE assets.warehouse_id = :w AND tickets.status = 'open'\"), {'w': warehouse_id}).scalar() or 0"
)
text = text.replace(
    "in_progress      = db.execute(text(\"SELECT COUNT(*) FROM tickets WHERE status = 'in_progress'\")).scalar() or 0",
    "in_progress      = db.execute(text(\"SELECT COUNT(tickets.id) FROM tickets JOIN assets ON tickets.asset_id = assets.id WHERE assets.warehouse_id = :w AND tickets.status = 'in_progress'\"), {'w': warehouse_id}).scalar() or 0"
)
text = text.replace(
    "priority_rows = db.query(Ticket.priority, func.count(Ticket.id)).group_by(Ticket.priority).all()",
    "priority_rows = db.query(Ticket.priority, func.count(Ticket.id)).join(Asset).filter(Asset.warehouse_id == warehouse_id).group_by(Ticket.priority).all()"
)
text = text.replace(
    "final_priority_rows = db.query(Ticket.final_priority, func.count(Ticket.id)).group_by(Ticket.final_priority).all()",
    "final_priority_rows = db.query(Ticket.final_priority, func.count(Ticket.id)).join(Asset).filter(Asset.warehouse_id == warehouse_id).group_by(Ticket.final_priority).all()"
)
text = text.replace(
    "category_rows = db.query(Ticket.final_category, func.count(Ticket.id)).group_by(Ticket.final_category).all()",
    "category_rows = db.query(Ticket.final_category, func.count(Ticket.id)).join(Asset).filter(Asset.warehouse_id == warehouse_id).group_by(Ticket.final_category).all()"
)
text = re.sub(
    r"count = db\.query\(func\.count\(Ticket\.id\)\)\.filter\(",
    r"count = db.query(func.count(Ticket.id)).join(Asset).filter(\n                Asset.warehouse_id == warehouse_id,",
    text
)

# User Queries
text = text.replace(
    "total_users    = db.query(func.count(Profile.id)).scalar() or 0",
    "total_users    = db.query(func.count(Profile.id)).filter(Profile.warehouse_id == warehouse_id).scalar() or 0"
)
text = text.replace(
    "active_users   = db.execute(text(\"SELECT COUNT(*) FROM profiles WHERE status = 'active'\")).scalar() or 0",
    "active_users   = db.execute(text(\"SELECT COUNT(*) FROM profiles WHERE warehouse_id = :w AND status = 'active'\"), {'w': warehouse_id}).scalar() or 0"
)

with open(path, "w", encoding="utf-8") as f:
    f.write(text)
print("Finished replacements.")
