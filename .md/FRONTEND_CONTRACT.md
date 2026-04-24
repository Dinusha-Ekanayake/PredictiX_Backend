# 🔗 Frontend-Backend Contract (Simplified Message API)

## Overview

The **simplified message API** provides a clean, stable contract for frontend integration. It hides the complexity of the RAG system while maintaining all the intelligence underneath.

---

## Quick Start

### Endpoint
```
POST /chatbot/message
```

### Request (Simple & Clean)
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

### Response (Simple & Clean)
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

## Request Schema

### `SimpleMessageRequest`

```typescript
interface SimpleMessageRequest {
  message: string;              // Required: User message/question
  conversation_id?: string;     // Optional: For conversation threading
  context?: {                   // Optional: Context metadata
    page?: string;              // Current page (admin-dashboard, assets, etc.)
    role?: string;              // User role (admin, technician, viewer, etc.)
    asset_id?: string;          // If viewing specific asset
    department_id?: string;     // If in specific department
    extra?: Record<string, any>; // Additional custom fields
  };
}
```

### Field Details

#### `message` (Required)
- **Type:** String
- **Length:** 1-5000 characters
- **Description:** The user's question or message to the chatbot
- **Example:** `"How do I maintain tires?"`, `"What is the status of Asset-123?"`

#### `conversation_id` (Optional)
- **Type:** String
- **Description:** Group related messages into a conversation
- **If omitted:** Backend generates one automatically
- **Format:** Any string, suggested format: `conv_XXXXXXXX` or UUID
- **Use case:** For threading, showing conversation history, etc.
- **Example:** `"conv_abc123def456"`, `"550e8400-e29b-41d4-a716-446655440000"`

#### `context` (Optional)
- **Type:** Object
- **Description:** Contextual information about where request originates
- **Fields:**
  - `page`: Current page/section the user is on
  - `role`: User's role in the system
  - `asset_id`: If viewing/managing a specific asset
  - `department_id`: If working in a specific department
  - `extra`: Any additional custom fields

### Example Requests

#### Simple Question
```json
{
  "message": "What is predictive maintenance?"
}
```

#### Question with Conversation ID
```json
{
  "message": "What should I do next?",
  "conversation_id": "conv_user123_session456"
}
```

#### Question with Context
```json
{
  "message": "What maintenance is due?",
  "conversation_id": "conv_admin_session1",
  "context": {
    "page": "asset-detail",
    "role": "admin",
    "asset_id": "VEHICLE-001"
  }
}
```

#### Full Example
```json
{
  "message": "How many maintenance tickets are overdue?",
  "conversation_id": "conv_user_20260424",
  "context": {
    "page": "maintenance-dashboard",
    "role": "technician",
    "department_id": "dept_fleetops",
    "extra": {
      "vehicle_type": "truck",
      "region": "north"
    }
  }
}
```

---

## Response Schema

### `SimpleMessageResponse`

```typescript
interface SimpleMessageResponse {
  reply: string;                      // Required: Chatbot's answer
  conversation_id: string;            // Required: Conversation ID (generated if not provided)
  message_id: string;                 // Required: Unique message ID for this exchange
  created_at: string;                 // Required: ISO 8601 timestamp
  confidence_score?: number;          // Optional: 0-1 confidence (rounded to 2 decimals)
  used_knowledge_base?: boolean;      // Optional: Whether KB was used
}
```

### Field Details

#### `reply` (Required)
- **Type:** String
- **Description:** The chatbot's answer to the user's message
- **Format:** Plain text, optimized for readability
- **Length:** Typically 50-500 characters, max 5000
- **Example:** `"There are 14 urgent maintenance tickets that need immediate attention."`

#### `conversation_id` (Required)
- **Type:** String
- **Description:** Conversation ID (from request or generated)
- **Format:** `conv_XXXXXXXX` or the one provided in request
- **Use case:** Thread related messages together
- **Example:** `"conv_abc123def"`

#### `message_id` (Required)
- **Type:** String
- **Description:** Unique ID for this specific message/response
- **Format:** `msg_XXXXXXXX`
- **Use case:** Track, log, or reference this specific exchange
- **Example:** `"msg_xyz789uvw"`

#### `created_at` (Required)
- **Type:** String (ISO 8601 datetime)
- **Description:** When the response was generated
- **Format:** `YYYY-MM-DDTHH:MM:SSZ`
- **Example:** `"2026-04-24T10:30:00Z"`

