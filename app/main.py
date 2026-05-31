from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import auth, users
from app.routers.assets import router as assets_router

app = FastAPI(title="PredictiX API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router,    prefix="/api/v1/auth",   tags=["Auth"])
app.include_router(users.router,   prefix="/api/v1/users",  tags=["Users"])
app.include_router(assets_router,  prefix="/api/v1/assets", tags=["Assets"])


@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/")
def root():
    return {"message": "PredictiX Backend is running!"}