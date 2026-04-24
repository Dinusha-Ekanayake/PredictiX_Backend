# 🤖 How to Add LLM to PredictiX - Complete Guide

## Overview

You have **3 main options** for integrating an LLM into PredictiX:

1. **🏠 Local LLM (Ollama)** - Free, private, no API costs (Recommended for MVP)
2. **☁️ Cloud API (OpenAI/Anthropic/GitHub)** - More powerful, better quality, requires API key
3. **🔄 Hybrid** - Use local for simple tasks, cloud for complex ones

## Current Implementation (What You Have Now)

Your chatbot is **already using Ollama + llama3**! Here's what's happening:

### Files Already Set Up
- ✅ `app/routers/chatbot.py` - Calls Ollama via `/api/generate` endpoint
- ✅ `app/ai/services/knowledge_service.py` - Uses SentenceTransformers for embeddings
- ✅ Environment variables configured in `.env`

### Current Flow
```
User Question
    ↓
Search Knowledge Base (SentenceTransformers embeddings)
    ↓
Build Prompt with KB Context
    ↓
Call Ollama LLM (llama3)
    ↓
Parse Response (Structured answer)
    ↓
Return ChatbotResponse
```

---

## Option 1: Ollama (Local LLM) - Currently Using

### ✅ Advantages
- 🔒 **Privacy** - Data stays on your machine
- 💰 **Free** - No API costs
- ⚡ **Fast** - No network latency
- 🎓 **Learning** - Great for development/testing
- 📱 **Works Offline** - No internet required

### ❌ Disadvantages
- 💻 **Resource Heavy** - Needs good GPU/CPU
- 🎯 **Lower Quality** - llama3 < GPT-4o
- 🔧 **Maintenance** - You manage the server
- 📊 **Limited Models** - Fewer choices

### Setup Steps

#### Step 1: Install Ollama
```bash
# Download from https://ollama.ai
# Or on Ubuntu:
curl https://ollama.ai/install.sh | sh
```

#### Step 2: Start Ollama Server
```bash
ollama serve
# Runs on http://localhost:11434
```

#### Step 3: Pull a Model
```bash
ollama pull llama3        # Currently using (8B, fast, balanced)
ollama pull llama3:70b    # Larger, better quality
ollama pull mistral       # Fast, good for coding
ollama pull neural-chat   # Smaller, optimized
```

#### Step 4: Test It
```bash
# Test locally
ollama run llama3 "What is predictive maintenance?"

# Or via API
curl http://localhost:11434/api/generate \
  -d '{
    "model": "llama3",
    "prompt": "What is tire maintenance?",
    "stream": false
  }'
```

#### Step 5: Configure in PredictiX

Create `.env` file in project root:
```env
# LLM Configuration
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3

# Embeddings
EMBEDDING_MODEL=all-MiniLM-L6-v2

# Database
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_key
```

#### Step 6: Run Your Chatbot
```bash
# Activate virtual environment
.venv\Scripts\Activate.ps1  # Windows
source .venv/bin/activate  # Mac/Linux

# Install dependencies
pip install -r requirements.txt

# Start FastAPI
uvicorn app.main:app --reload

# Test endpoint
curl -X POST http://localhost:8000/chatbot/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "How do I maintain tires?"}'
```

### Current Code Implementation
```python
# app/routers/chatbot.py - How it calls Ollama

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")

def _call_ollama(prompt, timeout=60):
    """Call Ollama LLM endpoint"""
    try:
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False
            },
            timeout=timeout
        )
        response.raise_for_status()
        return response.json().get("response")
    except Exception as e:
        print(f"Error calling Ollama: {e}")
        return None
```

### Available Models (Ollama)
```bash
ollama pull llama3           # 8B - balanced (CURRENT)
ollama pull llama3:70b       # 70B - better quality, slower
ollama pull mistral          # 7B - fast, good
ollama pull neural-chat      # 7B - optimized for chat
ollama pull dolphin-mixtral  # 8x7B - powerful
ollama pull zephyr           # 7B - fast, accurate
```

---

## Option 2: Cloud API (OpenAI, Anthropic, GitHub)