#### `confidence_score` (Optional)
- **Type:** Number
- **Range:** 0.0 - 1.0
- **Precision:** 2 decimal places
- **Description:** How confident the answer is
  - `0.9+`: Very confident (KB had good match)
  - `0.7-0.9`: Confident (KB had reasonable match)
  - `0.5-0.7`: Somewhat confident (general knowledge)
  - `<0.5`: Low confidence (avoid relying on answer)
- **Example:** `0.87`

#### `used_knowledge_base` (Optional)
- **Type:** Boolean
- **Description:** Whether the answer was based on KB (vs. pure LLM)
- **Use case:** Show user where information came from
- **Example:** `true`

### Example Responses

#### Simple Answer
```json
{
  "reply": "Tire maintenance involves checking pressure monthly and rotating every 10,000 km.",
  "conversation_id": "conv_abc123",
  "message_id": "msg_xyz789",
  "created_at": "2026-04-24T10:30:00Z"
}
```

#### With Confidence & KB Info
```json
{
  "reply": "There are 14 urgent maintenance tickets scheduled for today.",
  "conversation_id": "conv_abc123",
  "message_id": "msg_xyz789",
  "created_at": "2026-04-24T10:30:00Z",
  "confidence_score": 0.95,
  "used_knowledge_base": true
}
```

#### Low Confidence Answer
```json
{
  "reply": "I'm not entirely sure, but it might be related to the sensor system.",
  "conversation_id": "conv_abc123",
  "message_id": "msg_xyz789",
  "created_at": "2026-04-24T10:30:00Z",
  "confidence_score": 0.45,
  "used_knowledge_base": false
}
```

---

## API Comparison

### Old API: `/chatbot/ask` (Complex)

**Request:**
```json
{
  "question": "How do I maintain tires?",
  "use_knowledge_base": true,
  "kb_limit": 3,
  "similarity_threshold": 0.3
}
```

**Response:** (Complex, 15+ fields)
```json
{
  "question": "...",
  "summary": "...",
  "detailed_answer": "...",
  "structured_sections": [...],
  "key_points": [...],
  "image_suggestions": [...],
  "related_topics": [...],
  "confidence_score": 0.87,
  "context_entries": [...],
  "used_knowledge_base": true,
  "model": "llama3",
  "timestamp": "..."
}
```

**Best for:** Building rich UIs with sections, images, formatted content

---

### New API: `/chatbot/message` (Simple) ✨

**Request:**
```json
{
  "message": "How do I maintain tires?",
  "conversation_id": "conv_123"
}
```

**Response:** (Simple, 5 core fields)
```json
{
  "reply": "...",
  "conversation_id": "conv_123",
  "message_id": "msg_456",
  "created_at": "2026-04-24T10:30:00Z",
  "confidence_score": 0.87,
  "used_knowledge_base": true
}
```

**Best for:** Simple chat interfaces, quick integrations, mobile apps

---

## Usage Examples

### JavaScript/TypeScript

#### Basic Usage
```javascript
async function askChatbot(message) {
  const response = await fetch('http://localhost:8000/chatbot/message', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message })
  });
  
  const data = await response.json();
  console.log(data.reply);  // "There are 14 urgent tickets today."
  return data;
}

// Usage
askChatbot("How many urgent tickets today?");
```

#### With Conversation Tracking
```javascript
class ChatbotClient {
  constructor() {
    this.conversationId = null;
    this.messages = [];
  }
  
  async sendMessage(message, context = {}) {
    // Generate conversation ID on first message
    if (!this.conversationId) {
      this.conversationId = `conv_${Date.now()}`;
    }
    
    const response = await fetch('http://localhost:8000/chatbot/message', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message,
        conversation_id: this.conversationId,
        context
      })
    });
    
    const data = await response.json();
    
    // Store in local history
    this.messages.push({
      role: 'user',
      content: message,
      id: data.message_id
    });
    this.messages.push({
      role: 'assistant',
      content: data.reply,
      id: data.message_id
    });
    
    return data;
  }
  
  getHistory() {
    return this.messages;
  }
}

// Usage
const chatbot = new ChatbotClient();
await chatbot.sendMessage("What is maintenance?", { page: "dashboard" });
await chatbot.sendMessage("Tell me more", { page: "dashboard" });
console.log(chatbot.getHistory());
```

#### With Error Handling
```javascript
async function sendMessage(message, conversationId = null) {
  try {
    const response = await fetch('http://localhost:8000/chatbot/message', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message,
        conversation_id: conversationId,
        context: {
          page: window.location.pathname,
          role: getUserRole()
        }
      })
    });
    
    if (!response.ok) {
      const error = await response.json();
      console.error('Error:', error.detail);
      return null;
    }
    
    const data = await response.json();
    
    // Use confidence score
    if (data.confidence_score < 0.5) {
      console.warn('Low confidence answer:', data.confidence_score);
    }
    
    return data;
  } catch (error) {
    console.error('Network error:', error);
    return null;
  }
}
```

