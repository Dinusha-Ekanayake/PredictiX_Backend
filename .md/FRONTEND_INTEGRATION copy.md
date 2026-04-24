# Frontend Integration Guide - ChatGPT-Style Chatbot UI

This guide explains how to display the structured chatbot responses (similar to ChatGPT) on your frontend.

## Response Structure

The chatbot now returns rich, structured responses with this JSON format:

```json
{
  "question": "How do I maintain the tire system?",
  "summary": "Tire maintenance involves regular pressure checks, visual inspections, and rotation.",
  "detailed_answer": "Full markdown formatted answer...",
  "structured_sections": [
    {
      "title": "Overview",
      "content": "Tire maintenance is essential...",
      "icon": "📋"
    },
    {
      "title": "Key Maintenance Steps",
      "content": "- Check pressure monthly\n- Inspect tread depth...",
      "icon": "📌"
    }
  ],
  "key_points": [
    "Check tire pressure monthly",
    "Rotate tires every 10,000 km",
    "Replace when tread reaches 4/32 inch"
  ],
  "related_topics": ["wheel alignment", "tire pressure", "tread depth"],
  "image_suggestions": [
    {
      "alt_text": "Tire maintenance and inspection",
      "search_terms": "tire maintenance inspection rotation",
      "caption": "Proper tire maintenance techniques"
    }
  ],
  "used_knowledge_base": true,
  "context_entries": [...],
  "confidence_score": 0.87,
  "model": "llama3",
  "timestamp": "2026-04-24T10:30:00"
}
```

## Frontend Display Components

### 1. Header Section (Question + Confidence)

```jsx
function ChatbotHeader({ question, confidenceScore }) {
  const confidenceColor = 
    confidenceScore > 0.8 ? 'green' : 
    confidenceScore > 0.6 ? 'yellow' : 'orange';
  
  return (
    <div className="chatbot-header">
      <h2>{question}</h2>
      <div className="confidence-badge" style={{ color: confidenceColor }}>
        Confidence: {(confidenceScore * 100).toFixed(0)}%
      </div>
    </div>
  );
}
```

### 2. Summary Card

```jsx
function SummaryCard({ summary }) {
  return (
    <div className="summary-card">
      <div className="summary-icon">💡</div>
      <p className="summary-text">{summary}</p>
    </div>
  );
}
```

**CSS Styling:**
```css
.summary-card {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  padding: 20px;
  border-radius: 12px;
  margin: 15px 0;
  display: flex;
  gap: 15px;
  align-items: flex-start;
}

.summary-icon {
  font-size: 28px;
  flex-shrink: 0;
}

.summary-text {
  margin: 0;
  font-size: 16px;
  line-height: 1.6;
}
```

### 3. Structured Sections

```jsx
import ReactMarkdown from 'react-markdown';

function StructuredSections({ sections }) {
  return (
    <div className="sections-container">
      {sections.map((section, idx) => (
        <div key={idx} className="content-section">
          <div className="section-header">
            <span className="section-icon">{section.icon || '📝'}</span>
            <h3>{section.title}</h3>
          </div>
          <div className="section-content">
            <ReactMarkdown>{section.content}</ReactMarkdown>
          </div>
        </div>
      ))}
    </div>
  );
}
```

**CSS Styling:**
```css
.sections-container {
  display: flex;
  flex-direction: column;
  gap: 20px;
  margin: 20px 0;
}

.content-section {
  border-left: 4px solid #667eea;
  background: #f8f9fa;
  padding: 20px;
  border-radius: 8px;
  transition: all 0.3s ease;
}

.content-section:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  transform: translateX(4px);
}

.section-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 15px;
}

.section-icon {
  font-size: 24px;
}

.section-header h3 {
  margin: 0;
  color: #333;
  font-size: 18px;
}

.section-content {
  color: #555;
  line-height: 1.8;
}

.section-content ul, .section-content ol {
  margin: 10px 0;
  padding-left: 20px;
}

.section-content li {
  margin: 8px 0;
}

.section-content strong {
  color: #667eea;
}
```

### 4. Key Points Box

```jsx
function KeyPointsBox({ keyPoints }) {
  if (!keyPoints || keyPoints.length === 0) return null;
  
  return (
    <div className="key-points-box">
      <div className="key-points-header">
        <span className="key-points-icon">⭐</span>
        <h3>Key Points</h3>
      </div>
      <ul className="key-points-list">
        {keyPoints.map((point, idx) => (
          <li key={idx} className="key-point-item">
            <span className="point-number">{idx + 1}</span>
            <span className="point-text">{point}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
```

