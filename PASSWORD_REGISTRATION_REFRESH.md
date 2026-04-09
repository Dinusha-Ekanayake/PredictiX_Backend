# User Registration, Password Hashing & Token Refresh - Implementation Guide

## What Was Implemented

### 1. **Password Hashing Integration** ✅
- Using bcrypt for secure password storage
- Passwords hashed before storing in User model
- Password verification on login

### 2. **User Registration Endpoint** ✅
- `POST /auth/register` - Create new user account
- Creates both User (with password) and Profile entries
- Email uniqueness validation
- Password strength requirements

### 3. **Token Refresh Mechanism** ✅
- `POST /auth/refresh` - Get new access token
- Refresh token valid for 7 days
- Access token valid for 60 minutes (configured)

---

## New Endpoints

### 1. Register User
**POST** `/auth/register`

**Request:**
```json
{
  "email": "john@example.com",
  "user_name": "John Doe",
  "password": "SecurePass123",
  "contact_no": "+1234567890",
  "role": "user"
}
```

**Password Requirements:**
- Minimum 8 characters
- At least one uppercase letter
- At least one digit
- Example: `MyPassword123` ✅ `password123` ❌

**Response (201 Created):**
```json
{
  "message": "User registered successfully",
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "john@example.com",
    "user_name": "John Doe",
    "role": "user",
    "is_active": true
  }
}
```

**Error Responses:**
```json
{
  "detail": "Email already registered"  // 400 Bad Request
}
```

---

### 2. Login with Password
**POST** `/auth/login`

**Request:**
```json
{
  "email": "john@example.com",
  "password": "SecurePass123"
}
```

**Response (200 OK):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "john@example.com",
    "user_name": "John Doe",
    "role": "user",
    "full_name": "John Doe",
    "employee_id": null,
    "warehouse_id": null,
    "department_id": null
  }
}
```

**Changes from previous version:**
- Now validates password against User model
- Returns refresh token in addition to access token
- Checks if user is active

---

### 3. Refresh Access Token
**POST** `/auth/refresh`

**Request:**
```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIs..."
}
```

**Response (200 OK):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cC...",
  "token_type": "bearer"
}
```

**Use Case:**
```typescript
// When access token expires (after 60 minutes)
const newAccessToken = await fetch('/auth/refresh', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    refresh_token: localStorage.getItem('refresh_token')
  })
}).then(r => r.json());

localStorage.setItem('token', newAccessToken.access_token);
```

**Error Responses:**
```json
{
  "detail": "Invalid or expired refresh token"  // 401 Unauthorized
}
```

---

## Frontend Integration

### Complete Login Flow

```typescript
// Step 1: User registers
async function registerUser(email, password, userName) {
  const res = await fetch('http://localhost:8000/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      email,
      password,
      user_name: userName,
      role: 'user'
    })
  });
  
  if (!res.ok) {
    const error = await res.json();
    throw new Error(error.detail);
  }
  
  return await res.json();
}

// Step 2: User logs in
async function loginUser(email, password) {
  const res = await fetch('http://localhost:8000/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password })
  });
  
  if (!res.ok) {
    const error = await res.json();
    throw new Error(error.detail);
  }
  
  const data = await res.json();
  
  // Store tokens
  localStorage.setItem('access_token', data.access_token);
  localStorage.setItem('refresh_token', data.refresh_token);
  localStorage.setItem('user', JSON.stringify(data.user));
  
  return data.user;
}

// Step 3: Make authenticated requests
async function getMyProfile() {
  const token = localStorage.getItem('access_token');
  
  const res = await fetch('http://localhost:8000/profiles/me', {
    headers: { Authorization: `Bearer ${token}` }
  });
  
  if (res.status === 401) {
    // Token expired, refresh it
    await refreshAccessToken();
    // Retry request
    return getMyProfile();
  }
  
  return await res.json();
}

// Step 4: Refresh token when expired
async function refreshAccessToken() {
  const refreshToken = localStorage.getItem('refresh_token');
  
  const res = await fetch('http://localhost:8000/auth/refresh', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refreshToken })
  });
  
  if (!res.ok) {
    // Refresh token expired, redirect to login
    localStorage.clear();
    window.location.href = '/login';
    return;
  }
  
  const data = await res.json();
  localStorage.setItem('access_token', data.access_token);
}

// Step 5: Logout
function logoutUser() {
  localStorage.clear();
  window.location.href = '/login';
}
```

---

## API Testing with Curl

### Register
```bash
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email":"newuser@example.com",
    "user_name":"New User",
    "password":"SecurePass123",
    "role":"user"
  }'
```

### Login
```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email":"newuser@example.com",
    "password":"SecurePass123"
  }'

# Extract access_token and refresh_token from response
```

### Use Access Token
```bash
TOKEN="your_access_token_here"

curl -X GET http://localhost:8000/profiles/me \
  -H "Authorization: Bearer $TOKEN"
```

### Refresh Token
```bash
REFRESH_TOKEN="your_refresh_token_here"

curl -X POST http://localhost:8000/auth/refresh \
  -H "Content-Type: application/json" \
  -d "{\"refresh_token\":\"$REFRESH_TOKEN\"}"
```

---

## Database Schema Changes

### User Model (app/user.py)
- `password_hash` field now properly used for storing bcrypt hashes
- Passwords hashed before insertion

### Profile Model (app/models.py)
- No changes (still stores user metadata/role for authorization)
- Now linked to User via ID

### Sync Strategy
- User created first (with password)
- Profile created with same ID (for authorization/metadata)

---

## Files Modified

| File | Changes |
|------|---------|
| `app/routers/auth.py` | Added register, fixed login with password verification, added refresh endpoint |
| `app/core/security.py` | Added `create_refresh_token()`, `decode_token()` functions, removed duplicate pwd_context |
| `app/core/deps.py` | Removed unused import, added User model dependency |
| `app/schemas/user.py` | Added password validation, new `UserRegister` and `UserLogin` schemas |

---

## Security Notes

✅ **What's Secure:**
- Passwords hashed with bcrypt
- Clear separation: User (passwords) vs Profile (metadata)
- Token expiration (60 min access, 7 day refresh)
- Refresh tokens separate from access tokens
- Password strength requirements enforced

⚠️ **Still TODO (for production):**
- HTTPS enforcement
- CORS configuration hardening
- Rate limiting on login/register
- Account lockout after failed attempts
- Email verification
- Password reset flow

---

## Testing Checklist

- [ ] Register new user with valid password
- [ ] Register fails with weak password (`password123`)
- [ ] Register fails with duplicate email
- [ ] Login with correct credentials returns tokens
- [ ] Login fails with wrong password
- [ ] Can access `/profiles/me` with valid access token
- [ ] Cannot access protected endpoints without token
- [ ] Refresh token generates new access token
- [ ] Expired refresh token returns 401
