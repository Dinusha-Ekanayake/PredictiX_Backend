"""TEMP read-only repro of GET /users/ (list_users) to surface the 500 traceback."""
import traceback
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import func
from app.db.session import SessionLocal
from app.models import Asset, Department, Profile, Warehouse
from app.routers.users import _build_item

db = SessionLocal()
try:
    print("step: department query")
    dept_names = {d.id: d.name for d in db.query(Department.id, Department.name).all()}
    print("  depts:", len(dept_names))

    print("step: warehouse query")
    warehouse_names = {w.id: w.name for w in db.query(Warehouse.id, Warehouse.name).all()}
    print("  warehouses:", len(warehouse_names))

    print("step: asset_counts query")
    asset_counts = {
        str(a): c
        for a, c in db.query(Asset.assigned_to, func.count(Asset.id))
        .filter(Asset.assigned_to.isnot(None), Asset.status == "active")
        .group_by(Asset.assigned_to).all()
    }
    print("  asset_counts:", len(asset_counts))

    print("step: profile query")
    users = db.query(Profile).all()
    print("  users:", len(users))

    print("step: build items")
    ok = 0
    for i, u in enumerate(users):
        try:
            _build_item(u, dept_names, warehouse_names, asset_counts)
            ok += 1
        except Exception:
            print(f"  !! _build_item FAILED at index {i}, user id={getattr(u,'id',None)} email={getattr(u,'email',None)}")
            traceback.print_exc()
            break
    print(f"  built OK: {ok}/{len(users)}")
except Exception:
    print("!! QUERY-LEVEL FAILURE:")
    traceback.print_exc()
finally:
    db.close()
