import sys
import os
import uuid
import random

# Ensure the app path is in sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.db.session import SessionLocal
from app.models import Warehouse, Department, Asset

def seed_badulla():
    db = SessionLocal()
    try:
        # 1. Create Badulla Warehouse
        badulla_wh = db.query(Warehouse).filter_by(code="LL-BDLA").first()
        if not badulla_wh:
            badulla_wh = Warehouse(
                id=uuid.uuid4(),
                code="LL-BDLA",
                name="LankaLogix - Badulla",
                address="No 12, Main Street, Badulla",
                city="Badulla",
                district="Badulla",
                climate_zone="Upcountry",
                warehouse_type="Regional Hub"
            )
            db.add(badulla_wh)
            db.commit()
            db.refresh(badulla_wh)
            print(f"Created warehouse: {badulla_wh.name}")
        else:
            print(f"Warehouse {badulla_wh.name} already exists.")

        # 2. Create Departments for Badulla
        depts_data = [
            {"code": "BD-LOG", "name": "Logistics"},
            {"code": "BD-MNT", "name": "Maintenance"}
        ]
        dept_map = {}
        for d_data in depts_data:
            dept = db.query(Department).filter_by(warehouse_id=badulla_wh.id, code=d_data["code"]).first()
            if not dept:
                dept = Department(
                    id=uuid.uuid4(),
                    warehouse_id=badulla_wh.id,
                    code=d_data["code"],
                    name=d_data["name"]
                )
                db.add(dept)
                db.commit()
                db.refresh(dept)
                print(f"Created department: {dept.name}")
            dept_map[d_data["code"]] = dept

        # 3. Add Realistic Vehicle Assets for Badulla
        assets_data = [
            {"asset_code": "BD-TRK-001", "name": "Tata LPT 1109 - Freight", "type": "Truck", "make": "Tata", "model": "LPT 1109", "year": 2018, "fuel": "Diesel", "mileage": 120500},
            {"asset_code": "BD-TRK-002", "name": "Isuzu Elf - Refrigerated", "type": "Truck", "make": "Isuzu", "model": "Elf", "year": 2020, "fuel": "Diesel", "mileage": 85000},
            {"asset_code": "BD-VAN-001", "name": "Toyota HiAce - Delivery", "type": "Van", "make": "Toyota", "model": "HiAce", "year": 2019, "fuel": "Diesel", "mileage": 102000},
            {"asset_code": "BD-VAN-002", "name": "Nissan Caravan - Delivery", "type": "Van", "make": "Nissan", "model": "Caravan", "year": 2021, "fuel": "Diesel", "mileage": 60000},
            {"asset_code": "BD-4X4-001", "name": "Toyota Hilux - Estate Support", "type": "Pickup 4x4", "make": "Toyota", "model": "Hilux", "year": 2022, "fuel": "Diesel", "mileage": 35000},
            {"asset_code": "BD-TRK-003", "name": "Ashok Leyland Dost - Light Delivery", "type": "Light Truck", "make": "Ashok Leyland", "model": "Dost", "year": 2021, "fuel": "Diesel", "mileage": 45000},
            {"asset_code": "BD-FLT-001", "name": "Toyota Forklift 3.0T", "type": "Forklift", "make": "Toyota", "model": "8FD30", "year": 2017, "fuel": "Diesel", "mileage": 12000},
        ]

        added = 0
        for ad in assets_data:
            existing = db.query(Asset).filter_by(asset_code=ad["asset_code"]).first()
            if not existing:
                dept_id = dept_map["BD-LOG"].id if "TRK" in ad["asset_code"] or "VAN" in ad["asset_code"] else dept_map["BD-MNT"].id
                ast = Asset(
                    id=uuid.uuid4(),
                    asset_code=ad["asset_code"],
                    warehouse_id=badulla_wh.id,
                    department_id=dept_id,
                    asset_name=ad["name"],
                    asset_type="vehicle",
                    category="Heavy Duty" if "TRK" in ad["asset_code"] else ("Material Handling" if "FLT" in ad["asset_code"] else "Light Commercial"),
                    vehicle_type=ad["type"],
                    make=ad["make"],
                    model=ad["model"],
                    manufacture_year=ad["year"],
                    status="active",
                    health_band="good" if ad["mileage"] < 50000 else ("moderate" if ad["mileage"] < 100000 else "critical"),
                    criticality_score=round(random.uniform(5.0, 8.5), 2),
                    current_mileage=ad["mileage"],
                    fuel_type=ad["fuel"]
                )
                db.add(ast)
                added += 1

        db.commit()
        print(f"Successfully added {added} new realistic vehicle assets to LankaLogix - Badulla.")

    except Exception as e:
        print("Error:", e)
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_badulla()
