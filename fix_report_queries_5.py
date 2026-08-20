path = r"D:\Project\sharada-user-section-backend\app\agents\report_agents.py"
with open(path, "r", encoding="utf-8") as f:
    text = f.read()

text = text.replace(
    """    rows = db.execute(text(\"\"\"
        SELECT top_explanations
        FROM pdm_batch_predictions
        WHERE status = 'ok' AND health_score < 60
        LIMIT 50
    \"\"\")).fetchall()""",
    """    rows = db.execute(text(\"\"\"
        SELECT p.top_explanations
        FROM pdm_batch_predictions p
        JOIN assets a ON p.asset_id = a.id
        WHERE p.status = 'ok' AND p.health_score < 60 AND a.warehouse_id = :w
        LIMIT 50
    \"\"\"), {"w": warehouse_id}).fetchall()"""
)

with open(path, "w", encoding="utf-8") as f:
    f.write(text)
print("Finished final replacement.")
