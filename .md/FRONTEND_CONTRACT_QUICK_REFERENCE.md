# 🔗 Simplified Frontend Contract - Quick Reference

## What's New?

A **simplified, stable API contract** for frontend-backend communication:

```
OLD (Complex): /chatbot/ask
NEW (Simple):  /chatbot/message ✨
```

---

## One-Minute Overview

### Frontend Sends ➡️
```json
{
  "message": "How many urgent tickets today?",
  "conversation_id": "optional-conv-123",
  "context": {
    "page": "admin-dashboard",
    "role": "admin"
  }
}
```

### Backend Responds ⬅️
```json
{
  "reply": "There are 14 urgent tickets today.",
  "conversation_id": "conv_123",
  "message_id": "msg_456",
  "created_at": "2026-04-24T10:30:00Z",
  "confidence_score": 0.87,
  "used_knowledge_base": true
}
```

---

## Endpoint

### URL
```
POST /chatbot/message
```

### Base URL
```
http://localhost:8000/chatbot/message
```

---

## Request Fields

| Field | Required? | Type | Description |
|-------|-----------|------|-------------|
| `message` | ✅ YES | string | User's question or message |
| `conversation_id` | ❌ NO | string | Group messages (auto-generated if omitted) |
| `context.page` | ❌ NO | string | Current page (admin-dashboard, assets, etc.) |
| `context.role` | ❌ NO | string | User role (admin, technician, viewer) |
| `context.asset_id` | ❌ NO | string | Specific asset being viewed |
| `context.department_id` | ❌ NO | string | Specific department context |

---

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `reply` | string | The chatbot's answer |
| `conversation_id` | string | Conversation ID (for threading) |
| `message_id` | string | Unique ID for this exchange |
| `created_at` | datetime | ISO 8601 timestamp |
| `confidence_score` | number | 0-1 confidence (optional) |
| `used_knowledge_base` | boolean | Whether KB was used (optional) |

---

## Code Examples

### JavaScript (Vanilla)
```javascript
const response = await fetch('http://localhost:8000/chatbot/message', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    message: "How do I maintain tires?"
  })
});

const data = await response.json();
console.log(data.reply);  // "Tire maintenance involves..."
```

### React
```jsx
const [reply, setReply] = useState('');

const sendMessage = async (message) => {
  const response = await fetch('/chatbot/message', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message })
  });
  const data = await response.json();
  setReply(data.reply);
};
```

### Python
```python
import requests

response = requests.post(
    'http://localhost:8000/chatbot/message',
    json={'message': 'How do I maintain tires?'}
)

data = response.json()
print(data['reply'])
```

### cURL
```bash
curl -X POST http://localhost:8000/chatbot/message \
  -H "Content-Type: application/json" \
  -d '{"message": "How do I maintain tires?"}'
```

---

## Conversation Tracking

### Track Conversations
```javascript
// First message (auto-generates conversation_id)
const response1 = await fetch('/chatbot/message', {
  method: 'POST',
  body: JSON.stringify({ message: "What is maintenance?" })
});
const convId = response1.json().conversation_id;

// Second message (reuse conversation_id)
const response2 = await fetch('/chatbot/message', {
  method: 'POST',
  body: JSON.stringify({
    message: "Tell me more",
    conversation_id: convId
  })
});
```

### Store Conversation History (Frontend)
```javascript
const conversationHistory = [];

const response = await fetch('/chatbot/message', {
  method: 'POST',
  body: JSON.stringify({ message })
});

const data = await response.json();

conversationHistory.push({
  role: 'user',
  content: message,
  id: data.message_id
});

conversationHistory.push({
  role: 'assistant',
  content: data.reply,
  id: data.message_id,
  confidence: data.confidence_score
});
```

---

## Response Quality

### Confidence Score
```
0.9+  → Very high confidence (use without hesitation)
0.7-0.9 → Good confidence (can use reliably)
0.5-0.7 → Medium confidence (verify if important)
<0.5  → Low confidence (ask user to verify)
```

### Check Knowledge Base Usage
```javascript
const data = await response.json();

if (data.used_knowledge_base) {
  // Answer is backed by knowledge base
  console.log("Sourced from knowledge base");
} else {
  // Answer is from LLM without KB context
  console.log("Based on general knowledge");
}
```

---

## Error Handling

### Check Status
```javascript
const response = await fetch('/chatbot/message', {
  method: 'POST',
  body: JSON.stringify({ message })
});

if (response.ok) {
  const data = await response.json();
  console.log(data.reply);
} else if (response.status === 503) {
  console.error("Chatbot unavailable - is Ollama running?");
} else {
  const error = await response.json();
  console.error("Error:", error.detail);
}
```

---

## Common Request/Response Patterns

### Simple Question
```json
Request:
{
  "message": "What is predictive maintenance?"
}

Response:
{
  "reply": "Predictive maintenance uses data...",
  "conversation_id": "conv_abc123",
  "message_id": "msg_xyz789",
  "created_at": "2026-04-24T10:30:00Z"
}
```

