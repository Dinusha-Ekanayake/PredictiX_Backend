path = r"D:\Project\sharada-user-section-backend\app\agents\report_agents.py"
with open(path, "r", encoding="utf-8") as f:
    text = f.read()

# Fix vendor_rows query
text = text.replace(
    """      vendor_rows = db.execute(text(\"\"\"
          SELECT vendor_name,
                 COUNT(*)::int                            AS event_count,
                 COALESCE(SUM(cost_amount), 0)::numeric  AS total_cost
          FROM maintenance_events
          WHERE vendor_name IS NOT NULL AND vendor_name <> ''
            AND performed_at >= :cutoff
          GROUP BY vendor_name
          ORDER BY event_count DESC
          LIMIT 5
      \"\"\"), {"cutoff": period_start}).fetchall()""",
    """      vendor_rows = db.execute(text(\"\"\"
          SELECT m.vendor_name,
                 COUNT(m.id)::int                            AS event_count,
                 COALESCE(SUM(m.cost_amount), 0)::numeric  AS total_cost
          FROM maintenance_events m
          JOIN assets a ON m.asset_id = a.id
          WHERE m.vendor_name IS NOT NULL AND m.vendor_name <> ''
            AND m.performed_at >= :cutoff
            AND a.warehouse_id = :w
          GROUP BY m.vendor_name
          ORDER BY event_count DESC
          LIMIT 5
      \"\"\"), {"cutoff": period_start, "w": warehouse_id}).fetchall()"""
)

with open(path, "w", encoding="utf-8") as f:
    f.write(text)
print("Replaced vendor_rows.")
