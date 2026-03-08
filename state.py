import threading

_lock = threading.Lock()

dashboard_state = {
    "stage": "GREETING",
    "stage_history": [],
    "profile": {},
    "tools_called": [],
    "strategy": "Opening conversation and establishing CRE credibility",
    "call_active": False,
    "call_start_time": None,
    "conversation": [],
    "research_active": False,
    "research_query": "",
    "research_progress": [],
    "research_sources": [],
}
