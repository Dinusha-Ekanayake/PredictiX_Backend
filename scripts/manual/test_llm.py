import sys
from pathlib import Path

# Repository root on sys.path so `import app` works however this is invoked.
# Located by walking up to the directory holding the app package, so moving
# this file cannot break it.
_here = Path(__file__).resolve()
_root = next(p for p in _here.parents if (p / "app" / "__init__.py").exists())
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import asyncio
import os
from app.ai.services.llm_service import call_groq

prompt = """You are PredictiX Assistant. A user asked: "how many closed tickets here"
The database returned this data: [{'Metric': 'Total Users', 'Count': 103}, {'Metric': 'Active Users', 'Count': 103}, {'Metric': 'Admins', 'Count': 6}, {'Metric': 'Super Admins', 'Count': 4}, {'Metric': 'Regular Users', 'Count': 93}, {'Metric': 'Total Assets', 'Count': 1007}, {'Metric': 'Critical Alerts', 'Count': 366}, {'Metric': 'Open Tickets', 'Count': 205}, {'Metric': 'High Priority Tickets', 'Count': 116}, {'Metric': 'Predicted Failures', 'Count': 363}]

INSTRUCTIONS — follow these EXACTLY:
1. Start with a ONE-LINE summary stating the TOTAL count.
2. Then list EVERY SINGLE category/group/status/role from the data with its exact count.
   Format each line as: [emoji] **Category Name:** X items
3. Use 👥 for user roles, 🎫 for ticket status, ⚙️ for asset types, 📊 for general stats.
4. Quote EXACT numbers — never round or approximate.
5. Never say 'Found N records matching' — always show the actual breakdown.
6. Never expose raw UUIDs.
7. End with a polite, helpful closing sentence."""

summary, fb = call_groq(
    messages=[{'role': 'user', 'content': prompt}],
    model='llama-3.1-8b-instant',
    max_tokens=400,
    temperature=0.2,
)
print("SUMMARY:", summary)
print("FB:", fb)
