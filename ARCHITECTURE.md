# Architecture — [PRODUCT_NAME]

## System Overview

```
                    ┌─────────────────────────────────────┐
                    │           YOUR LAPTOP               │
                    │                                     │
                    │  ┌──────────┐    ┌──────────────┐  │
                    │  │ Mic/Spkr │◄──►│   agent.py   │  │
                    │  └──────────┘    └──────┬───────┘  │
                    │                         │           │
                    │  ┌──────────┐           │           │
                    │  │ Webcam   │──────────►│           │
                    │  └──────────┘  vision   │           │
                    │                         │           │
                    └─────────────────────────┼───────────┘
                                              │ WebSocket
                                              ▼
                    ┌─────────────────────────────────────┐
                    │         GEMINI LIVE API             │
                    │    (Google Cloud — Vertex AI)       │
                    │                                     │
                    │  STT + Reasoning + TTS + ADK Tools  │
                    └─────────────────────────────────────┘
                                              │ State updates
                                              ▼
                    ┌─────────────────────────────────────┐
                    │       GOOGLE CLOUD RUN              │
                    │                                     │
                    │   server.py (FastAPI :8080)         │
                    │   dashboard.html (static)           │
                    │                                     │
                    │   GET  /           → dashboard      │
                    │   GET  /state      → JSON state     │
                    │   POST /update_state → write state  │
                    │   GET  /health     → ok             │
                    └─────────────────────────────────────┘
                                              ▲
                                              │ Browser polls /state
                                    ┌─────────────────┐
                                    │  Judges' phones  │
                                    │  or laptops      │
                                    └─────────────────┘
```

## Data Flow

### Voice Conversation
```
Mic → PyAudio (16kHz PCM16) → Gemini Live WebSocket
Gemini Live → audio chunks (24kHz PCM16) → PyAudio → Speaker
```

### Tool Call
```
Customer speech → Gemini detects intent → calls ADK tool
tools.py function runs → reads config.json → writes to state.py
state.py dashboard_state updated → server.py /state reflects it
dashboard.html polls /state → UI updates live
```

### Vision
```
OpenCV captures frame (1.5s interval) → JPEG encode (quality 70)
→ send as inline_data to Gemini session → Jordan sees and responds
```

### Config → Prompt Pipeline
```
config.json
    └─► generate_prompt.py
            └─► prompts/system_prompt.txt  (auto-generated)
                    └─► agent.py loads at session start
```

## File Map

```
project/
├── .cursorrules              ← Cursor AI rules (this project's coding standards)
├── agent.py                  ← Entry point. Orchestrates everything.
├── config.json               ← SINGLE SOURCE OF TRUTH for domain data
├── generate_prompt.py        ← config.json → system_prompt.txt
├── tools.py                  ← 6 ADK tools. All read config.json.
├── state.py                  ← Shared state dict + threading.Lock
├── server.py                 ← FastAPI dashboard API
├── vision.py                 ← OpenCV webcam daemon
├── dashboard.html            ← Single-file live dashboard UI
├── Dockerfile                ← Cloud Run container (server.py only)
├── requirements.txt
└── prompts/
    └── system_prompt.txt     ← AUTO-GENERATED. Never edit manually.
```

## Thread Model

```
main thread
├── generate_prompt()              [sync, startup only]
├── start_server_thread()          [background, FastAPI uvicorn]
├── connect_gemini_session()       [sync, blocks on WebSocket]
│
├── mic_input_thread               [daemon]
│   └── read PyAudio chunks (16kHz) → send to Gemini session
│
├── speaker_output_thread          [daemon]
│   └── receive Gemini audio chunks → play at 24kHz
│   └── on interrupt signal → stop_stream() + drain buffer
│
└── vision_capture_thread          [daemon]
    └── cv2 capture every 1.5s → send to Gemini as inline_data
    └── entire body in try/except → fail silently
```

## State Shape

