import sys
import os

# Add parent directory to path to import app module
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.db.supabase_client import supabase

def main():
    response = supabase.from_("faqs").select("*").execute()
    for faq in response.data:
        print(f"ID: {faq.get('id')}, Question: {faq.get('question')}, Answer: {faq.get('answer')}")

if __name__ == "__main__":
    main()
