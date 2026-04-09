# User Role Implementation - Complete Guide

## Overview
This document outlines the complete user role implementation for the PredictiX backend, enabling authentication, authorization, and user-specific endpoints.

---

## What's Been Implemented

### 1. Authentication System (JWT-based)

**File:** `app/core/deps.py`

```python
get_current_user()      # Validates JWT token and returns Profile
require_user_role()     # Ensures user has 'user' role
require_admin_role()    # Ensures user has 'admin' role (don't use yet)
```

**Security Flow:**
1. Frontend sends `Authorization: Bearer <JWT_TOKEN>` header
2. Backend validates token using JWT secret
3. Returns authenticated user profile or raises 401 Unauthorized

---

### 2. Login Endpoint

**File:** `app/routers/auth.py`

#### POST `/auth/login`

**Request:**
```json
{
  "email": "user@example.com",
  "password": "password123"
}
```

**Response:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "user@example.com",
    "full_name": "John Doe",
    "role": "user",
    "employee_id": "EMP001",
    "warehouse_id": "...",
    "department_id": "..."
  }
}
```

**Current Limitation:** Password hashing not integrated yet (TODO in code)

---

### 3. Protected Endpoints

#### User Profile (`/profiles`)

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `GET /profiles` | GET | ❌ No | List all profiles (public) |
| `GET /profiles/me` | GET | ✅ Yes | Get current user's profile |
| `PUT /profiles/me` | PUT | ✅ Yes | Update own profile (cannot change role) |
| `GET /profiles/{id}` | GET | ❌ No | Get public profile data |
| `PUT /profiles/{id}` | PUT | ❌ No | Update any profile (unprotected, for admin) |

#### Tickets (`/tickets`)

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `GET /tickets` | GET | ✅ Yes | List all tickets with filters |
| `GET /tickets?created_by=ID` | GET | ✅ Yes | Filter by ticket creator |
| `GET /tickets?assigned_to=ID` | GET | ✅ Yes | Filter by assignee |
| `GET /tickets/my` | GET | ✅ Yes | Get user's tickets (created or assigned) |
| `GET /tickets/{id}` | GET | ❌ No | Get single ticket |
| `PUT /tickets/{id}` | PUT | ❌ No | Update ticket |

#### Notifications (`/user-notifications`)

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `GET /user-notifications` | GET | ✅ Yes | List user's notifications |
| `GET /user-notifications?status=unread` | GET | ✅ Yes | Filter by status |
| `GET /user-notifications/unread` | GET | ✅ Yes | Get unread only |
| `GET /user-notifications/{id}` | GET | ✅ Yes | Get specific notification |
| `PUT /user-notifications/{id}/mark-read` | PUT | ✅ Yes | Mark as read |
| `PUT /user-notifications/mark-all-read` | PUT | ✅ Yes | Mark all as read |
| `DELETE /user-notifications/{id}` | DELETE | ✅ Yes | Delete notification |

---

## Frontend Integration

### 1. Login Flow

```typescript
// Step 1: Send login request
const response = await fetch('http://localhost:8000/auth/login', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    email: 'user@example.com',
    password: 'password123'
  })
});

const data = await response.json();
// data.access_token = "eyJhbGciOiJIUzI1NiIs..."

// Step 2: Store token
localStorage.setItem('token', data.access_token);
localStorage.setItem('user', JSON.stringify(data.user));
```

### 2. Authenticated Requests

```typescript
const token = localStorage.getItem('token');

// Get current user profile
const response = await fetch('http://localhost:8000/profiles/me', {
  headers: {
    'Authorization': `Bearer ${token}`
  }
});

// Get user's tickets
const tickets = await fetch('http://localhost:8000/tickets/my', {
  headers: {
    'Authorization': `Bearer ${token}`
  }
});

// Get notifications
const notifications = await fetch('http://localhost:8000/user-notifications', {
  headers: {
    'Authorization': `Bearer ${token}`
  }
});
```

### 3. Role Detection

```typescript
const user = JSON.parse(localStorage.getItem('user'));

if (user.role === 'user') {
  // Show user dashboard
} else if (user.role === 'admin') {
  // Show admin dashboard (separate implementation)
}
```

---

## Database Requirements

### Users Must Have:
- `id` (UUID, Primary Key)
- `email` (unique)
- `full_name`
- `role` ('user' or 'admin')
- `status` ('active' or 'inactive')

All users are stored in the `profiles` table with login via email.

---

## Error Handling

### 401 Unauthorized
```json
{
  "detail": "Invalid authentication credentials"
}
```

### 403 Forbidden
```json
{
  "detail": "User role required"
}
```

### 404 Not Found
```json
{
  "detail": "Notification not found"
}
```

---

## Next Steps (TODO)

1. **Password Integration**
   - Integrate with User model for password hashing/verification
   - Use `bcrypt` or `argon2` for secure hashing

2. **User Registration**
   - Create `POST /auth/register` endpoint
   - Validate email uniqueness
   - Hash password before storing

3. **Token Refresh**
   - Add refresh token mechanism
   - Implement token expiration handling

4. **Admin User Page**
   - Implement separate endpoints
   - Add admin-only role checks

5. **Audit Logging**
   - Log login attempts
   - Log profile updates
   - Log ticket changes

---

## Testing

Use curl or Postman:

```bash
# Login
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"pass123"}'

# Get token from response, then...

# Get current user
curl -X GET http://localhost:8000/profiles/me \
  -H "Authorization: Bearer YOUR_TOKEN"

# Get my tickets
curl -X GET http://localhost:8000/tickets/my \
  -H "Authorization: Bearer YOUR_TOKEN"

# Get notifications
curl -X GET http://localhost:8000/user-notifications \
  -H "Authorization: Bearer YOUR_TOKEN"
```

---

## File Changes Summary

| File | Changes |
|------|---------|
| `app/core/deps.py` | Added `get_current_user()`, `require_user_role()` |
| `app/routers/auth.py` | Added `POST /auth/login` endpoint |
| `app/routers/profile.py` | Added `GET /profiles/me`, `PUT /profiles/me` with auth |
| `app/routers/tickets.py` | Added `created_by`, `assigned_to` filters + `GET /tickets/my` |
| `app/routers/user_notifications.py` | NEW: Full notification management for users |
| `app/main.py` | Registered new user_notifications router |

