path = r"D:\Project\sharada-user-section-backend\app\agents\report_agents.py"
with open(path, "r", encoding="utf-8") as f:
    text = f.read()

text = text.replace(
    "resolved_tickets = db.execute(text(\"SELECT COUNT(*) FROM tickets WHERE status = 'resolved'\")).scalar() or 0",
    "resolved_tickets = db.execute(text(\"SELECT COUNT(tickets.id) FROM tickets JOIN assets ON tickets.asset_id = assets.id WHERE assets.warehouse_id = :w AND tickets.status = 'resolved'\"), {'w': warehouse_id}).scalar() or 0"
)

text = text.replace(
    "closed_tickets   = db.execute(text(\"SELECT COUNT(*) FROM tickets WHERE status = 'closed'\")).scalar() or 0",
    "closed_tickets   = db.execute(text(\"SELECT COUNT(tickets.id) FROM tickets JOIN assets ON tickets.asset_id = assets.id WHERE assets.warehouse_id = :w AND tickets.status = 'closed'\"), {'w': warehouse_id}).scalar() or 0"
)

old_pdm = """    latest_preds = db.execute(text(\"\"\"
        SELECT
            asset_id, health_score, failure_probability, risk_level, predicted_days_until_maintenance
        FROM pdm_batch_predictions
        WHERE status = 'ok'
    \"\"\")).fetchall()"""

new_pdm = """    latest_preds = db.execute(text(\"\"\"
        SELECT
            p.asset_id, p.health_score, p.failure_probability, p.risk_level, p.predicted_days_until_maintenance
        FROM pdm_batch_predictions p
        JOIN assets a ON p.asset_id = a.id
        WHERE p.status = 'ok' AND a.warehouse_id = :w
    \"\"\"), {"w": warehouse_id}).fetchall()"""

text = text.replace(old_pdm, new_pdm)

with open(path, "w", encoding="utf-8") as f:
    f.write(text)
print("Finished replacements 2.")
