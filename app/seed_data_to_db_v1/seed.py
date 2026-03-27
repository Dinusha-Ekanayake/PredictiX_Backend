# import psycopg2
# from dotenv import load_dotenv
# import os
    
# load_dotenv()

# SUPABASE_URL = os.getenv("SUPABASE_URL")
# DATABASE_PASSWORD = os.getenv("DATABASE_PASSWORD")


# conn = psycopg2.connect(
#     host="db.ulpjoljukculqqrwlwup.supabase.co", 
#     database="postgres",
#     user="postgres",
#     password=DATABASE_PASSWORD,
#     port=5432,
#     sslmode="require"
# )

# cur = conn.cursor()

# sql_file_path = r"E:\BSc.(Hons) in Artificial Intelligence\Semesters\Year 02\Software Project\predictix_backend\PredictiX_backend\app\seed_data_to_db_v1\predictix_seed_lankalogix_colombo_fixed_vins.sql"

# with open(sql_file_path, "r", encoding="utf-8") as f:
#     for statement in f.read().split(";"):
#         if statement.strip():
#             cur.execute(statement)

# conn.commit()
# cur.close()
# conn.close()

# print("✅ SQL executed in chunks successfully!")

import psycopg2
from dotenv import load_dotenv
import os

load_dotenv()

conn = psycopg2.connect(
    host="db.ulpjoljukculqqrwlwup.supabase.co",
    database="postgres",
    user="postgres",
    password=os.environ["DATABASE_PASSWORD"],
    port=5432,
    sslmode="require"
)

cur = conn.cursor()

sql_file_path = r"E:\BSc.(Hons) in Artificial Intelligence\Semesters\Year 02\Software Project\predictix_backend\PredictiX_backend\app\seed_data_to_db_v1\predictix_seed_lankalogix_colombo_fixed_vins.sql"

try:
    with open(sql_file_path, "r", encoding="utf-8") as f:
        sql = f.read()

    cur.execute(sql)
    conn.commit()
    print("✅ SQL executed successfully!")

except Exception as e:
    conn.rollback()
    print("❌ Error:", e)

finally:
    cur.close()
    conn.close()