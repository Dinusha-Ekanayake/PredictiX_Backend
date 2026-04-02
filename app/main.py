from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import auth
from app.routers.assets import router as assets_router
from app.schemas.user import UserCreate, UserRead
from app.routers import users



app = FastAPI(title="PredictiX API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(users.router, prefix="/api/v1/users")
app.include_router(auth.router)
app.include_router(assets_router)
app.include_router(auth.router, prefix="/api/v1/auth")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/users/", response_model=UserRead)
def create_user(user: UserCreate):
    # store user.password hashed in DB
    new_user = {"id": 1, "username": user.username, "email": user.email}
    return new_user

@app.get("/")
def root():
    return {"message": "PredictiX Backend is running!"}