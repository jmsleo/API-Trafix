from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from api_trafix.config.settings import get_settings
from api_trafix.config.database import init_db
from api_trafix.config.redis import close_redis
from api_trafix import models

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await close_redis()

app = FastAPI(
    title=get_settings().app_name,
    version=get_settings().app_version,
    description="Fix Trafing System API - Admin, Teknisi, Operator",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

@app.get("/")
async def root():
    return {
        "app": get_settings().app_name,
        "version": get_settings().app_version,
        "status": "running",
        "docs": "/docs"
    }

@app.get("/healt")
async def health_check():
    return {"status":"healthy"}