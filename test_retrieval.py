import os
from app.kb.kb_vector_store import get_kb_store

def main():
    store = get_kb_store()
    print("Testing retrieve:")
    results = store.retrieve("What is the scheduled maintenance interval for brakes?")
    for r in results:
        print(f"[{r['id']}] Score: {r['score']}")
    
    print("\nTesting retrieve_by_tags:")
    results = store.retrieve_by_tags(["SMRP", "safety"])
    for r in results:
        print(f"[{r['id']}] tag_matches: {r.get('tag_matches')}")

if __name__ == "__main__":
    main()
