import random
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

random.seed(42)
np.random.seed(42)

NUM_TICKETS = 3000
ASSET_COUNT = 120
OUTPUT_FILE = "predictix_95_percent_v2.csv"

brand_models = {
    "Toyota": ["8FBE15", "8FBN20"],
    "Crown": ["RR5700", "FC4500"],
    "Hyster": ["E50XN", "J40XNT"],
    "Jungheinrich": ["EFG216", "ETV214"]
}

asset_types = {
    "Forklift": ["Toyota", "Hyster"],
    "Reach Truck": ["Crown", "Jungheinrich"],
    "Electric Pallet Jack": ["Toyota"],
    "Tow Tractor": ["Hyster"]
}

sites = ["Colombo DC", "Kandy Hub", "Warehouse 3", "Main Yard"]

shifts = [
    "Day Shift (06:00–14:00)",
    "Evening Shift (14:00–22:00)",
    "Night Shift (22:00–06:00)"
]

technicians = [
    "Technician Silva (Level II)",
    "Senior Tech Perera",
    "Maintenance Officer Jayasinghe",
    "Shift Engineer Fernando"
]


subsystems = {
    "Hydraulic System":[
        "pressure drop in lift cylinder",
        "seal leakage at mast base",
        "irregular hydraulic flow",
        "contaminated hydraulic oil",
        "pump cavitation detected",
        "slow fork elevation",
        "unstable tilt mechanism"
    ],
    "Battery System":[
        "voltage imbalance across cells",
        "thermal instability during charging",
        "reduced charge retention",
        "battery connector corrosion",
        "overheating battery module",
        "low runtime capacity",
        "battery management error"
    ],
    "Drive Motor System":[
        "torque reduction under load",
        "overcurrent during acceleration",
        "excessive brush wear",
        "motor bearing vibration",
        "controller communication fault",
        "erratic motor speed",
        "electrical resistance anomaly"
    ],
    "Steering System":[
        "steering column misalignment",
        "hydraulic steering stiffness",
        "directional response delay",
        "wheel alignment deviation",
        "steering pump noise"
    ],
    "Brake System":[
        "worn brake pads",
        "extended stopping distance",
        "brake fluid contamination",
        "parking brake failure",
        "caliper seizure detected"
    ],
    "Electrical System":[
        "relay malfunction",
        "sensor communication fault",
        "wiring harness damage",
        "control panel error",
        "fuse overload condition"
    ],
    "Mast Assembly":[
        "mast chain wear",
        "uneven lift movement",
        "carriage misalignment",
        "fork tilt malfunction",
        "load backrest instability"
    ]
}

def init_assets():
    assets = []
    for i in range(ASSET_COUNT):

        asset_type = random.choice(list(asset_types.keys()))
        brand = random.choice(asset_types[asset_type])
        model = random.choice(brand_models[brand])

        weak_subsystem = random.choice(list(subsystems.keys()))

        assets.append({
            "id": f"AS-{i:03d}",
            "type": asset_type,
            "brand": brand,
            "model": model,
            "site": random.choice(sites),
            "age": random.randint(1, 10),
            "health": random.uniform(80, 95),
            "wear": random.uniform(0.01, 0.05),
            "timestamp": datetime(2025, 1, 1),
            "fault_history": {},
            "weak_subsystem": weak_subsystem
        })

    return assets

assets = init_assets()


def degrade(asset):
    age_factor = 1 + asset["age"] * 0.05
    delta = (asset["wear"]*100 + random.uniform(0,8)) * age_factor
    asset["health"] -= delta
    asset["health"] = max(5, asset["health"])

def recover(asset):
    asset["health"] += random.uniform(15,25)
    asset["health"] = min(98, asset["health"])

def priority(h, age):
    age_penalty = min(15, age * 1.5)
    effective = h - age_penalty
    if effective < 30: return "Critical"
    if effective < 50: return "High"
    if effective < 65: return "Medium"
    return "Low"

rows = []
seen_summaries = set()
ticket_id = 0

