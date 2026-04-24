# ⚡ LLM Quick Reference - PredictiX

## Current Status

✅ **You have Ollama + llama3 running**

```
Chatbot → Ollama (llama3) on localhost:11434
Embeddings → SentenceTransformers (local)
Knowledge Base → Supabase + pgvector
```

---

## Quick Switch Guide

### 1️⃣ Stay with Ollama (Recommended for MVP)

**What to do:** Nothing! Already working. ✅

**Test it:**
```bash
curl -X POST http://localhost:8000/chatbot/ask \
  -d '{"question": "How do I maintain tires?"}'
```

**Cost:** Free  
**Quality:** 7/10  
**Speed:** Fast (local)

---

### 2️⃣ Switch to OpenAI (GPT-4o)

#### Quick Setup (5 minutes)

**Step 1:** Get API key
```
→ https://platform.openai.com/api/keys
→ Create key → Copy
```

**Step 2:** Install & configure
```bash
pip install openai
```

Add to `.env`:
```env
OPENAI_API_KEY=sk-proj-...
OPENAI_MODEL=gpt-4o-mini
```

**Step 3:** Update `app/routers/chatbot.py`

Find this line (~line 20):
```python
def _call_ollama(prompt, timeout=60):
```

Replace whole function with:
```python
from openai import OpenAI

_openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def _call_ollama(prompt, timeout=60):
    """Now calls OpenAI instead of Ollama"""
    try:
        response = _openai_client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": "You are a helpful assistant for vehicle maintenance and predictive maintenance."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=1500,
            timeout=timeout
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Error calling OpenAI: {e}")
        return None
```

**Step 4:** Test
```bash
curl -X POST http://localhost:8000/chatbot/ask \
  -d '{"question": "How do I maintain tires?"}'
```

**Cost:** ~$0.10-1.00 per 100 questions  
**Quality:** 9/10  
**Speed:** ~1 second (network)

---

### 3️⃣ Switch to Claude (Anthropic)

#### Quick Setup (5 minutes)

**Step 1:** Get API key
```
→ https://console.anthropic.com
→ Create key → Copy
```

**Step 2:** Install & configure
```bash
pip install anthropic
```

Add to `.env`:
```env
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-opus-4-5
```

**Step 3:** Update `app/routers/chatbot.py`

Replace `_call_ollama` function with:
```python
from anthropic import Anthropic

_anthropic_client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

def _call_ollama(prompt, timeout=60):
    """Now calls Anthropic Claude instead of Ollama"""
    try:
        message = _anthropic_client.messages.create(
            model=os.getenv("ANTHROPIC_MODEL", "claude-opus-4-5"),
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}]
        )
        return message.content[0].text
    except Exception as e:
        print(f"Error calling Anthropic: {e}")
        return None
```

**Step 4:** Test
```bash
curl -X POST http://localhost:8000/chatbot/ask \
  -d '{"question": "How do I maintain tires?"}'
```

**Cost:** ~$0.10-0.50 per 100 questions  
**Quality:** 9.5/10 (Best)  
**Speed:** ~1 second

---

### 4️⃣ Switch to GitHub Models (Free Trial!)

#### Quick Setup (5 minutes)

**Step 1:** Get GitHub token
```
→ https://github.com/settings/tokens
→ Create token (read:packages)
→ Copy
```

**Step 2:** Install dependency
```bash
# Already have requests
pip freeze | grep requests
```

Add to `.env`:
```env
GITHUB_TOKEN=ghp_...
GITHUB_MODEL=meta/llama-3.3-70b-instruct
```

**Step 3:** Update `app/routers/chatbot.py`

Replace `_call_ollama` with:
```python
def _call_ollama(prompt, timeout=60):
    """Now calls GitHub Models instead of Ollama"""
    try:
        response = requests.post(
            "https://models.inference.ai.azure.com/chat/completions",
            headers={
                "Authorization": f"Bearer {os.getenv('GITHUB_TOKEN')}",
                "Content-Type": "application/json"
            },
            json={
                "model": os.getenv("GITHUB_MODEL", "meta/llama-3.3-70b-instruct"),
                "messages": [
                    {"role": "system", "content": "You are a helpful assistant for vehicle maintenance."},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 1500
            },
            timeout=timeout
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"Error calling GitHub Models: {e}")
        return None
```

**Step 4:** Test
```bash
curl -X POST http://localhost:8000/chatbot/ask \
  -d '{"question": "How do I maintain tires?"}'
```

**Cost:** Free trial, then ~$0.10 per 100 questions  
**Quality:** 8/10  
**Speed:** ~1 second

---

## Model Options Reference

### Ollama (Local)
```
llama3              ← Current (FAST ⚡)
llama3:70b          (Better quality, slower)
mistral             (Fast, good)
neural-chat         (Optimized for chat)
dolphin-mixtral     (Powerful)
```

