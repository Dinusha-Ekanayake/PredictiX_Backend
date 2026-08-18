import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ai.services.knowledge_service import search_knowledge

def test():
    query = "Factories Ordinance hoist inspection"
    print(f"Query: {query}")
    results = search_knowledge(query, match_count=2)
    print(f"Results found: {len(results)}")
    for i, r in enumerate(results):
        print(f"\n[{i+1}] {r.get('title') or r.get('section')}")
        print(f"Source: {r.get('source')}")
        print(f"Content: {r.get('content')[:150]}...")

if __name__ == "__main__":
    test()