### React Component

```jsx
import React, { useState } from 'react';

export function ChatWidget() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [conversationId, setConversationId] = useState(null);
  const [loading, setLoading] = useState(false);

  const sendMessage = async () => {
    if (!input.trim()) return;

    setLoading(true);
    
    try {
      const response = await fetch('/chatbot/message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: input,
          conversation_id: conversationId,
          context: {
            page: 'dashboard',
            role: 'admin'
          }
        })
      });

      const data = await response.json();
      
      // Update conversation ID
      setConversationId(data.conversation_id);
      
      // Add messages
      setMessages([
        ...messages,
        { role: 'user', text: input, id: data.message_id },
        { 
          role: 'assistant', 
          text: data.reply, 
          id: data.message_id,
          confidence: data.confidence_score
        }
      ]);
      
      setInput('');
    } catch (error) {
      console.error('Error:', error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="chat-widget">
      <div className="messages">
        {messages.map((msg) => (
          <div key={msg.id} className={`message ${msg.role}`}>
            {msg.text}
            {msg.confidence && (
              <span className="confidence">
                Confidence: {Math.round(msg.confidence * 100)}%
              </span>
            )}
          </div>
        ))}
      </div>
      
      <input
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyPress={(e) => e.key === 'Enter' && sendMessage()}
        placeholder="Ask me anything..."
        disabled={loading}
      />
      <button onClick={sendMessage} disabled={loading}>
        {loading ? 'Thinking...' : 'Send'}
      </button>
    </div>
  );
}
```

### Python/FastAPI Client

```python
import requests
from typing import Optional

class ChatbotClient:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.conversation_id = None
    
    def send_message(
        self,
        message: str,
        context: Optional[dict] = None
    ) -> dict:
        """Send a message to the chatbot."""
        
        payload = {
            "message": message,
            "conversation_id": self.conversation_id,
            "context": context or {}
        }
        
        response = requests.post(
            f"{self.base_url}/chatbot/message",
            json=payload
        )
        response.raise_for_status()
        
        data = response.json()
        
        # Store conversation ID
        self.conversation_id = data["conversation_id"]
        
        return data

# Usage
client = ChatbotClient()

response = client.send_message(
    "How many urgent tickets today?",
    context={
        "page": "admin-dashboard",
        "role": "admin"
    }
)

print(response["reply"])
print(f"Confidence: {response['confidence_score']}")
print(f"Used KB: {response['used_knowledge_base']}")
```

---

## Best Practices

### 1. Always Provide Meaningful Context
```json
{
  "message": "What's the status?",
  "context": {
    "page": "asset-detail",
    "role": "technician",
    "asset_id": "TRUCK-001"
  }
}
```

### 2. Reuse Conversation ID
```javascript
// Don't:
const response1 = await chatbot('/chatbot/message', { message: "Hello" });
const response2 = await chatbot('/chatbot/message', { message: "Tell me more" });

// Do:
const response1 = await chatbot('/chatbot/message', 
  { message: "Hello" });
const response2 = await chatbot('/chatbot/message', 
  { message: "Tell me more", 
    conversation_id: response1.conversation_id });
```

### 3. Check Confidence Before Acting
```javascript
const response = await chatbot.sendMessage(message);

if (response.confidence_score >= 0.7) {
  // Use the answer confidently
  updateUI(response.reply);
} else {
  // Show warning or ask user to verify
  showWarning("This answer has low confidence. Please verify.");
}
```

### 4. Store Message IDs for Logging
```javascript
const response = await chatbot.sendMessage(message);

// Log for analytics
analytics.trackChatMessage({
  conversationId: response.conversation_id,
  messageId: response.message_id,
  timestamp: response.created_at,
  confidence: response.confidence_score
});
```

### 5. Handle Errors Gracefully
```javascript
try {
  const response = await chatbot.sendMessage(message);
  return response.reply;
} catch (error) {
  if (error.status === 503) {
    return "Chatbot is currently unavailable. Please try again later.";
  }
  return "Sorry, I couldn't process that. Please try again.";
}
```

---

## Error Handling

### HTTP Status Codes

| Code | Meaning | Action |
|------|---------|--------|
| `200` | Success | Use response as normal |
| `400` | Bad request | Check message format, context validity |
| `500` | Server error | Retry after delay |
| `503` | Service unavailable | Chatbot/LLM not available, show user message |

