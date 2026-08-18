path = r"D:\Project\sharada-user-section-backend\app\agents\report_agents.py"
with open(path, "r", encoding="utf-8") as f:
    text = f.read()

# fix high_priority_active
text = text.replace(
    "text(\"SELECT COUNT(*) FROM tickets WHERE status NOT IN ('closed','resolved') AND (priority = 'high' OR final_priority = 'high')\")",
    "text(\"SELECT COUNT(t.id) FROM tickets t JOIN assets a ON t.asset_id = a.id WHERE t.status NOT IN ('closed','resolved') AND (t.priority = 'high' OR t.final_priority = 'high') AND a.warehouse_id = :w\"), {'w': warehouse_id}"
)

# fix critical_rows parameters
text = text.replace(
    "WHERE p.status = 'ok' AND p.health_score < 50 AND a.warehouse_id = :w\n        ORDER BY p.health_score ASC\n        LIMIT 25\")\n    ).fetchall()",
    "WHERE p.status = 'ok' AND p.health_score < 50 AND a.warehouse_id = :w\n        ORDER BY p.health_score ASC\n        LIMIT 25\"), {'w': warehouse_id}\n    ).fetchall()"
)

# fix cost_row
text = text.replace(
    "WHERE m.performed_at >= :start AND m.performed_at < :end AND m.status != 'cancelled' AND a.warehouse_id = :w\"),\n            {\"start\": period_start, \"end\": period_end}\n        ).fetchone()",
    "WHERE m.performed_at >= :start AND m.performed_at < :end AND m.status != 'cancelled' AND a.warehouse_id = :w\"),\n            {\"start\": period_start, \"end\": period_end, \"w\": warehouse_id}\n        ).fetchone()"
)

# fix warranty_expiring_90d
text = text.replace(
    "          AND warehouse_id = :w\"),\n            {\"now\": now, \"plus90\": now + timedelta(days=90)}\n        ).scalar() or 0",
    "          AND warehouse_id = :w\"),\n            {\"now\": now, \"plus90\": now + timedelta(days=90), \"w\": warehouse_id}\n        ).scalar() or 0"
)

# fix comp_row
text = text.replace(
    "WHERE m.performed_at >= :start AND m.performed_at < :end AND m.status != 'cancelled' AND a.warehouse_id = :w\"),\n            {\"start\": period_start, \"end\": period_end}\n        ).scalar() or 0",
    "WHERE m.performed_at >= :start AND m.performed_at < :end AND m.status != 'cancelled' AND a.warehouse_id = :w\"),\n            {\"start\": period_start, \"end\": period_end, \"w\": warehouse_id}\n        ).scalar() or 0"
)

# fix vendor_rows
text = text.replace(
    "        LIMIT 5\"),\n            {\"start\": period_start}\n        ).fetchall()",
    "        LIMIT 5\"),\n            {\"start\": period_start, \"w\": warehouse_id}\n        ).fetchall()"
)

# fix mttr_row
text = text.replace(
    "WHERE t.status = 'resolved' AND t.resolved_at IS NOT NULL AND a.warehouse_id = :w\")\n        ).scalar()",
    "WHERE t.status = 'resolved' AND t.resolved_at IS NOT NULL AND a.warehouse_id = :w\"), {'w': warehouse_id}\n        ).scalar()"
)

# fix prio_rows
text = text.replace(
    "        GROUP BY t.final_priority\")\n        ).fetchall()",
    "        GROUP BY t.final_priority\"), {'w': warehouse_id}\n        ).fetchall()"
)


with open(path, "w", encoding="utf-8") as f:
    f.write(text)
print("Finished replacements 4.")
