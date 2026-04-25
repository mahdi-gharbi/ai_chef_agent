"""
api/index.py — Vercel Serverless Entry Point for AI Chef Agent
--------------------------------------------------------------
Exposes the multi-agent chef system as a FastAPI REST API.
The Streamlit UI (web/app_ui.py) still works locally; this file
adds a Vercel-compatible HTTP interface on top of the same agent core.

Endpoints:
  GET  /            → health check
  POST /chat        → send a message, get a streamed or full response
  GET  /fridge      → list current fridge inventory
  POST /fridge      → add an item to the fridge
  GET  /fridge/warnings → expiry & allergen alerts
  POST /fridge/scan → (stub) vision scan — needs cloud DashScope key
"""

import os
import sys
import json
import asyncio
from pathlib import Path

# ---------------------------------------------------------------------------
# Make sure the project root is on sys.path so local modules are importable
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = FastAPI(
    title="AI Chef Agent API",
    description="Multi-agent private chef — LangChain + LangGraph + MCP",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # tighten this in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Lazy-load the agent (cold-start friendly for serverless)
# ---------------------------------------------------------------------------
_agent_executor = None

def get_agent():
    global _agent_executor
    if _agent_executor is None:
        try:
            from agent.chef_agent import init_agent_executor
            _agent_executor = init_agent_executor()
        except Exception as exc:
            raise RuntimeError(f"Failed to initialise agent: {exc}") from exc
    return _agent_executor


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = "default"
    stream: Optional[bool] = False


class FridgeAddRequest(BaseModel):
    item_name: str
    quantity: float
    unit: str
    expiration_date: Optional[str] = None   # ISO format YYYY-MM-DD


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", tags=["health"])
async def root():
    """Health check — confirms the API is running."""
    return {
        "status": "ok",
        "service": "AI Chef Agent",
        "version": "1.0.0",
        "docs": "/docs",
    }


@app.post("/chat", tags=["agent"])
async def chat(req: ChatRequest):
    """
    Send a message to the multi-agent chef system.

    Set `stream: true` to receive a server-sent events stream of tokens.
    Set `stream: false` (default) for a single JSON response.
    """
    try:
        agent = get_agent()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    if req.stream:
        # --- Streaming response ---
        async def token_generator():
            try:
                from agent.chef_agent import get_chef_response_stream
                async for token in get_chef_response_stream(agent, req.message, req.session_id):
                    yield f"data: {json.dumps({'token': token})}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as exc:
                yield f"data: {json.dumps({'error': str(exc)})}\n\n"

        return StreamingResponse(
            token_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    else:
        # --- Full response ---
        try:
            from agent.chef_agent import get_chef_response_stream
            full_response = ""
            async for token in get_chef_response_stream(agent, req.message, req.session_id):
                full_response += token
            return {"reply": full_response, "session_id": req.session_id}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))


@app.get("/fridge", tags=["fridge"])
async def get_fridge():
    """Return the full fridge inventory for the default user."""
    try:
        from fridge_manager.fridge_db import FridgeDB
        db = FridgeDB()
        inventory = db.get_inventory(user_id="default")
        return {"inventory": inventory}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/fridge", tags=["fridge"])
async def add_to_fridge(req: FridgeAddRequest):
    """Add an ingredient to the virtual fridge."""
    try:
        from fridge_manager.fridge_db import FridgeDB
        db = FridgeDB()
        db.add_item(
            user_id="default",
            item_name=req.item_name,
            quantity=req.quantity,
            unit=req.unit,
            expiration_date=req.expiration_date,
        )
        return {"status": "added", "item": req.item_name}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/fridge/warnings", tags=["fridge"])
async def fridge_warnings():
    """Return expiry alerts and allergen warnings."""
    try:
        from fridge_manager.warning_system import WarningSystem
        ws = WarningSystem()
        warnings = ws.get_warnings(user_id="default")
        return {"warnings": warnings}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/health/env", tags=["health"])
async def env_check():
    """
    Check which API keys are configured.
    Returns presence (True/False) only — never exposes key values.
    """
    return {
        "DASHSCOPE_API_KEY": bool(os.getenv("DASHSCOPE_API_KEY")),
        "GEMINI_API_KEY": bool(os.getenv("GEMINI_API_KEY")),
        "SPOONACULAR_API_KEY": bool(os.getenv("SPOONACULAR_API_KEY")),
    }


# ---------------------------------------------------------------------------
# Vercel handler  (Vercel calls the ASGI app directly via the `app` export)
# ---------------------------------------------------------------------------
# No extra handler needed — @vercel/python detects the `app` FastAPI instance
# automatically when this file is the build entry point.