while len(rows) < NUM_TICKETS:

    asset = random.choice(assets)

    gap = int(np.random.exponential(scale=36)) + 2
    gap = min(gap, 720)
    asset["timestamp"] += timedelta(hours=gap)

    prev_health = asset["health"]
    degrade(asset)

    if random.random() < 0.60:
        subsystem = asset["weak_subsystem"]
    else:
        subsystem = random.choice(list(subsystems.keys()))

    fault = random.choice(subsystems[subsystem])

    asset["fault_history"][fault] = asset["fault_history"].get(fault, 0) + 1
    recurrence = asset["fault_history"][fault]

    pr = priority(asset["health"], asset["age"])

    if asset["health"] < 35:
        status = "Resolved"
    elif recurrence > 3:
        status = "Open" if random.random() < 0.55 else "Resolved"
    else:
        status = "Resolved" if random.random() < 0.65 else "Open"

    shift = random.choice(shifts)
    technician = random.choice(technicians)

    if status == "Resolved":
        recover(asset)

    curr_health = asset["health"]
    delta = round(curr_health - prev_health, 1)
    sign = "+" if delta >= 0 else ""
    delta_str = f"Δ{sign}{delta}"

    if recurrence == 1:
        recur_note = " First reported occurrence of this fault on this asset."
    elif recurrence == 2:
        recur_note = f" This fault has been reported {recurrence} times on this asset."
    else:
        recur_note = f" Recurring fault — {recurrence} occurrences logged. RCA recommended."

  
    description_templates = [
        f"{asset['type']} {asset['brand']} {asset['model']} ({asset['id']}) "
        f"at {asset['site']} during {shift} reported {fault}. "
        f"Status: {status}. Health {round(prev_health,1)} → {round(curr_health,1)} ({delta_str})."
        f"{recur_note} Assigned to {technician}.",

        f"During {shift}, asset {asset['id']} ({asset['type']}) "
        f"experienced {fault} in the {subsystem}. "
        f"Marked {status}. Health delta {delta_str}."
        f"{recur_note} Assigned to {technician}.",

        f"{asset['site']} logged {fault} on {asset['brand']} {asset['model']} "
        f"({asset['id']}). Ticket currently {status}. "
        f"Health changed {round(prev_health,1)} → {round(curr_health,1)} ({delta_str})."
        f"{recur_note} Assigned to {technician}.",

        f"{asset['type']} unit {asset['id']} showed {fault} affecting the {subsystem}. "
        f"Status: {status}. Health now {round(curr_health,1)} ({delta_str})."
        f"{recur_note} Assigned to {technician}.",

        f"Inspection during {shift} identified {fault} on {asset['id']} "
        f"located at {asset['site']}. "
        f"Ticket marked {status}. Health delta recorded as {delta_str}."
        f"{recur_note} Assigned to {technician}."
    ]

    description = random.choice(description_templates)

   
    if status == "Resolved":

        summary = (
            f"{fault.capitalize()} on {asset['id']} was resolved during {shift}. "
            f"Health improved from {round(prev_health,1)} to {round(curr_health,1)} ({delta_str}). "
            f"Priority level {pr}. Occurrence count {recurrence}. "
            f"Site: {asset['site']}."
        )

    else:

        summary = (
            f"{fault.capitalize()} on {asset['id']} remains open. "
            f"Health moved from {round(prev_health,1)} to {round(curr_health,1)} ({delta_str}). "
            f"Priority classified as {pr}. Recurrence {recurrence}. "
            f"Location: {asset['site']}."
        )

    if summary in seen_summaries:
        continue

    seen_summaries.add(summary)

    rows.append({
        "Ticket ID": f"T-{ticket_id:05d}",
        "Category": subsystem,
        "Priority": pr,
        "Description": description,
        "Summary": summary,
        "Timestamp": asset["timestamp"]
    })

    ticket_id += 1


df = pd.DataFrame(rows)
df.sort_values(by="Timestamp", inplace=True)
df.drop(columns=["Timestamp"], inplace=True)
df.to_csv(OUTPUT_FILE, index=False)

print("✅ Fully Corrected 95% Dataset Generated")
print(f"📁 Saved as {OUTPUT_FILE}")