### Error Response Format

```json
{
  "detail": "Chatbot service unavailable. Please ensure Ollama is running."
}
```

### Example Error Handling

```javascript
const response = await fetch('/chatbot/message', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ message })
});

if (response.status === 200) {
  const data = await response.json();
  displayReply(data.reply);
} else if (response.status === 503) {
  displayError("Chatbot service unavailable");
} else if (response.status === 400) {
  displayError("Invalid message format");
} else {
  displayError("Unknown error occurred");
}
```

---

## Testing

### Using cURL

```bash
# Simple message
curl -X POST http://localhost:8000/chatbot/message \
  -H "Content-Type: application/json" \
  -d '{"message": "How do I maintain tires?"}'

# With conversation ID
curl -X POST http://localhost:8000/chatbot/message \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Tell me more",
    "conversation_id": "conv_123",
    "context": {
      "page": "dashboard",
      "role": "admin"
    }
  }'
```

### Using Postman

1. **Method:** POST
2. **URL:** `http://localhost:8000/chatbot/message`
3. **Headers:** `Content-Type: application/json`
4. **Body (raw JSON):**
```json
{
  "message": "How many urgent tickets?",
  "conversation_id": "conv_user_123",
  "context": {
    "page": "dashboard",
    "role": "admin"
  }
}
```

### Using Python

```python
import requests

response = requests.post(
    'http://localhost:8000/chatbot/message',
    json={
        'message': 'How do I maintain tires?',
        'context': {
            'page': 'dashboard',
            'role': 'admin'
        }
    }
)

print(response.json())
```

---

## Migration Guide (From /ask to /message)

### Old Endpoint
```javascript
// Old: /ask endpoint (complex response)
const response = await fetch('/chatbot/ask', {
  method: 'POST',
  body: JSON.stringify({
    question: "...",
    use_knowledge_base: true,
    kb_limit: 3
  })
});

const data = await response.json();
console.log(data.summary);
console.log(data.structured_sections);
console.log(data.image_suggestions);
```

### New Endpoint
```javascript
// New: /message endpoint (simple response)
const response = await fetch('/chatbot/message', {
  method: 'POST',
  body: JSON.stringify({
    message: "..."
  })
});

const data = await response.json();
console.log(data.reply);  // Simple, clean answer
```

### Side-by-side Comparison

| Aspect | `/ask` | `/message` |
|--------|--------|-----------|
| **Request** | Complex (5 params) | Simple (1 required param) |
| **Response** | Structured (15+ fields) | Simple (5 core fields) |
| **Use Case** | Rich UIs, formatting | Simple chat, mobile |
| **Learning curve** | Steep | Shallow |
| **Flexibility** | High | Fixed |
| **Conversation tracking** | Manual | Built-in |

---

## Troubleshooting

### "Connection refused" Error
```
Backend is not running. Start it with:
uvicorn app.main:app --reload
```

### "Invalid message format" Error
```
Check that message field is provided and is a string:
✗ { "text": "Hello" }
✓ { "message": "Hello" }
```

### "Chatbot service unavailable"
```
Ollama is not running. Start it with:
ollama serve
```

### Empty or Nonsensical Replies
```
Check confidence_score in response:
- < 0.5: Low confidence, retry or show warning
- > 0.7: Good confidence, safe to use
```

---

## FAQ

**Q: Can I use the old `/ask` endpoint?**
A: Yes, both endpoints are available. Use `/message` for simple chats, `/ask` for rich UIs.

**Q: How do I implement conversation history?**
A: Reuse the `conversation_id` returned in the response for subsequent messages. Frontend can store messages locally using the `message_id`.

**Q: What if I need more complex responses?**
A: Use the `/ask` endpoint which returns structured sections, images, and more detailed information.

**Q: How do I know if the answer is accurate?**
A: Check the `confidence_score` (0-1 scale) and `used_knowledge_base` flag in the response.

**Q: Can I customize the response?**
A: The `/message` endpoint provides simplified responses. Use `/ask` for customization or modify the backend code.

---

## Summary

✅ **Simple Request:** Just send `message`  
✅ **Simple Response:** Get `reply`, `conversation_id`, `message_id`, `created_at`  
✅ **Conversation Tracking:** Reuse `conversation_id`  
✅ **Confidence Indication:** Check `confidence_score`  
✅ **KB Attribution:** See `used_knowledge_base` flag  

---

**Version:** 1.0  
**Status:** ✅ Stable | **Last Updated:** April 24, 2026
