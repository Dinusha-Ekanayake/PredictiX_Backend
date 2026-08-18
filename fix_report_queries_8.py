path = r"D:\Project\sharada-user-section-backend\app\agents\report_agents.py"
with open(path, "r", encoding="utf-8") as f:
    text = f.read()

# Fix critical assets query
old_sql = """        SELECT
            a.asset_code, a.asset_name, a.model, a.make, a.vehicle_type, a.status,
            p.health_score, p.failure_probability, p.risk_level, p.predicted_days_until_maintenance,
            p.top_explanations
        FROM pdm_batch_predictions p
        JOIN assets a ON a.id = p.asset_id
        WHERE p.status = 'ok'
        ORDER BY CASE WHEN a.asset_code LIKE 'SIM-%' THEN 0 ELSE 1 END, p.health_score ASC
        LIMIT 25
    \"\"\")).fetchall()"""

new_sql = """        SELECT
            a.asset_code, a.asset_name, a.model, a.make, a.vehicle_type, a.status,
            p.health_score, p.failure_probability, p.risk_level, p.predicted_days_until_maintenance,
            p.top_explanations
        FROM pdm_batch_predictions p
        JOIN assets a ON a.id = p.asset_id
        WHERE p.status = 'ok' AND a.warehouse_id = :w
        ORDER BY CASE WHEN a.asset_code LIKE 'SIM-%' THEN 0 ELSE 1 END, p.health_score ASC
        LIMIT 25
    \"\"\"), {"w": warehouse_id}).fetchall()"""

text = text.replace(old_sql, new_sql)

with open(path, "w", encoding="utf-8") as f:
    f.write(text)
print("Replaced missed query.")
