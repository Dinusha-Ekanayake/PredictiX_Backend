import os
import sys

sys.path.insert(0, r"D:\Project\sharada-user-section-backend")
os.chdir(r"D:\Project\sharada-user-section-backend")
os.environ["PYTHONIOENCODING"] = "utf-8"

from app.db.session import SessionLocal
from app.models import Warehouse

db = SessionLocal()
w = db.query(Warehouse).first()
print(f"Warehouse ID: {w.id}")
db.close()
