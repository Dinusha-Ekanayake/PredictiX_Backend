import sqlalchemy
from sqlalchemy import create_engine, text

engine = create_engine('postgresql+psycopg2://postgres.ulpjoljukculqqrwlwup:udCV%40bTGj.Ah38L@aws-1-ap-southeast-2.pooler.supabase.com:6543/postgres')
with engine.connect() as conn:
    try:
        res = conn.execute(text("INSERT INTO tickets (title, description, created_by) VALUES ('test', 'test', '00000000-0000-0000-0000-000000000000') RETURNING id"))
        print(res.fetchone())
        conn.commit()
    except Exception as e:
        print("Error:", e)
        conn.rollback()