### Question with Context
```json
Request:
{
  "message": "What maintenance is overdue?",
  "context": {
    "page": "asset-detail",
    "asset_id": "TRUCK-001",
    "role": "technician"
  }
}

Response:
{
  "reply": "Based on Asset TRUCK-001, tire rotation is overdue...",
  "conversation_id": "conv_def456",
  "message_id": "msg_uvw012",
  "created_at": "2026-04-24T10:32:00Z",
  "confidence_score": 0.92,
  "used_knowledge_base": true
}
```

### Conversation Follow-up
```json
First Request:
{
  "message": "How do I check tire pressure?"
}

First Response:
{
  "reply": "...",
  "conversation_id": "conv_ghi789",
  "message_id": "msg_abc123"
}

Second Request (same conversation):
{
  "message": "How often should I do this?",
  "conversation_id": "conv_ghi789"
}

Second Response:
{
  "reply": "...",
  "conversation_id": "conv_ghi789",
  "message_id": "msg_def456"
}
```

---

## Differences: `/ask` vs `/message`

| Aspect | `/ask` (Old) | `/message` (New) |
|--------|-------------|-----------------|
| **Endpoint** | Complex | Simple |
| **Request Fields** | 4-5 fields | 1 required field |
| **Response Fields** | 15+ fields | 5 core fields |
| **Sections/Formatting** | Detailed structure | Plain text |
| **Images** | Included | Not included |
| **Key Points** | Included | Not included |
| **Conversation** | Manual tracking | Built-in |
| **Best For** | Rich UIs | Chat interfaces |
| **Learning Curve** | Steep | Shallow |

### When to Use Which?

**Use `/message` when:**
- Building simple chat interface
- Mobile app
- Don't need structured formatting
- Want simplest integration
- Need conversation threading

**Use `/ask` when:**
- Building rich, formatted UI
- Need sections and key points
- Want image suggestions
- Need maximum flexibility
- Building ChatGPT-like interface

---

## Testing

### Using cURL
```bash
# Simple
curl -X POST http://localhost:8000/chatbot/message \
  -H "Content-Type: application/json" \
  -d '{"message":"Hello"}'

# With context
curl -X POST http://localhost:8000/chatbot/message \
  -H "Content-Type: application/json" \
  -d '{
    "message":"Hello",
    "context":{"page":"dashboard","role":"admin"}
  }'
```

### Check if API is Working
```javascript
const testMessage = async () => {
  try {
    const response = await fetch('http://localhost:8000/chatbot/message', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: 'test' })
    });
    
    if (response.ok) {
      console.log('✅ API is working');
      return true;
    } else {
      console.error(`❌ API error: ${response.status}`);
      return false;
    }
  } catch (error) {
    console.error('❌ Connection error:', error);
    return false;
  }
};
```

---

## Prerequisites

1. **Backend running:**
   ```bash
   uvicorn app.main:app --reload
   ```

2. **Ollama running:**
   ```bash
   ollama serve
   ```

3. **Knowledge Base (optional):**
   - Set up Supabase with pgvector
   - Or use without KB (still works, just LLM)

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| **Connection refused** | Start FastAPI: `uvicorn app.main:app --reload` |
| **Service unavailable** | Start Ollama: `ollama serve` |
| **Invalid message format** | Ensure `message` field is a string |
| **Low confidence answers** | Check `confidence_score` field |
| **Slow responses** | Normal for first run, check Ollama status |

---

## File Reference

**New schemas:**
- `app/schemas/chatbot.py` - Added `SimpleMessageRequest`, `SimpleMessageResponse`, `ConversationContext`

**New endpoint:**
- `app/routers/chatbot.py` - Added `POST /chatbot/message`

**Documentation:**
- `FRONTEND_CONTRACT.md` - Complete guide (this file's full version)

---

## Next Steps

1. **Test the endpoint:**
   ```bash
   curl -X POST http://localhost:8000/chatbot/message \
     -H "Content-Type: application/json" \
     -d '{"message": "Hello"}'
   ```

2. **View API docs:**
   ```
   http://localhost:8000/docs
   ```

3. **Build frontend:**
   - Use examples from this guide
   - Reference `FRONTEND_CONTRACT.md` for more details

4. **Integrate into your app:**
   - Copy request/response patterns
   - Track conversations with `conversation_id`
   - Use `confidence_score` to show quality

---

## Summary

✅ **Simple Request:** Just send `message`  
✅ **Simple Response:** Get `reply`, `conversation_id`, `message_id`  
✅ **Conversation Tracking:** Built-in with `conversation_id`  
✅ **Quality Indicator:** Check `confidence_score`  
✅ **Production Ready:** Error handling, validation, logging included  

---

**Quick Links:**
- Full Guide: [FRONTEND_CONTRACT.md](FRONTEND_CONTRACT.md)
- Endpoint: `POST /chatbot/message`
- Docs: `http://localhost:8000/docs`

---

**Version:** 1.0 | **Status:** ✅ Stable | **Date:** April 24, 2026