### ✅ Advantages
- 🚀 **High Quality** - Latest powerful models (GPT-5, Claude Opus)
- 📈 **Scalable** - Handle millions of requests
- 🔄 **Updates** - Models improve automatically
- 🎯 **Specialized** - Models for different tasks
- 📊 **Analytics** - Usage tracking and logging

### ❌ Disadvantages
- 💸 **Costs Money** - Per-token pricing ($0.10-$30+ per 1M tokens)
- 🌐 **Network Latency** - Slower responses
- 🔐 **Privacy** - Data sent to external servers
- 🔑 **API Key Required** - Dependency on API provider

### Option 2A: OpenAI (GPT-4o, GPT-5)

#### Setup
```bash
# 1. Get API key from https://platform.openai.com
# 2. Install package
pip install openai

# 3. Add to .env
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini  # or gpt-5, gpt-4o
```

#### Code Implementation
```python
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def call_openai(prompt):
    """Call OpenAI API"""
    try:
        response = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=1000
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Error calling OpenAI: {e}")
        return None
```

#### Pricing
- GPT-4o mini: $0.15 per 1M input tokens
- GPT-4o: $2.50 per 1M input tokens
- GPT-5: $15+ per 1M input tokens

### Option 2B: Anthropic (Claude Opus, Sonnet)

#### Setup
```bash
# 1. Get API key from https://console.anthropic.com
# 2. Install package
pip install anthropic

# 3. Add to .env
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-opus-4-5  # Best quality
```

#### Code Implementation
```python
from anthropic import Anthropic

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

def call_anthropic(prompt):
    """Call Anthropic API"""
    try:
        message = client.messages.create(
            model=os.getenv("ANTHROPIC_MODEL", "claude-opus-4-5"),
            max_tokens=1000,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        return message.content[0].text
    except Exception as e:
        print(f"Error calling Anthropic: {e}")
        return None
```

#### Pricing
- Claude Haiku: $0.80 per 1M input tokens (fastest, cheapest)
- Claude Sonnet: $3 per 1M input tokens (balanced)
- Claude Opus: $15 per 1M input tokens (most powerful)

### Option 2C: GitHub Models (Free Trial + Billing)

#### Setup
```bash
# 1. Get GitHub PAT token
# 2. Install package
pip install requests

# 3. Add to .env
GITHUB_TOKEN=ghp_...
GITHUB_MODEL=meta/llama-3.3-70b-instruct
```

#### Code Implementation
```python
import requests

def call_github_model(prompt):
    """Call GitHub Models API (free trial!)"""
    try:
        response = requests.post(
            "https://models.inference.ai.azure.com/chat/completions",
            headers={"Authorization": f"Bearer {os.getenv('GITHUB_TOKEN')}"},
            json={
                "model": os.getenv("GITHUB_MODEL", "meta/llama-3.3-70b-instruct"),
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1000
            }
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"Error calling GitHub Models: {e}")
        return None
```

#### Pricing
- Free trial available
- Then per-token like others
- Great for development

---

## Option 3: Hybrid Approach (Best for Production)

Use **local + cloud** together:

### Strategy
```
Simple Questions (FAQ, maintenance logs)
    ↓ (Fast + Free)
Ollama (llama3)
    
Complex Questions (Diagnosis, analysis)
    ↓ (Better Quality)
OpenAI/Claude
    
User Toggle
    ↓
"Use Fast Mode" → Ollama
"Use Best Quality" → Claude
```

### Implementation
```python
from enum import Enum
from app.ai.services.knowledge_service import search_knowledge_base

class LLMMode(str, Enum):
    LOCAL = "local"      # Ollama
    CLOUD = "cloud"      # OpenAI/Claude
    AUTO = "auto"        # Decide based on complexity

async def call_llm(prompt, mode=LLMMode.AUTO):
    """Call LLM with mode selection"""
    
    if mode == LLMMode.LOCAL:
        return _call_ollama(prompt)
    
    elif mode == LLMMode.CLOUD:
        return call_openai(prompt)  # or call_anthropic
    
    elif mode == LLMMode.AUTO:
        # Auto-select based on KB quality
        # If high-quality KB match → use local (save cost)
        # If no good KB match → use cloud (better answer)
        confidence = calculate_confidence(kb_entries)
        if confidence > 0.7:
            return _call_ollama(prompt)
        else:
            return call_openai(prompt)

# In router:
@app.post("/chatbot/ask")
async def ask_chatbot(request: ChatbotRequest):
    # Use mode from request, default to AUTO
    mode = getattr(request, 'llm_mode', LLMMode.AUTO)
    answer = await call_llm(prompt, mode=mode)
    # ... rest of processing
```

