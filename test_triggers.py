import sqlalchemy
from sqlalchemy import create_engine, text

engine = create_engine('postgresql+psycopg2://postgres.ulpjoljukculqqrwlwup:udCV%40bTGj.Ah38L@aws-1-ap-southeast-2.pooler.supabase.com:6543/postgres')
with engine.connect() as conn:
    res = conn.execute(text("SELECT tgname, proname FROM pg_trigger JOIN pg_proc ON pg_trigger.tgfoid = pg_proc.oid WHERE tgrelid = 'tickets'::regclass"))
    print("Triggers:", res.fetchall())
