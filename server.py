from __future__ import annotations
import os
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from euchre.web_session import WebGameSession

app = FastAPI(title="EuchreStratMaster")
sessions: dict[str, WebGameSession] = {}


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.post("/api/new-game")
def new_game() -> dict:
    session = WebGameSession.new()
    sessions[session.session_id] = session
    return session.to_state_dict()


class ActionRequest(BaseModel):
    session_id: str
    action: dict


@app.post("/api/action")
def take_action(req: ActionRequest) -> dict:
    session = sessions.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    return session.process_action(req.action)


@app.get("/api/state/{session_id}")
def get_state(session_id: str) -> dict:
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    return session.to_state_dict()


# ---------------------------------------------------------------------------
# Static files + index
# ---------------------------------------------------------------------------

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def serve_index():
    return FileResponse("static/index.html")
