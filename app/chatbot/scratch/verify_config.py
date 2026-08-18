from app.ai.services.llm_service import MODEL_COMPOUND, MODEL_COMPOUND_MINI, FAST_MODELS, HEAVY_MODELS, MODEL_CASCADE
from app.ai.agent.agent_service import run_agent
from app.ai.agent.tools import ToolContext

print("LLM CONFIGURATION:")
print("MODEL_COMPOUND:", MODEL_COMPOUND)
print("MODEL_COMPOUND_MINI:", MODEL_COMPOUND_MINI)
print("FAST_MODELS:", FAST_MODELS)
print("HEAVY_MODELS:", HEAVY_MODELS)
print("MODEL_CASCADE:", MODEL_CASCADE)
print("SUCCESS: Modules loaded cleanly.")
