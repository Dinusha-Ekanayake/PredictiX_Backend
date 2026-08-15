import logging
logging.basicConfig(level=logging.INFO)

from app.chatbot.knowledge_service import search_knowledge

res = search_knowledge("how to change my profile picture")
print("SEARCH RESULTS:", res)
