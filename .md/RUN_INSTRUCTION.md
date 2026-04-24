# PredictiX Chatbot Integration - Run Instructions

## Overview
This guide explains how to run both the FastAPI backend and Next.js frontend for the PredictiX chatbot integration.

**Current Setup:**
- Backend: FastAPI (Python) running on `http://localhost:8002`
- Frontend: Next.js (React) running on `http://localhost:3000`
- Chatbot API Endpoint: `POST http://localhost:8002/chatbot/ask`

---

## Prerequisites

### Backend
- Python 3.12+
- Virtual environment (`.venv` folder exists)
- Dependencies installed from `requirements.txt`
- `.env` file configured with:
  - `GROQ_API_KEY`
  - `SUPABASE_URL`
  - `SUPABASE_KEY`
  - `DATABASE_URL`
  - `JWT_SECRET`

### Frontend
- Node.js 18+
- npm or yarn package manager
- Dependencies installed from `package.json`

---

## Running the Backend

### Step 1: Navigate to Backend Directory
```bash
cd c:\Users\USER\Desktop\chakablast\PredictiX_backend
```

### Step 2: Start the Backend Server
Use this exact command:
```cmd
cmd /c ".venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8002"
```

**Alternative (from PowerShell):**
```powershell
& ".\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8002
```

### Step 3: Verify Backend is Running
You should see:
```
INFO:     Uvicorn running on http://127.0.0.1:8002 (Press CTRL+C to quit)
```

The backend will:
1. Load environment variables from `.env`
2. Load PredictiX ML models (~3-5 seconds)
3. Initialize Supabase connection
4. Start listening on port 8002

---

## Running the Frontend

### Step 1: Navigate to Frontend Directory
```bash
cd c:\Users\USER\Desktop\chakablast\PredictiX-Frontend\PredictiX-Frontend
```

### Step 2: Start the Development Server
```bash
npm run dev
```

### Step 3: Verify Frontend is Running
You should see:
```
✓ Ready in 949ms
- Local:         http://localhost:3000
```

### Step 4: Open in Browser
Navigate to: `http://localhost:3000`

---

## Testing the Chatbot Integration

1. **Ensure both servers are running**:
   - Backend terminal showing: `INFO: Uvicorn running on http://127.0.0.1:8002`
   - Frontend terminal showing: `✓ Ready in Xms` on port 3000

2. **Open frontend in browser**:
   - Go to http://localhost:3000
   - Look for the floating chat widget (circular button with message icon)

3. **Send a test message**:
   - Click the floating chat button
   - Type a question (e.g., "What is vehicle maintenance?")
   - Send the message
   - Wait for the response

4. **Verify response**:
   - You should see the bot's answer
   - Below the answer, source badges should appear (if available)
   - Click a source badge to see source title in the input

---

## Port Configuration

The chatbot endpoint is configured in: 
`src/lib/apiClient.ts`

```typescript
export async function askChatbot(question: string): Promise<ChatbotAskResponse> {
  const response = await fetch("http://localhost:8002/chatbot/ask", {
    // ...
  });
}
```

**If you change the backend port from 8002:**
1. Stop both servers
2. Edit `src/lib/apiClient.ts` 
3. Change `8002` to your new port
4. Restart both servers

---

## Troubleshooting

### Backend Won't Start
**Error**: `ERROR: [Errno 10048] error while attempting to bind on address ('127.0.0.1', 8002)`
- **Solution**: Port 8002 is in use. Find and kill the process:
  ```cmd
  netstat -ano | findstr :8002
  taskkill /PID <PID> /F
  ```
- Or use a different port: change `8002` to `8003` (and update frontend)

**Error**: `ModuleNotFoundError: No module named 'app'`
- **Solution**: Ensure you're in the correct directory:
  ```bash
  cd c:\Users\USER\Desktop\chakablast\PredictiX_backend
  ```

**Error**: `ModuleNotFoundError: No module named 'dotenv'` or other import errors
- **Solution**: Reinstall dependencies:
  ```bash
  cd c:\Users\USER\Desktop\chakablast\PredictiX_backend
  .venv\Scripts\pip.exe install -r requirements.txt
  ```

