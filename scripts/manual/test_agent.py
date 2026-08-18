import sys
from pathlib import Path

# Repository root on sys.path so `import app` works however this is invoked.
# Located by walking up to the directory holding the app package, so moving
# this file cannot break it.
_here = Path(__file__).resolve()
_root = next(p for p in _here.parents if (p / "app" / "__init__.py").exists())
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import sys
import io

# Force UTF-8 output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from app.db import SessionLocal
from app.models import Profile
from app.ai.agent.agent_service import run_agent
from app.ai.agent.tools import ToolContext

def test():
    db = SessionLocal()
    user = db.query(Profile).filter(Profile.role == 'admin').first()
    if not user:
        print("No admin found. Using any user.")
        user = db.query(Profile).first()
        
    ctx = ToolContext(db=db, user=user)
    print(f"Testing with user: {user.full_name} ({user.role})")
    
    # Test 1: Simple greeting (no tools needed)
    print("\n--- Test 1: Simple greeting ---")
    res = run_agent('hello, what can you help me with?', None, ctx)
    print('Answer:', res["answer"][:500])
    print('Tools called:', [t["name"] for t in res["tool_trace"]])
    
    # Test 2: Tool-calling question
    print("\n--- Test 2: How many open tickets? ---")
    res = run_agent('how many open tickets are there?', None, ctx)
    print('Answer:', res["answer"][:500])
    print('Tools called:', [t["name"] for t in res["tool_trace"]])

if __name__ == "__main__":
    test()
