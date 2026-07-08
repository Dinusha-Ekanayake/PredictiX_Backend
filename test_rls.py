import sqlalchemy
from sqlalchemy import create_engine, text

engine = create_engine('postgresql+psycopg2://postgres.ulpjoljukculqqrwlwup:udCV%40bTGj.Ah38L@aws-1-ap-southeast-2.pooler.supabase.com:6543/postgres')
with engine.connect() as conn:
    res = conn.execute(text("SELECT pol.polname, pol.polcmd, pg_get_expr(pol.polqual, pol.polrelid) AS qual FROM pg_policy pol JOIN pg_class c ON c.oid = pol.polrelid WHERE c.relname = 'tickets'"))
    print(res.fetchall())
    
    # Also check if it's a view
    res = conn.execute(text("SELECT table_type FROM information_schema.tables WHERE table_name = 'tickets'"))
    print("Type:", res.fetchall())