### OpenAI
```
gpt-4o-mini         ← Recommended (cheap + good)
gpt-4o              (More expensive, better)
gpt-5-mini          (Newest, cheap)
gpt-5               (Best quality, expensive)
```

### Anthropic
```
claude-haiku-4-5    (Fast, cheap)
claude-sonnet-4-5   (Balanced)
claude-opus-4-5     ← Best quality
```

### GitHub
```
meta/llama-3.3-70b-instruct
meta/llama-3.1-405b-instruct
mistral/mistral-large-2411
cohere/cohere-command-r-plus
```

---

## Decision Matrix

```
┌─────────────────────────────────────────────────────────────┐
│ Pick your scenario:                                          │
├─────────────────────────────────────────────────────────────┤
│ 1. Just learning? → Ollama (FREE, local)                    │
│ 2. MVP/Prototype? → Ollama (FREE)                           │
│ 3. Need best quality? → Claude Opus ($$$)                   │
│ 4. Want cost-effective? → GitHub Models + Claude Sonnet ($) │
│ 5. Testing cloud? → GitHub Models (FREE trial)              │
│ 6. Production scale? → OpenAI GPT-4o ($$)                   │
└─────────────────────────────────────────────────────────────┘
```

---

## Environment Variables Cheat Sheet

### Ollama (Current)
```env
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3
```

### OpenAI
```env
OPENAI_API_KEY=sk-proj-abc123...
OPENAI_MODEL=gpt-4o-mini
```

### Anthropic
```env
ANTHROPIC_API_KEY=sk-ant-abc123...
ANTHROPIC_MODEL=claude-opus-4-5
```

### GitHub
```env
GITHUB_TOKEN=ghp_abc123...
GITHUB_MODEL=meta/llama-3.3-70b-instruct
```

---

## Pricing Quick Reference

| LLM | Per 1M Tokens | Per 100 Questions |
|-----|---|---|
| Ollama | $0 | $0 |
| GitHub (free trial) | $0 | $0 |
| Claude Haiku | $0.80 | $0.001 |
| Claude Sonnet | $3 | $0.004 |
| GPT-4o mini | $0.15 | $0.0002 |
| GPT-4o | $2.50 | $0.003 |
| Claude Opus | $15 | $0.020 |

---

## Testing Commands

### Test Current LLM
```bash
curl -X POST http://localhost:8000/chatbot/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What is predictive maintenance?", "use_knowledge_base": true}'
```

### Check Health
```bash
curl http://localhost:8000/chatbot/health
```

### Search Knowledge Base
```bash
curl -X POST http://localhost:8000/chatbot/search-kb \
  -H "Content-Type: application/json" \
  -d '{"query": "tire maintenance", "limit": 3}'
```

---

## Troubleshooting

### "Connection refused" error
**Ollama problem:**
```bash
ollama serve  # Start Ollama if not running
```

### "Invalid API key" error
**Cloud problem:**
- Check `.env` file has correct key
- Verify key format (should start with `sk-` or `ghp_`)
- Check key is not expired/revoked
- Verify permissions/scopes

### Slow responses
**Solutions:**
1. Use faster model (gpt-4o-mini, claude-haiku)
2. Increase timeout in code (timeout=120)
3. Use local Ollama (no network latency)

### High costs
**Solutions:**
1. Use cheaper model (gpt-4o-mini, claude-haiku)
2. Use Ollama (free)
3. Use GitHub free trial
4. Limit max_tokens (currently 1500)

---

## File to Modify

All LLM changes go in ONE file:

**`app/routers/chatbot.py`**

Specifically, modify the `_call_ollama()` function (around line 20-40).

---

## Minimal Change Example

### Current (Ollama):
```python
def _call_ollama(prompt, timeout=60):
    response = requests.post(f"{OLLAMA_BASE_URL}/api/generate", ...)
    return response.json().get("response")
```

### To Use OpenAI (3-line change):
```python
from openai import OpenAI
_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def _call_ollama(prompt, timeout=60):
    response = _client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content
```

---

## Recommended: Start with Ollama

✅ **Best for now:**
- No costs
- No API keys needed  
- Privacy (local)
- Fast responses
- Good enough quality for MVP

**When to upgrade:**
- Quality becomes issue
- Need better reasoning
- Ready for production
- Have budget for API calls

---

## Quick Migration Path

1. **Week 1-2:** Use Ollama (learn system)
2. **Week 3:** Try GitHub free trial (test cloud)
3. **Week 4+:** Upgrade to Claude/GPT based on needs

---

## Questions?

See detailed guide: **[LLM_INTEGRATION_GUIDE.md](LLM_INTEGRATION_GUIDE.md)**

---

**TL;DR:** You have Ollama working. To switch, change the `_call_ollama()` function in `app/routers/chatbot.py`. Done! 🚀
