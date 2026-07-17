import os, psycopg2
from dotenv import load_dotenv

load_dotenv()
dsn = os.environ['DATABASE_URL'].replace('postgresql+psycopg2://', 'postgresql://')
conn = psycopg2.connect(dsn)
cur = conn.cursor()

cur.execute("UPDATE faqs SET category = 'ticket' WHERE category = 'tickets'")
cur.execute("UPDATE faqs SET category = 'asset' WHERE category = 'assets'")
cur.execute("UPDATE faqs SET category = 'user' WHERE category = 'account'")
conn.commit()

cur.execute('SELECT id, question, category FROM faqs')
print(cur.fetchall())
