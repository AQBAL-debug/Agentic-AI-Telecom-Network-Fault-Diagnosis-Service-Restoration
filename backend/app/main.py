"""
main.py
-------
WHAT IT DOES:
    Entry point of the FastAPI backend.
      * creates tables + seeds demo data + trains the anomaly model on first start
      * enables CORS so the React frontend (Vercel / localhost:5173) can call it
      * mounts all routers
    Run locally:   uvicorn app.main:app --reload --port 8000
    API docs:      http://localhost:8000/docs
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .config import settings
from .seed import init
from .llm import llm_available
from .routers import inventory, alarms, incidents, operations


@asynccontextmanager
async def lifespan(app: FastAPI):
    init()
    yield


app = FastAPI(title="Agentic AI Telecom Network Fault Diagnosis & Service Restoration",
              version="1.0.0", lifespan=lifespan,
              description="NOC decision-support platform: 8 cooperating AI agents, human approval required for any action.")

origins = [o.strip() for o in settings.CORS_ORIGINS.split(",")] if settings.CORS_ORIGINS else ["*"]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False, allow_methods=["*"], allow_headers=["*"])

for r in (inventory.router, alarms.router, incidents.router, operations.router):
    app.include_router(r)


@app.get("/")
def root():
    return {"service": "NOC Agentic AI backend", "docs": "/docs", "llm_enabled": llm_available(),
            "database": "postgresql" if settings.db_url.startswith("postgresql") else "sqlite"}


@app.get("/api/health")
def health():
    return {"status": "ok"}