```python
dashboard_state = {
    'stage': 'GREETING',           # current sales stage string
    'stage_history': [              # list of stage transitions
        {
            'stage': 'DISCOVERY',
            'reason': 'Customer answered opening question',
            'timestamp': '2026-03-08T14:23:01'
        }
    ],
    'profile': {                    # everything Jordan has learned
        'company': 'Jones Lang LaSalle',
        'team_size': '12',
        'deal_types': 'office and retail',
        'current_tools': 'CoStar and Excel',
        'pain_points': 'comp reports take 3-4 hours',
        'budget_range': 'flexible',
        'decision_timeline': 'this quarter'
    },
    'tools_called': [               # last N tool calls
        {
            'tool': 'calculate_price',
            'input': 'plan=professional, num_users=12',
            'result': '$799/mo flat',
            'timestamp': '2026-03-08T14:24:15'
        }
    ],
    'strategy': 'Transitioning to PITCH — CoStar+Excel pain confirmed'
}
```

## config.json Shape

```json
{
  "agent": {
    "name": "Jordan",
    "title": "Senior Sales Executive",
    "company": "[PRODUCT_NAME]",
    "domain": "Commercial Real Estate Technology",
    "personality": "Warm CRE industry insider. Confident, consultative, never pushy."
  },
  "plans": [
    {
      "name": "Starter",
      "price_monthly": 299,
      "user_limit": 3,
      "features": ["Automated comp analysis", "Basic client portal", "10 reports/month"],
      "ideal_for": "Independent brokers or small teams"
    },
    {
      "name": "Professional",
      "price_monthly": 799,
      "user_limit": 15,
      "features": ["Unlimited comp analysis", "Full client portal", "Pipeline intelligence", "Automated reporting"],
      "ideal_for": "Regional brokerage firms with 5-15 brokers"
    },
    {
      "name": "Enterprise",
      "price_monthly": 1999,
      "user_limit": 999,
      "features": ["All Professional + custom integrations + Dedicated CSM + SLA"],
      "ideal_for": "Large firms and asset management companies"
    }
  ],
  "competitors": [
    {
      "name": "Rethink CRM",
      "price": "$149/user/mo",
      "we_win": ["Purpose-built CRE", "Flat team pricing", "Automated comps"],
      "they_win": ["Larger user base"],
      "talking_point": "Rethink is a generic CRM bolted onto CRE. We are built from the ground up."
    },
    {
      "name": "Salesforce",
      "price": "$150/user/mo",
      "we_win": ["Live in one day", "No consultant needed", "CRE-specific out of the box"],
      "they_win": ["Larger ecosystem"],
      "talking_point": "Salesforce needs months and a consultant. We are live tomorrow."
    },
    {
      "name": "CoStar",
      "price": "$500-2000/mo",
      "we_win": ["We automate what CoStar makes manual"],
      "they_win": ["They own the data layer — we don't compete on data"],
      "talking_point": "[PRODUCT_NAME] sits on top of CoStar. Your subscription stays and becomes 10x more productive."
    }
  ],
  "roi_data": {
    "hours_saved_per_report": 3,
    "reports_per_broker_per_month": 8,
    "average_commission": 75000,
    "payback_months": 1
  }
}
```

## GCP Deployment Architecture

```
Laptop                          Google Cloud
──────                          ─────────────
agent.py ──── WebSocket ────► Vertex AI (Gemini Live)
    │
    └── HTTP POST /update_state ──► Cloud Run (server.py)
                                         │
                                         └── GET /state ◄── Judges' browsers
```

**What runs where:**

| Component | Where | Why |
|-----------|-------|-----|
| agent.py | Laptop | Needs mic + speaker |
| vision.py | Laptop | Needs webcam |
| server.py | Cloud Run | Public URL for judges |
| dashboard.html | Cloud Run (served) | Judges open in browser |
| Gemini API | Vertex AI | Uses $25 GCP credit |
| Docker image | Artifact Registry | Cloud Run pulls from here |
| API keys | Secret Manager | Never in code |

## Swapping the Domain (When Name is Decided)

1. Edit `config.json` → change `agent.company` to real product name
2. Run `python generate_prompt.py` → system_prompt.txt rebuilt in seconds
3. Run `python agent.py` → Jordan now uses the real name
4. Rebuild Docker image + redeploy Cloud Run (10 min)
5. Zero Python code changes required
