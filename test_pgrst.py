import sqlalchemy
from sqlalchemy import create_engine, text

engine = create_engine('postgresql+psycopg2://postgres.ulpjoljukculqqrwlwup:udCV%40bTGj.Ah38L@aws-1-ap-southeast-2.pooler.supabase.com:6543/postgres')
with engine.connect() as conn:
    try:
        res = conn.execute(text("SHOW ALL"))
        for row in res:
            if 'pgrst' in row[0] or 'pre_request' in row[0]:
                print(row)
    except Exception as e:
        print("Error showing all:", e)
        
    try:
        res = conn.execute(text("SELECT * FROM pg_proc WHERE proname = 'pre_request'"))
        print(res.fetchall())
    except Exception as e:
        print(e)
