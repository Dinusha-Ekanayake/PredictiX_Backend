import sys
import os
sys.path.append(os.getcwd())
from app.agents.report_agents import _build_survival_summary, build_warehouse_context
from app.db.session import SessionLocal
from app.models import Warehouse

db = SessionLocal()
w = db.query(Warehouse).first()
if w:
    ctx = build_warehouse_context(db, str(w.id))
    try:
        from app.ai.services import survival_service
        codes = [a.get('code') for a in (ctx.get('critical_assets', []) or [])[:25] if a.get('code')]
        if not codes:
            print("NO CODES")
            sys.exit(1)
        res = survival_service.fleet_survival_summary(db, max_assets=25, horizon_days=180, asset_codes=codes)
        print("Success!", res.get("assets_analyzed"))
    except Exception as e:
        print("EXCEPTION:", e)
        import traceback
        traceback.print_exc()
