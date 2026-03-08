from pathlib import Path
import os
import time
from datetime import datetime

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

import state

app = FastAPI(title="ApexAI Dashboard API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def dashboard() -> FileResponse:
    return FileResponse(Path("index.html"))


@app.get("/dashboard")
def legacy_dashboard() -> FileResponse:
    return FileResponse(Path("dashboard.html"))


@app.get("/state")
def get_state() -> dict:
    with state._lock:
        return state.dashboard_state


@app.post("/update_state")
def update_state(payload: dict) -> dict:
    with state._lock:
        for key, value in payload.items():
            if key in state.dashboard_state:
                state.dashboard_state[key] = value
    return {"ok": True, "state": state.dashboard_state}


@app.post("/start_call")
def start_call() -> dict:
    now_iso = datetime.now().isoformat()
    with state._lock:
        state.dashboard_state["call_active"] = True
        state.dashboard_state["call_start_time"] = now_iso
        state.dashboard_state["conversation"] = []
        state.dashboard_state["research_active"] = False
        state.dashboard_state["research_query"] = ""
        state.dashboard_state["research_progress"] = []
        state.dashboard_state["research_sources"] = []
        state.dashboard_state["stage"] = "GREETING"
        state.dashboard_state["stage_history"] = []
    return {"ok": True, "call_start_time": now_iso}


@app.post("/end_call")
def end_call() -> dict:
    with state._lock:
        state.dashboard_state["call_active"] = False
        state.dashboard_state["research_active"] = False
    return {"ok": True}


@app.post("/add_conversation_entry")
def add_conversation_entry(payload: dict) -> dict:
    entry_type = payload.get("type", "").strip()
    text = payload.get("text", "").strip()
    ts = payload.get("timestamp") or datetime.now().strftime("%H:%M:%S")
    if entry_type not in {"customer", "jordan", "thinking"}:
        return {"ok": False, "error": "Invalid type"}
    if not text:
        return {"ok": False, "error": "Empty text"}

    entry = {"type": entry_type, "text": text, "timestamp": ts}
    with state._lock:
        state.dashboard_state["conversation"].append(entry)
        if len(state.dashboard_state["conversation"]) > 120:
            state.dashboard_state["conversation"] = state.dashboard_state["conversation"][-120:]
    return {"ok": True}


@app.post("/add_research_update")
def add_research_update(payload: dict) -> dict:
    message = payload.get("message", "").strip()
    site = payload.get("site", "").strip()
    if not message:
        return {"ok": False, "error": "Empty message"}

    with state._lock:
        state.dashboard_state["research_progress"].append(message)
        if site and site not in state.dashboard_state["research_sources"]:
            state.dashboard_state["research_sources"].append(site)
        if len(state.dashboard_state["research_progress"]) > 60:
            state.dashboard_state["research_progress"] = state.dashboard_state["research_progress"][-60:]
    return {"ok": True}


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "timestamp": int(time.time())}


if __name__ == "__main__":
    raw_port = os.getenv("DASHBOARD_PORT", "8090").strip()
    try:
        port = int(raw_port)
    except ValueError:
        port = 8090
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)
