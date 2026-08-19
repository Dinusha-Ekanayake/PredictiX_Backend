path = r"D:\Project\sharada-user-section-backend\app\agents\report_agents.py"
with open(path, "r", encoding="utf-8") as f:
    text = f.read()

# Fix estimated_cost_lkr query
text = text.replace(
    """      cost_row = db.execute(text(\"\"\"
          SELECT
              COALESCE(SUM(estimated_cost_lkr), 0) AS total_cost,
              COALESCE(AVG(estimated_cost_lkr), 0) AS avg_cost,
              COALESCE(MIN(min_cost_lkr), 0)       AS min_cost,
              COALESCE(MAX(max_cost_lkr), 0)       AS max_cost
          FROM pdm_batch_predictions
          WHERE status = 'ok'
      \"\"\")).fetchone()""",
    """      cost_row = db.execute(text(\"\"\"
          SELECT
              COALESCE(SUM(p.estimated_cost_lkr), 0) AS total_cost,
              COALESCE(AVG(p.estimated_cost_lkr), 0) AS avg_cost,
              COALESCE(MIN(p.min_cost_lkr), 0)       AS min_cost,
              COALESCE(MAX(p.max_cost_lkr), 0)       AS max_cost
          FROM pdm_batch_predictions p
          JOIN assets a ON p.asset_id = a.id
          WHERE p.status = 'ok' AND a.warehouse_id = :w
      \"\"\"), {"w": warehouse_id}).fetchone()"""
)

with open(path, "w", encoding="utf-8") as f:
    f.write(text)
print("Replaced estimated cost query.")
