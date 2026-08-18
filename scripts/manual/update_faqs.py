import sys
import os
from dotenv import load_dotenv

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
load_dotenv()

from supabase import create_client, Client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

supabase_admin: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

def main():
    # Delete test faqs
    delete_ids = [
        "4f30bcbb-b460-44b1-90f3-4d7dee1f3f4b", # test q
        "88f2850f-1226-45d8-b708-7469bef87d8e", # TEWW
        "607c6635-2399-448a-b122-a154d3dfc062", # test
        "8a56e3a4-01fb-4715-84c9-49f77618b8a3", # test 2
    ]
    
    for faq_id in delete_ids:
        print(f"Deleting FAQ {faq_id}...")
        res = supabase_admin.from_("faqs").delete().eq("id", faq_id).execute()
        print(res.data)
        
    # Update "forgot my password" faq
    update_id = "66a55b45-0ddd-43a5-ae86-007bc4251297"
    print(f"Updating FAQ {update_id}...")
    res = supabase_admin.from_("faqs").update({"answer": "contact admin"}).eq("id", update_id).execute()
    print(res.data)
    
    print("Done!")

if __name__ == "__main__":
    main()