---

## Comparison Table

| Feature | Ollama | OpenAI | Anthropic | GitHub |
|---------|--------|--------|-----------|--------|
| **Cost** | Free | $0.15-$15/1M | $0.80-$15/1M | Free trial |
| **Speed** | Fast (local) | ~500ms | ~500ms | ~500ms |
| **Quality** | 7/10 | 9/10 | 9/10 | 8/10 |
| **Privacy** | 10/10 | 3/10 | 5/10 | 5/10 |
| **Requires API** | No | Yes | Yes | Yes |
| **Models** | 10+ | 5+ | 4+ | 30+ |
| **Best For** | MVP, Dev | Production | Complex | Testing |
| **Context Window** | 8K | 128K+ | 200K | 128K |

---

## How to Change LLM in PredictiX

### Current: Using Ollama

**File:** `app/routers/chatbot.py`

```python
# Lines 1-20 (Current implementation)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")

def _call_ollama(prompt, timeout=60):
    """Current implementation calling Ollama"""
    # ... code to call Ollama API
```

### Switch to OpenAI

```python
# Option 1: Replace _call_ollama function
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def _call_llm(prompt):
    """Use OpenAI instead"""
    response = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        messages=[
            {"role": "system", "content": "You are a helpful assistant for predictive maintenance..."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7
    )
    return response.choices[0].message.content

# Then update the endpoint to use:
answer = _call_llm(prompt)  # Instead of _call_ollama(prompt)
```

### Switch to Anthropic

```python
from anthropic import Anthropic

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

def _call_llm(prompt):
    """Use Anthropic Claude"""
    message = client.messages.create(
        model=os.getenv("ANTHROPIC_MODEL", "claude-opus-4-5"),
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text

# Then use: answer = _call_llm(prompt)
```

---

## Step-by-Step: Switch from Ollama to OpenAI

### Step 1: Get OpenAI API Key
```
1. Go to https://platform.openai.com
2. Sign up / Log in
3. Create API key → Copy it
4. Set spending limit (important!)
```

### Step 2: Install OpenAI Package
```bash
pip install openai
pip freeze > requirements.txt
```

### Step 3: Add Environment Variable
Create/update `.env`:
```env
OPENAI_API_KEY=sk-proj-abc123...
OPENAI_MODEL=gpt-4o-mini
```

### Step 4: Update Code
File: `app/routers/chatbot.py`

Find this:
```python
def _call_ollama(prompt, timeout=60):
    try:
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={...},
            timeout=timeout
        )
        return response.json().get("response")
```

Replace with:
```python
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def _call_openai(prompt):
    """Call OpenAI API"""
    response = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        messages=[
            {
                "role": "system",
                "content": "You are a helpful assistant for vehicle maintenance and predictive maintenance systems."
            },
            {"role": "user", "content": prompt}
        ],
        temperature=0.7,
        max_tokens=1500
    )
    return response.choices[0].message.content
```

### Step 5: Update Function Call in `/ask` Endpoint
Find:
```python
answer = _call_ollama(prompt)
```

Replace with:
```python
answer = _call_openai(prompt)
```

### Step 6: Update Health Check
Find health endpoint and update:
```python
@router.get("/chatbot/health")
def health_check():
    try:
        # Check OpenAI availability
        response = requests.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}"},
            timeout=5
        )
        openai_available = response.status_code == 200
    except:
        openai_available = False
    
    return ChatbotHealthResponse(
        status="healthy" if openai_available else "degraded",
        ollama_available=False,  # No longer using
        openai_available=openai_available,
        message="Running with OpenAI GPT"
    )
```

