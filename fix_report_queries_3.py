path = r"D:\Project\sharada-user-section-backend\app\agents\report_agents.py"
with open(path, "r", encoding="utf-8") as f:
    text = f.read()

import re

# line 318: prediction_feature_importance via prediction_explanations
text = text.replace("""        SELECT pfi.feature_name, COUNT(pfi.id) as freq
        FROM prediction_feature_importance pfi
        JOIN prediction_explanations pe ON pfi.explanation_id = pe.id
        GROUP BY pfi.feature_name""",
        """        SELECT pfi.feature_name, COUNT(pfi.id) as freq
        FROM prediction_feature_importance pfi
        JOIN prediction_explanations pe ON pfi.explanation_id = pe.id
        JOIN assets a ON pe.asset_id = a.id
        WHERE a.warehouse_id = :w
        GROUP BY pfi.feature_name""")

# line 370: critical_rows
text = text.replace("""        SELECT
            a.asset_code, a.name, a.vehicle_type, a.status,
            p.health_score, p.failure_probability, p.risk_level, p.predicted_days_until_maintenance
        FROM assets a
        JOIN pdm_batch_predictions p ON a.id = p.asset_id
        WHERE p.status = 'ok' AND p.health_score < 50
        ORDER BY p.health_score ASC
        LIMIT 25""",
        """        SELECT
            a.asset_code, a.name, a.vehicle_type, a.status,
            p.health_score, p.failure_probability, p.risk_level, p.predicted_days_until_maintenance
        FROM assets a
        JOIN pdm_batch_predictions p ON a.id = p.asset_id
        WHERE p.status = 'ok' AND p.health_score < 50 AND a.warehouse_id = :w
        ORDER BY p.health_score ASC
        LIMIT 25""")

# line 408: cost_row
text = text.replace("""        SELECT SUM(cost_amount), COUNT(id)
        FROM maintenance_events
        WHERE performed_at >= :start AND performed_at < :end AND status != 'cancelled'""",
        """        SELECT SUM(cost_amount), COUNT(m.id)
        FROM maintenance_events m
        JOIN assets a ON m.asset_id = a.id
        WHERE m.performed_at >= :start AND m.performed_at < :end AND m.status != 'cancelled' AND a.warehouse_id = :w""")

# line 544: high_priority_active
text = text.replace("""        SELECT COUNT(*) FROM tickets WHERE priority = 'high' AND status IN ('open', 'in_progress')""",
        """        SELECT COUNT(t.id) FROM tickets t JOIN assets a ON t.asset_id = a.id WHERE t.priority = 'high' AND t.status IN ('open', 'in_progress') AND a.warehouse_id = :w""")

# line 552: admin_users
text = text.replace("admin_users    = db.execute(text(\"SELECT COUNT(*) FROM profiles WHERE role = 'admin'\")).scalar() or 0",
                    "admin_users    = db.execute(text(\"SELECT COUNT(*) FROM profiles WHERE role = 'admin' AND warehouse_id = :w\"), {'w': warehouse_id}).scalar() or 0")

# line 592: warranty_expiring_90d
text = text.replace("""        SELECT COUNT(*) FROM assets
        WHERE warranty_expiry IS NOT NULL
          AND warranty_expiry >= :now
          AND warranty_expiry <= :plus90""",
        """        SELECT COUNT(*) FROM assets
        WHERE warranty_expiry IS NOT NULL
          AND warranty_expiry >= :now
          AND warranty_expiry <= :plus90
          AND warehouse_id = :w""")

# line 610: comp_row
text = text.replace("""        SELECT AVG(cost_amount)
        FROM maintenance_events
        WHERE performed_at >= :start AND performed_at < :end AND status != 'cancelled'""",
        """        SELECT AVG(cost_amount)
        FROM maintenance_events m
        JOIN assets a ON m.asset_id = a.id
        WHERE m.performed_at >= :start AND m.performed_at < :end AND m.status != 'cancelled' AND a.warehouse_id = :w""")

# line 647: vendor_rows
text = text.replace("""        SELECT vendor, SUM(cost_amount) as total_cost, COUNT(id) as count
        FROM maintenance_events
        WHERE vendor IS NOT NULL AND vendor != '' AND performed_at >= :start
        GROUP BY vendor
        ORDER BY total_cost DESC
        LIMIT 5""",
        """        SELECT vendor, SUM(cost_amount) as total_cost, COUNT(m.id) as count
        FROM maintenance_events m
        JOIN assets a ON m.asset_id = a.id
        WHERE vendor IS NOT NULL AND vendor != '' AND m.performed_at >= :start AND a.warehouse_id = :w
        GROUP BY vendor
        ORDER BY total_cost DESC
        LIMIT 5""")

# line 670: mttr_row
text = text.replace("""        SELECT AVG(EXTRACT(EPOCH FROM (resolved_at - created_at))/3600)
        FROM tickets
        WHERE status = 'resolved' AND resolved_at IS NOT NULL""",
        """        SELECT AVG(EXTRACT(EPOCH FROM (t.resolved_at - t.created_at))/3600)
        FROM tickets t
        JOIN assets a ON t.asset_id = a.id
        WHERE t.status = 'resolved' AND t.resolved_at IS NOT NULL AND a.warehouse_id = :w""")

# line 681: prio_rows
text = text.replace("""        SELECT final_priority, AVG(EXTRACT(EPOCH FROM (resolved_at - created_at))/3600)
        FROM tickets
        WHERE status = 'resolved' AND resolved_at IS NOT NULL AND final_priority IS NOT NULL
        GROUP BY final_priority""",
        """        SELECT t.final_priority, AVG(EXTRACT(EPOCH FROM (t.resolved_at - t.created_at))/3600)
        FROM tickets t
        JOIN assets a ON t.asset_id = a.id
        WHERE t.status = 'resolved' AND t.resolved_at IS NOT NULL AND t.final_priority IS NOT NULL AND a.warehouse_id = :w
        GROUP BY t.final_priority""")

with open(path, "w", encoding="utf-8") as f:
    f.write(text)
print("Finished replacements 3.")