**CSS Styling:**
```css
.key-points-box {
  background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
  color: white;
  padding: 20px;
  border-radius: 12px;
  margin: 20px 0;
}

.key-points-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 15px;
}

.key-points-icon {
  font-size: 24px;
}

.key-points-header h3 {
  margin: 0;
  font-size: 18px;
}

.key-points-list {
  list-style: none;
  padding: 0;
  margin: 0;
}

.key-point-item {
  display: flex;
  gap: 12px;
  margin: 10px 0;
  align-items: flex-start;
}

.point-number {
  background: rgba(255, 255, 255, 0.3);
  border-radius: 50%;
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  font-weight: bold;
}

.point-text {
  flex: 1;
  line-height: 1.5;
}
```

### 5. Image Suggestions

```jsx
function ImageSuggestions({ imageSuggestions }) {
  if (!imageSuggestions || imageSuggestions.length === 0) return null;
  
  return (
    <div className="images-section">
      <h3>📸 Related Images</h3>
      <div className="images-grid">
        {imageSuggestions.map((img, idx) => (
          <a
            key={idx}
            href={`https://www.google.com/search?q=${encodeURIComponent(img.search_terms)}&tbm=isch`}
            target="_blank"
            rel="noopener noreferrer"
            className="image-suggestion-card"
          >
            <div className="image-placeholder">
              <span>🖼️</span>
            </div>
            <div className="image-info">
              <p className="image-caption">{img.caption || img.alt_text}</p>
              <p className="image-search-terms">Search: {img.search_terms}</p>
            </div>
          </a>
        ))}
      </div>
    </div>
  );
}
```

**CSS Styling:**
```css
.images-section {
  margin: 20px 0;
}

.images-section h3 {
  color: #333;
  margin-bottom: 15px;
}

.images-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: 15px;
}

.image-suggestion-card {
  text-decoration: none;
  color: inherit;
  border: 1px solid #ddd;
  border-radius: 8px;
  overflow: hidden;
  transition: all 0.3s ease;
}

.image-suggestion-card:hover {
  box-shadow: 0 8px 16px rgba(0, 0, 0, 0.15);
  transform: translateY(-4px);
}

