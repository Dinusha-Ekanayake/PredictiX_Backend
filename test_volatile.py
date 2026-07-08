import sqlalchemy
from sqlalchemy import create_engine, text

engine = create_engine('postgresql+psycopg2://postgres.ulpjoljukculqqrwlwup:udCV%40bTGj.Ah38L@aws-1-ap-southeast-2.pooler.supabase.com:6543/postgres')
with engine.connect() as conn:
    try:
        res = conn.execute(text("SELECT proname, provolatile FROM pg_proc JOIN pg_namespace ON pg_namespace.oid = pg_proc.pronamespace WHERE nspname = 'public' AND provolatile = 'v'"))
        for row in res.fetchall():
            print(row)
    except Exception as e:
        print("Error:", e)