### Frontend Won't Start
**Error**: `Port 3000 is in use by process`
- **Solution**: Kill the process:
  ```cmd
  taskkill /PID <PID> /F
  ```
- Or use a different port by editing Next.js config

**Error**: `Cannot find module` or TypeScript errors
- **Solution**: Reinstall dependencies:
  ```bash
  cd c:\Users\USER\Desktop\chakablast\PredictiX-Frontend\PredictiX-Frontend
  npm install
  ```

### Chatbot Returns "Unable to reach the chatbot service"
- **Verify backend is running**: Check terminal shows `Uvicorn running on http://127.0.0.1:8002`
- **Check port number**: Ensure frontend `apiClient.ts` uses the correct port
- **Check browser console**: Open DevTools (F12) → Console tab for detailed error messages

### Backend Loads Slowly
The first startup includes:
- Loading ML models (~3-5 seconds)
- Initializing Supabase connection (~1-2 seconds)
- This is normal; only happens once per session

---

## File Locations

| File | Purpose | Location |
|------|---------|----------|
| Backend main | FastAPI application | `PredictiX_backend/app/main.py` |
| Chatbot router | Chat endpoint | `PredictiX_backend/app/routers/chatbot.py` |
| API client | Frontend API calls | `PredictiX-Frontend/.../src/lib/apiClient.ts` |
| Chat component | UI widget | `PredictiX-Frontend/.../src/components/chat/FloatingChatbot.tsx` |
| Environment | Backend config | `PredictiX_backend/.env` |

---

## API Contract

### Request
```bash
POST http://localhost:8002/chatbot/ask
Content-Type: application/json

{
  "question": "What is vehicle maintenance?"
}
```

### Response
```json
{
  "answer": "Vehicle maintenance is...",
  "sources": [
    {
      "title": "Maintenance Guide",
      "category": "documentation"
    }
  ]
}
```

---

## Development Workflow

### Daily Development
1. **Terminal 1 - Backend**:
   ```cmd
   cd c:\Users\USER\Desktop\chakablast\PredictiX_backend
   cmd /c ".venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8002"
   ```

2. **Terminal 2 - Frontend**:
   ```bash
   cd c:\Users\USER\Desktop\chakablast\PredictiX-Frontend\PredictiX-Frontend
   npm run dev
   ```

3. **Browser**:
   - Open http://localhost:3000
   - Changes to React/TypeScript reload automatically (Turbopack)
   - Backend changes require restart (Ctrl+C, then run again)

### Making Changes
- **Backend logic**: Edit `app/routers/chatbot.py` → Restart backend
- **Frontend UI**: Edit `src/components/chat/FloatingChatbot.tsx` → Auto-reload
- **API endpoint**: Edit `src/lib/apiClient.ts` → Auto-reload
- **Backend configuration**: Edit `.env` → Restart backend

---

## Next Steps

### After Verification
1. Customize the chatbot behavior in `app/routers/chatbot.py`
2. Style the floating widget in `src/components/chat/FloatingChatbot.tsx`
3. Add authentication to chatbot endpoint if needed
4. Deploy to production using appropriate deployment strategy

### Production Deployment
- Change API endpoint from `localhost:8002` to your production server
- Use environment variables for configuration
- Enable CORS for frontend domain
- Implement rate limiting on chatbot endpoint
- Add error logging and monitoring

---

## Support & Debugging

**Check backend logs**:
- Backend terminal shows all requests and errors
- Look for `POST /chatbot/ask` entries for chat requests

**Check frontend logs**:
- Open browser DevTools (F12)
- Console tab shows network requests and JavaScript errors
- Network tab shows actual HTTP requests/responses

**Enable debug logging** (add to FloatingChatbot.tsx):
```typescript
console.log('Sending question:', question);
console.log('Response:', response);
```

---

## Summary

| Service | Port | Command | Status |
|---------|------|---------|--------|
| Backend (FastAPI) | 8002 | `cmd /c ".venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8002"` | ✓ Running |
| Frontend (Next.js) | 3000 | `npm run dev` | ✓ Running |
| Browser | 3000 | http://localhost:3000 | ✓ Ready |

Everything is configured and ready to use!