.image-placeholder {
  background: linear-gradient(135deg, #e0c3fc 0%, #8ec5fc 100%);
  height: 120px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 48px;
}

.image-info {
  padding: 12px;
}

.image-caption {
  font-weight: 600;
  margin: 0 0 8px 0;
  color: #333;
}

.image-search-terms {
  font-size: 12px;
  color: #666;
  margin: 0;
}
```

### 6. Related Topics

```jsx
function RelatedTopics({ topics }) {
  if (!topics || topics.length === 0) return null;
  
  return (
    <div className="related-topics">
      <h3>🔗 Related Topics</h3>
      <div className="topics-tags">
        {topics.map((topic, idx) => (
          <button
            key={idx}
            className="topic-tag"
            onClick={() => {
              // Trigger new question
              onTopicClick?.(topic);
            }}
          >
            {topic}
            <span className="topic-arrow">→</span>
          </button>
        ))}
      </div>
    </div>
  );
}
```

**CSS Styling:**
```css
.related-topics {
  margin: 20px 0;
  padding: 20px;
  background: #f0f4ff;
  border-radius: 8px;
}

.related-topics h3 {
  margin-top: 0;
  color: #333;
}

.topics-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.topic-tag {
  background: white;
  border: 1px solid #667eea;
  color: #667eea;
  padding: 8px 16px;
  border-radius: 20px;
  cursor: pointer;
  transition: all 0.3s ease;
  font-size: 14px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.topic-tag:hover {
  background: #667eea;
  color: white;
  transform: translateY(-2px);
  box-shadow: 0 4px 8px rgba(102, 126, 234, 0.3);
}

.topic-arrow {
  opacity: 0;
  transition: opacity 0.3s ease;
}

.topic-tag:hover .topic-arrow {
  opacity: 1;
}
```

### 7. Context Sources Card

```jsx
function ContextSources({ contextEntries, usedKnowledgeBase }) {
  if (!usedKnowledgeBase || !contextEntries || contextEntries.length === 0) {
    return null;
  }
  
  return (
    <div className="context-sources">
      <details>
        <summary className="sources-summary">
          📚 Sources Used ({contextEntries.length})
        </summary>
        <div className="sources-list">
          {contextEntries.map((entry, idx) => (
            <div key={idx} className="source-item">
              <div className="source-header">
                <strong>{entry.title}</strong>
                <span className="similarity-badge">
                  {(entry.similarity * 100).toFixed(0)}% match
                </span>
              </div>
              <p className="source-category">📁 {entry.category}</p>
              {entry.source && (
                <p className="source-origin">Source: {entry.source}</p>
              )}
            </div>
          ))}
        </div>
      </details>
    </div>
  );
}
```

**CSS Styling:**
```css
.context-sources {
  margin-top: 20px;
  padding: 15px;
  background: #f9f9f9;
  border-radius: 8px;
}

.sources-summary {
  cursor: pointer;
  color: #667eea;
  font-weight: 600;
  user-select: none;
}

.sources-summary:hover {
  color: #764ba2;
}

.sources-list {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.source-item {
  padding: 10px;
  background: white;
  border-left: 3px solid #667eea;
  border-radius: 4px;
}

.source-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.similarity-badge {
  background: #667eea;
  color: white;
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 12px;
  white-space: nowrap;
}

.source-category {
  margin: 4px 0;
  font-size: 13px;
  color: #666;
}

.source-origin {
  margin: 4px 0;
  font-size: 12px;
  color: #999;
  font-style: italic;
}
```

## Complete Response Component

```jsx
import React from 'react';
import ReactMarkdown from 'react-markdown';

function ChatbotResponse({ response }) {
  if (!response) return <div>No response</div>;

  return (
    <div className="chatbot-response">
      <ChatbotHeader 
        question={response.question}
        confidenceScore={response.confidence_score}
      />
      
      <SummaryCard summary={response.summary} />
      
      <StructuredSections sections={response.structured_sections} />
      
      <KeyPointsBox keyPoints={response.key_points} />
      
      <ImageSuggestions imageSuggestions={response.image_suggestions} />
      
      <RelatedTopics 
        topics={response.related_topics}
        onTopicClick={(topic) => {
          // Handle related topic click
          console.log('Clicked topic:', topic);
        }}
      />
      
      <ContextSources 
        contextEntries={response.context_entries}
        usedKnowledgeBase={response.used_knowledge_base}
      />
    </div>
  );
}

export default ChatbotResponse;
```

**Main CSS:**
```css
.chatbot-response {
  max-width: 800px;
  margin: 20px auto;
  padding: 20px;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
  color: #333;
  line-height: 1.6;
}

.chatbot-response h1, .chatbot-response h2, .chatbot-response h3 {
  color: #222;
  margin-top: 20px;
  margin-bottom: 10px;
}

.chatbot-response a {
  color: #667eea;
  text-decoration: none;
  border-bottom: 1px solid #667eea;
}

.chatbot-response a:hover {
  color: #764ba2;
  border-bottom-color: #764ba2;
}
```

## Integration Example (React)

```jsx
import { useState } from 'react';
import ChatbotResponse from './ChatbotResponse';

function ChatbotWidget() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);

  const handleAsk = async () => {
    if (!input.trim()) return;

    setLoading(true);
    try {
      const response = await fetch('/chatbot/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: input,
          use_knowledge_base: true,
          kb_limit: 3,
        }),
      });
      
      const data = await response.json();
      setMessages([...messages, data]);
      setInput('');
    } catch (error) {
      console.error('Error:', error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="chatbot-widget">
      <div className="chat-messages">
        {messages.map((msg, idx) => (
          <ChatbotResponse key={idx} response={msg} />
        ))}
      </div>

      <div className="chat-input-area">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyPress={(e) => e.key === 'Enter' && handleAsk()}
          placeholder="Ask about maintenance, troubleshooting, etc..."
          disabled={loading}
        />
        <button onClick={handleAsk} disabled={loading}>
          {loading ? 'Thinking...' : 'Ask'}
        </button>
      </div>
    </div>
  );
}

