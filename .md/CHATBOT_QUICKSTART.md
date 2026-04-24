# PredictiX Chatbot - Quick Start Guide

## 🚀 TL;DR - Get Started in 5 Minutes

### Prerequisites
- Python 3.10+ (already have)
- Supabase account (already have)
- Ollama installed

### Step 1: Install Ollama
```bash
# Download from https://ollama.ai and install
# Then pull llama3 model
ollama pull llama3

# Start Ollama server (keep this running)
ollama serve
```

### Step 2: Setup Supabase
1. Go to Supabase SQL Editor
2. Copy-paste entire contents of `KB_SUPABASE_SETUP.sql`
3. Run the SQL queries
4. Verify: You should see 3 sample knowledge entries

### Step 3: Update .env File
Add these variables to your `.env` file:
```env
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3
```

### Step 4: Install Dependencies
```bash
pip install sentence-transformers requests python-dotenv
# Or: pip install -r requirements.txt
```

### Step 5: Generate Embeddings
```bash
# Option A: Via FastAPI endpoint
curl -X POST http://localhost:8000/chatbot/kb/generate-embeddings

# Option B: Via Python script
python -m app.knowledge.generate_embeddings
```

### Step 6: Test the Chatbot
```bash
# Check health
curl http://localhost:8000/chatbot/health

# Ask a question
curl -X POST http://localhost:8000/chatbot/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "How do I maintain the tire system?"}'
```

## 📍 Key Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/chatbot/ask` | Ask chatbot with RAG |
| POST | `/chatbot/search-kb` | Search knowledge base |
| POST | `/chatbot/kb/add` | Add new KB entry |
| POST | `/chatbot/kb/generate-embeddings` | Generate embeddings |
| GET | `/chatbot/health` | Check system health |

## 📂 File Structure Created

```
app/
├── knowledge/
│   ├── __init__.py
│   └── generate_embeddings.py          # Generate embeddings script
├── ai/
│   └── services/
│       └── knowledge_service.py        # KB search & CRUD functions
├── schemas/
│   └── chatbot.py                      # Request/Response schemas
├── routers/
│   └── chatbot.py                      # Chatbot API endpoints
└── main.py                             # Updated with chatbot router

Project root:
├── KB_CHATBOT_SETUP.md                 # Detailed setup guide
├── KB_SUPABASE_SETUP.sql               # Supabase SQL setup
└── requirements.txt                    # Updated with new deps
```

## 🔄 Typical Workflow

### Adding Knowledge Entries
```bash
# 1. Add entry via endpoint
curl -X POST http://localhost:8000/chatbot/kb/add \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Engine Maintenance",
    "content": "Check engine oil...",
    "category": "maintenance",
    "source": "manual"
  }'

# 2. Generate embeddings
curl -X POST http://localhost:8000/chatbot/kb/generate-embeddings

# 3. Start asking questions
curl -X POST http://localhost:8000/chatbot/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "How do I check the engine?"}'
```

## 🐛 Troubleshooting

| Issue | Solution |
|-------|----------|
| `Connection refused to localhost:11434` | Start Ollama: `ollama serve` |
| `Chatbot service unavailable` | Check Ollama is running and healthy |
| `No embeddings found` | Run `generate-embeddings` endpoint |
| `Slow responses` | Reduce `kb_limit` to 2-3 results |
| `Out of memory` | Close other apps, llama3 needs ~4GB |

## 📊 Example Responses

### Ask Question with Context
```bash
curl -X POST http://localhost:8000/chatbot/ask \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What is the tire maintenance schedule?",
    "use_knowledge_base": true,
    "kb_limit": 3
  }'
```

Response:
```json
{
  "question": "What is the tire maintenance schedule?",
  "answer": "Based on the knowledge base, tire maintenance includes checking pressure monthly, rotating every 10,000 km...",
  "used_knowledge_base": true,
  "context_entries": [
    {
      "title": "Tire Maintenance Guide",
      "similarity": 0.95,
      "category": "maintenance"
    }
  ],
  "model": "llama3"
}
```

## 🎯 Next Steps

1. ✅ **Setup**: Follow steps 1-5 above
2. ✅ **Test**: Verify health endpoint works
3. ✅ **Add Data**: Insert your own knowledge entries
4. ✅ **Customize**: Adjust similarity thresholds as needed
5. ✅ **Deploy**: Push to production when ready

## 📚 More Info

For detailed information, see:
- **Setup & Configuration**: `KB_CHATBOT_SETUP.md`
- **Database Schema**: `KB_SUPABASE_SETUP.sql`
- **API Details**: `/docs` endpoint in FastAPI (Swagger UI)

## ⚠️ Important Notes

- **Ollama must be running** while using the chatbot
- **First embedding generation** may take 1-2 minutes for many entries
- **Responses depend on KB quality** - better content = better answers
- **Similarity threshold** (0-1): Lower = more results, Higher = more relevant

---

**Ready to chat?** Start with step 1 above! 🎉
