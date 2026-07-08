import sqlalchemy
from sqlalchemy import create_engine, text

engine = create_engine('postgresql+psycopg2://postgres.ulpjoljukculqqrwlwup:udCV%40bTGj.Ah38L@aws-1-ap-southeast-2.pooler.supabase.com:6543/postgres')
with engine.connect() as conn:
    try:
        # Reset the broken setting
        conn.execute(text("ALTER ROLE authenticator RESET pgrst.db_pre_request"))
        conn.execute(text("NOTIFY pgrst, 'reload config'"))
        conn.commit()
        print("Successfully reset pgrst.db_pre_request and reloaded config.")
    except Exception as e:
        print("Error:", e)
        conn.rollback()
