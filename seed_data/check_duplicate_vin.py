import re
from collections import Counter

sql_file_path = r"E:\BSc.(Hons) in Artificial Intelligence\Semesters\Year 02\Software Project\predictix_backend\PredictiX_backend\app\seed_data_to_db_v1\predictix_seed_lankalogix_colombo.sql"

with open(sql_file_path, "r", encoding="utf-8") as f:
    sql = f.read()

# looks for quoted VIN-like values starting with HELLKX
vins = re.findall(r"'(HELLKX[^']+)'", sql)

counts = Counter(vins)
dupes = {vin: c for vin, c in counts.items() if c > 1}

print(f"Total VINs found: {len(vins)}")
print(f"Duplicate VINs: {len(dupes)}")

for vin, c in sorted(dupes.items()):
    print(vin, c)