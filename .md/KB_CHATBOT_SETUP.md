# PredictiX Knowledge Base & RAG Chatbot Setup Guide

This guide walks you through setting up the Knowledge Base (KB) system with RAG-based chatbot using local models.

## Prerequisites

- **Python 3.10+** with virtual environment activated
- **Ollama** installed locally (for llama3 LLM)
- **Supabase** account with pgvector enabled
- **PostgreSQL** with pgvector extension (handled by Supabase)

## Installation Steps

### 1. Install Ollama

**Windows/Mac/Linux:**
- Download from: https://ollama.ai
- Follow the installation instructions for your OS
- Verify installation:
  ```bash
  ollama --version
  ```

### 2. Pull the llama3 Model

```bash
ollama pull llama3
```

This downloads the llama3 model (~4.7GB). First run may take time.

### 3. Start Ollama Server

```bash
ollama serve
```

The server will run at `http://localhost:11434` by default.

**Note:** Keep this terminal open while using the chatbot.

### 4. Install Python Dependencies

```bash
pip install -r requirements.txt
```

This includes:
- `sentence-transformers` — for all-MiniLM-L6-v2 embeddings
- `requests` — for Ollama API calls
- `supabase` — for knowledge base access

### 5. Set Environment Variables

Create or update your `.env` file in the project root:

```env
# Supabase Configuration
SUPABASE_URL=your_supabase_project_url
SUPABASE_KEY=your_supabase_anon_key

# Ollama Configuration
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3

# Other existing variables...
DATABASE_URL=...
JWT_SECRET=...
```

### 6. Verify Supabase Setup

Ensure your Supabase has:
- **pgvector extension** enabled
- **knowledge_base table** with structure:
  ```sql
  id (UUID, Primary Key)
  title (TEXT)
  content (TEXT)
  category (TEXT)
  source (TEXT, nullable)
  embedding (vector(384), nullable)
  created_at (TIMESTAMP)
  ```
- **match_knowledge RPC function** for similarity search:
  ```sql
  CREATE OR REPLACE FUNCTION match_knowledge(
    query_embedding vector(384),
    match_count int DEFAULT 5,
    similarity_threshold float DEFAULT 0.3
  ) RETURNS TABLE(
    id UUID,
    title TEXT,
    content TEXT,
    category TEXT,
    source TEXT,
    similarity FLOAT,
    created_at TIMESTAMP
  ) AS $$
  BEGIN
    RETURN QUERY
    SELECT
      kb.id,
      kb.title,
      kb.content,
      kb.category,
      kb.source,
      1 - (kb.embedding <=> query_embedding) as similarity,
      kb.created_at
    FROM knowledge_base kb
    WHERE kb.embedding IS NOT NULL
    AND (1 - (kb.embedding <=> query_embedding)) > similarity_threshold
    ORDER BY kb.embedding <=> query_embedding
    LIMIT match_count;
  END;
  $$ LANGUAGE plpgsql;
  ```

## API Endpoints

### 1. Ask Chatbot (RAG)

**POST** `/chatbot/ask`

Request:
```json
{
  "question": "How do I maintain the brake system?",
  "use_knowledge_base": true,
  "kb_limit": 3,
  "similarity_threshold": 0.3
}
```

Response:
```json
{
  "question": "How do I maintain the brake system?",
  "answer": "The brake system should be inspected regularly...",
  "used_knowledge_base": true,
  "context_entries": [
    {
      "id": "entry-id",
      "title": "Brake Maintenance",
      "content": "...",
      "category": "maintenance",
      "source": "manual",
      "similarity": 0.87,
      "created_at": "2026-01-15T10:00:00"
    }
  ],
  "model": "llama3",
  "timestamp": "2026-04-24T10:30:00"
}
```

### 2. Search Knowledge Base

**POST** `/chatbot/search-kb`

Request:
```json
{
  "query": "tire replacement",
  "limit": 5,
  "similarity_threshold": 0.3
}
```

Response:
```json
{
  "query": "tire replacement",
  "results": [
    {
      "id": "entry-id",
      "title": "Tire Maintenance Guide",
      "content": "...",
      "category": "maintenance",
      "source": "documentation",
      "similarity": 0.91
    }
  ],
  "count": 1
}
```

### 3. Add Knowledge Entry

**POST** `/chatbot/kb/add`

Request:
```json
{
  "title": "Oil Change Procedure",
  "content": "Steps to change engine oil...",
  "category": "maintenance",
  "source": "service_manual"
}
```

Response:
```json
{
  "id": "new-entry-id",
  "title": "Oil Change Procedure",
  "content": "Steps to change engine oil...",
  "category": "maintenance",
  "source": "service_manual",
  "created_at": "2026-04-24T10:00:00",
  "embedding": null
}
```

### 4. Generate Embeddings

**POST** `/chatbot/kb/generate-embeddings`

Generates embeddings for all KB entries without embeddings. Run this after adding new entries.

Response:
```json
{
  "status": "success",
  "message": "Embeddings generated successfully"
}
```

### 5. Chatbot Health Check

**GET** `/chatbot/health`

Response:
```json
{
  "status": "ok",
  "ollama_available": true,
  "knowledge_base_available": true,
  "model": "llama3",
  "embedding_model": "all-MiniLM-L6-v2"
}
```

## Usage Workflow

### First Time Setup:

1. Start Ollama:
   ```bash
   ollama serve
   ```

2. Start FastAPI server:
   ```bash
   uvicorn app.main:app --reload
   ```

3. Add initial knowledge entries (via `/chatbot/kb/add` endpoint)

4. Generate embeddings:
   ```bash
   curl -X POST http://localhost:8000/chatbot/kb/generate-embeddings
   ```

5. Test health:
   ```bash
   curl http://localhost:8000/chatbot/health
   ```

6. Ask questions:
   ```bash
   curl -X POST http://localhost:8000/chatbot/ask \
     -H "Content-Type: application/json" \
     -d '{"question": "What is predictive maintenance?"}'
   ```

### Bulk Add Knowledge Entries:

Use the script `app/knowledge/generate_embeddings.py` after adding entries via the endpoint:

```bash
python -m app.knowledge.generate_embeddings
```

This will find all KB entries without embeddings and generate them.

## Troubleshooting

### Ollama Connection Error
- Ensure Ollama is running: `ollama serve`
- Check `OLLAMA_BASE_URL` in `.env`
- Verify with: `curl http://localhost:11434/api/tags`

### Knowledge Base Errors
- Verify Supabase credentials in `.env`
- Check pgvector extension is enabled
- Ensure `match_knowledge` RPC function exists

### Slow Embeddings
- First run downloads the model (~300MB)
- Subsequent runs use cached model
- Consider reducing `kb_limit` in requests for faster responses

### Memory Issues
- llama3 requires ~4GB RAM minimum
- Reduce model size (use `ollama pull mistral` for smaller model)
- Close other applications

## Performance Tips

1. **Cache Models:** Ollama caches models locally after first run
2. **Limit KB Results:** Use `kb_limit: 3-5` for balanced performance
3. **Batch Embeddings:** Generate embeddings for multiple entries at once
4. **Monitor Ollama:** Check system resources while running

## Next Steps

1. ✅ Set up Ollama locally
2. ✅ Configure `.env` variables
3. ✅ Add knowledge base entries
4. ✅ Generate embeddings
5. ✅ Start asking questions!

## Support

- **Ollama Issues:** https://github.com/ollama/ollama/issues
- **SentenceTransformers:** https://www.sbert.net/
- **Supabase pgvector:** https://supabase.com/docs/guides/database/extensions/pgvector

---

**Last Updated:** April 24, 2026
