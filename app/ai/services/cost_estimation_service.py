import pickle
import os

BASE_DIR = os.path.dirname(os.path.dirname(__file__))

MODEL_PATH = os.path.join(
    BASE_DIR,
    "models",
    "cost_estimation_model",
    "cost_maintenance_model.pkl"
)

# Load INSIDE the with block
with open(MODEL_PATH, "rb") as f:
    reg_model = pickle.load(f)

# since pickle only has model
reg_mae = 15000  # know exact value

reg_features = [
    "vehicle_type",
    "repair_type",
    "mileage",
    "labor_hours",
    "service_days"
]

reg_cat_features = ["vehicle_type", "repair_type"]