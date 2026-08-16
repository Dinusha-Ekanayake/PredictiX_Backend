import sys
import os

# Add parent directory to path to import app module
import sys
from pathlib import Path

# Put the repository root on sys.path so `import app` works however this script
# is invoked. Located by walking up to the directory that contains the app
# package, rather than by counting parents, so moving this file cannot break it.
_here = Path(__file__).resolve()
_root = next(p for p in _here.parents if (p / "app" / "__init__.py").exists())
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from app.db.supabase_client import supabase

def main():
    response = supabase.from_("faqs").select("*").execute()
    for faq in response.data:
        print(f"ID: {faq.get('id')}, Question: {faq.get('question')}, Answer: {faq.get('answer')}")

if __name__ == "__main__":
    main()