### Step 7: Test
```bash
curl -X POST http://localhost:8000/chatbot/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "How often should I rotate tires?"}'
```

---

## Recommended Setup by Use Case

### 🎓 **Learning / Development**
- ✅ **Use Ollama** (llama3)
- Free, private, instant learning
- Perfect for understanding the system

### 🔨 **MVP / Prototype**
- ✅ **Use Ollama** (llama3 or mistral)
- No costs, good enough quality
- Can upgrade later

### 📊 **Production (Small Scale)**
- ✅ **Use Hybrid**
- Local (Ollama) + Claude for complex
- Balance cost and quality

### 🚀 **Production (High Quality)**
- ✅ **Use Claude Opus or GPT-4o**
- Best quality, handles scale
- Monitor costs

### 💰 **Cost-Conscious**
- ✅ **Use GitHub Models** (free trial)
- Or use Ollama for free
- Scale up only when needed

---

## Cost Estimation

### Ollama (Local)
```
Setup: 0 cost
Monthly: 0 cost (+ electricity ~$20)
Conversation: Unlimited
```

### OpenAI
```
Setup: 0 cost (account)
Monthly: ~$50-500 (depending on usage)
Per conversation: ~$0.001-0.01
1000 conversations: ~$1-10
```

### Anthropic Claude
```
Setup: 0 cost
Monthly: ~$50-300
Per conversation: ~$0.005-0.05
1000 conversations: ~$5-50
```

### GitHub Models
```
Setup: Free
Monthly: Free trial, then pay-as-you-go
1000 conversations: ~$1-10
```

---

## Common Issues & Troubleshooting

### Ollama Not Responding
```bash
# Check if server is running
curl http://localhost:11434/api/tags

# Restart if needed
ollama serve

# Check model is loaded
ollama list
```

### OpenAI API Key Invalid
```bash
# Verify key format
echo $OPENAI_API_KEY  # Should start with sk-

# Check in .env file (no quotes)
OPENAI_API_KEY=sk-proj-abc123...

# Check environment variable loaded
python -c "import os; print(os.getenv('OPENAI_API_KEY'))"
```

### Rate Limits
```python
# Add retry logic for cloud APIs
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def call_openai(prompt):
    # ... your code
    pass
```

### Slow Responses
```python
# Increase timeout for slower connections
response = requests.post(
    url,
    json=data,
    timeout=120  # Increase from default 60
)
```

---

## Environment Variables Reference

### For Ollama
```env
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3
```

### For OpenAI
```env
OPENAI_API_KEY=sk-proj-...
OPENAI_MODEL=gpt-4o-mini
```

### For Anthropic
```env
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-opus-4-5
```

### For GitHub
```env
GITHUB_TOKEN=ghp_...
GITHUB_MODEL=meta/llama-3.3-70b-instruct
```

### For Embeddings (Currently Used)
```env
EMBEDDING_MODEL=all-MiniLM-L6-v2
```

---

## Next Steps

1. **Choose Your LLM** - See "Recommended Setup" section above
2. **Follow Setup Steps** - Based on your choice
3. **Update Code** - See "How to Change LLM" section
4. **Test Thoroughly** - Verify responses are good quality
5. **Monitor Costs** - If using cloud API, set budget alerts
6. **Gather Feedback** - Improve prompts based on user feedback

---

## Additional Resources

### Documentation
- **Ollama**: https://ollama.ai
- **OpenAI**: https://platform.openai.com/docs
- **Anthropic**: https://docs.anthropic.com
- **GitHub Models**: https://github.com/marketplace/models

### Your Project Docs
- [CHATBOT_FEATURES.md](CHATBOT_FEATURES.md) - Feature overview
- [KB_CHATBOT_SETUP.md](KB_CHATBOT_SETUP.md) - Setup guide
- [FRONTEND_INTEGRATION.md](FRONTEND_INTEGRATION.md) - Frontend code

---

**Summary:** You already have Ollama + llama3 set up! For production, consider upgrading to OpenAI GPT-4o or Claude Opus for better quality, or stick with Ollama for cost savings. 🚀