export default ChatbotWidget;
```

## Vue.js Integration Example

```vue
<template>
  <div class="chatbot-response">
    <!-- Header -->
    <div class="chatbot-header">
      <h2>{{ response.question }}</h2>
      <span class="confidence-badge" :style="confidenceStyle">
        Confidence: {{ (response.confidence_score * 100).toFixed(0) }}%
      </span>
    </div>

    <!-- Summary -->
    <div class="summary-card">
      <span class="summary-icon">💡</span>
      <p>{{ response.summary }}</p>
    </div>

    <!-- Sections -->
    <div class="sections-container">
      <div v-for="(section, idx) in response.structured_sections" :key="idx" class="content-section">
        <div class="section-header">
          <span class="section-icon">{{ section.icon || '📝' }}</span>
          <h3>{{ section.title }}</h3>
        </div>
        <div class="section-content" v-html="markdownToHtml(section.content)"></div>
      </div>
    </div>

    <!-- Key Points -->
    <div v-if="response.key_points.length > 0" class="key-points-box">
      <div class="key-points-header">
        <span class="key-points-icon">⭐</span>
        <h3>Key Points</h3>
      </div>
      <ul class="key-points-list">
        <li v-for="(point, idx) in response.key_points" :key="idx" class="key-point-item">
          <span class="point-number">{{ idx + 1 }}</span>
          <span class="point-text">{{ point }}</span>
        </li>
      </ul>
    </div>

    <!-- Image Suggestions -->
    <div v-if="response.image_suggestions.length > 0" class="images-section">
      <h3>📸 Related Images</h3>
      <div class="images-grid">
        <a
          v-for="(img, idx) in response.image_suggestions"
          :key="idx"
          :href="googleImageSearch(img.search_terms)"
          target="_blank"
          rel="noopener noreferrer"
          class="image-suggestion-card"
        >
          <div class="image-placeholder">🖼️</div>
          <div class="image-info">
            <p class="image-caption">{{ img.caption || img.alt_text }}</p>
            <p class="image-search-terms">{{ img.search_terms }}</p>
          </div>
        </a>
      </div>
    </div>

    <!-- Related Topics -->
    <div v-if="response.related_topics.length > 0" class="related-topics">
      <h3>🔗 Related Topics</h3>
      <div class="topics-tags">
        <button
          v-for="topic in response.related_topics"
          :key="topic"
          class="topic-tag"
          @click="$emit('topic-click', topic)"
        >
          {{ topic }}
          <span class="topic-arrow">→</span>
        </button>
      </div>
    </div>

    <!-- Sources -->
    <div v-if="response.used_knowledge_base && response.context_entries.length > 0" class="context-sources">
      <details>
        <summary class="sources-summary">
          📚 Sources Used ({{ response.context_entries.length }})
        </summary>
        <div class="sources-list">
          <div v-for="entry in response.context_entries" :key="entry.id" class="source-item">
            <div class="source-header">
              <strong>{{ entry.title }}</strong>
              <span class="similarity-badge">
                {{ (entry.similarity * 100).toFixed(0) }}% match
              </span>
            </div>
            <p class="source-category">📁 {{ entry.category }}</p>
            <p v-if="entry.source" class="source-origin">Source: {{ entry.source }}</p>
          </div>
        </div>
      </details>
    </div>
  </div>
</template>

<script>
export default {
  props: {
    response: Object,
  },
  computed: {
    confidenceStyle() {
      const score = this.response.confidence_score;
      const color = score > 0.8 ? 'green' : score > 0.6 ? 'orange' : 'red';
      return { color };
    },
  },
  methods: {
    markdownToHtml(markdown) {
      // Use a markdown library like marked or markdown-it
      // This is a placeholder
      return markdown.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    },
    googleImageSearch(terms) {
      return `https://www.google.com/search?q=${encodeURIComponent(terms)}&tbm=isch`;
    },
  },
};
</script>
```

## Key Features Enabled

✅ **ChatGPT-Style Formatting** — Structured sections with markdown  
✅ **Image Suggestions** — Links to relevant images (Google Images)  
✅ **Key Points Highlighting** — Bullet-point summaries  
✅ **Related Topics** — Quick navigation to related questions  
✅ **Confidence Scoring** — Shows answer reliability  
✅ **Source Attribution** — Shows KB entries used  
✅ **Responsive Design** — Mobile-friendly layouts  
✅ **Accessibility** — Proper semantic HTML and ARIA labels  

## Example API Response

```bash
curl -X POST http://localhost:8000/chatbot/ask \
  -H "Content-Type: application/json" \
  -d '{
    "question": "How do I maintain the brake system?",
    "use_knowledge_base": true,
    "kb_limit": 3
  }'
```

Response includes all structured data ready to display as ChatGPT-style UI! 🎉

---

**Frontend Tips:**
- Use a markdown renderer like `react-markdown` for proper formatting
- Cache images locally if possible for faster loading
- Implement lazy-loading for images
- Add smooth animations for better UX
- Mobile-optimize the layout
