"""
agent.py — Apex AI Sales Agent (fully fixed)

Fixes in this version:
  1. Tools registered → model can now call update_sales_stage, update_customer_profile etc
  2. Tool call handler → dispatches to Python, sends result back → stages update
  3. Transcript buffering → accumulates fragments, flushes on turn_complete → full sentences
  4. End call kills session only, NOT the server (daemon thread stays alive)
  5. Greeting injected as a system instruction turn → no "I'm Jordan too" confusion
  6. Multi-call outer loop — reset + wait for next call without restarting script
"""

import asyncio
import json
import os
from pathlib import Path
from threading import Thread
from datetime import datetime
from dotenv import load_dotenv
from google import genai
from google.genai import types
import requests
from generate_prompt import generate_prompt
from state import _lock, dashboard_state
import tools as tool_module

try:
    import pyaudio
except ImportError:
    pyaudio = None

FORMAT       = pyaudio.paInt16 if pyaudio else None
CHANNELS     = 1
INPUT_RATE   = 16000    # mic — always 16kHz
OUTPUT_RATE  = 24000    # Gemini native audio — NEVER change to 16000
OUTPUT_CHUNK = 1024

DEFAULT_MODEL = "models/gemini-2.5-flash-preview-native-audio-dialog"
CONFIG = json.load(open("config.json", "r", encoding="utf-8"))


# ── Tool declarations ─────────────────────────────────────────────────────────
# Must be passed to LiveConnectConfig so the model knows it can call them.

TOOL_DECLARATIONS = types.Tool(function_declarations=[
    types.FunctionDeclaration(
        name="update_sales_stage",
        description=(
            "Update the active sales stage. Call whenever the conversation moves "
            "to a new stage. Valid values: GREETING, DISCOVERY, PITCH, "
            "OBJECTION_HANDLING, CLOSING, FOLLOW_UP. Include a specific reason."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "stage": types.Schema(
                    type=types.Type.STRING,
                    description="GREETING | DISCOVERY | PITCH | OBJECTION_HANDLING | CLOSING | FOLLOW_UP",
                ),
                "reason": types.Schema(
                    type=types.Type.STRING,
                    description="Specific reason for transitioning to this stage",
                ),
            },
            required=["stage", "reason"],
        ),
    ),
    types.FunctionDeclaration(
        name="update_customer_profile",
        description=(
            "Store a customer data point as soon as you learn it. "
            "Fields: company_name, team_size, industry_focus, current_tools, "
            "pain_points, budget_sensitivity, decision_timeline, other_stakeholders."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "attribute": types.Schema(
                    type=types.Type.STRING,
                    description="company_name | team_size | industry_focus | current_tools | "
                                "pain_points | budget_sensitivity | decision_timeline | other_stakeholders",
                ),
                "value": types.Schema(type=types.Type.STRING, description="The value to store"),
            },
            required=["attribute", "value"],
        ),
    ),
    types.FunctionDeclaration(
        name="calculate_price",
        description="Calculate monthly and annual cost for a plan and team size.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "plan":      types.Schema(type=types.Type.STRING,
                             description="Starter | Professional | Enterprise"),
                "num_users": types.Schema(type=types.Type.INTEGER,
                             description="Number of brokers/users"),
            },
            required=["plan", "num_users"],
        ),
    ),
    types.FunctionDeclaration(
        name="compare_competitor",
        description=(
            "Get positioning guidance vs a competitor. "
            "For CoStar always use complementary framing, never replacement."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "competitor_name": types.Schema(
                    type=types.Type.STRING,
                    description="CoStar | Rethink CRM | Salesforce | Buildout",
                ),
            },
            required=["competitor_name"],
        ),
    ),
    types.FunctionDeclaration(
        name="generate_recommendation",
        description="Generate a personalised plan recommendation based on customer profile.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "team_size":    types.Schema(type=types.Type.INTEGER),
                "pain_points":  types.Schema(
                    type=types.Type.ARRAY,
                    items=types.Schema(type=types.Type.STRING),
                ),
                "budget_range": types.Schema(
                    type=types.Type.STRING,
                    description="low | mid | high | unknown",
                ),
            },
            required=["team_size", "pain_points", "budget_range"],
        ),
    ),
    types.FunctionDeclaration(
        name="web_research",
        description=(
            "Research live market data or competitor info. "
            "Say 'give me one sec' before calling. "
            "If customer speaks during research, respond with a hold phrase."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "query": types.Schema(type=types.Type.STRING),
            },
            required=["query"],
        ),
    ),
])

# Tool name → Python function map
TOOL_FN = {
    "update_sales_stage":      tool_module.update_sales_stage,
    "update_customer_profile": tool_module.update_customer_profile,
    "calculate_price":         tool_module.calculate_price,
    "compare_competitor":      tool_module.compare_competitor,
    "generate_recommendation": tool_module.generate_recommendation,
    "web_research":            tool_module.web_research,
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _check_env() -> str:
    load_dotenv()
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY missing. Add to .env")
    return key

def _get_port() -> int:
    try:
        return int(os.getenv("DASHBOARD_PORT", "8090").strip())
    except ValueError:
        return 8090

def _get_dashboard_url() -> str:
    return os.getenv("DASHBOARD_URL", f"http://localhost:{_get_port()}").strip()

def _start_server() -> None:
    """Runs in a daemon thread — survives across multiple calls."""
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=_get_port(),
                reload=False, log_level="error")

def _reset_state() -> None:
    with _lock:
        dashboard_state.update({
            "call_active":       False,
            "call_start_time":   None,
            "stage":             "GREETING",
            "stage_history":     [],
            "profile":           {},
            "tools_called":      [],
            "strategy":          "Jordan is ready — waiting for call",
            "conversation":      [],
            "research_active":   False,
            "research_query":    "",
            "research_progress": [],
            "research_sources":  [],
        })


# ── Agent class ───────────────────────────────────────────────────────────────

class GeminiLiveLoop:
    def __init__(self, api_key: str, system_prompt: str, dashboard_url: str) -> None:
        if pyaudio is None:
            raise RuntimeError(
                "PyAudio not installed.\n"
                "macOS:  brew install portaudio && pip install pyaudio\n"
                "Linux:  sudo apt install python3-pyaudio"
            )
        self.client        = genai.Client(api_key=api_key,
                                          http_options={"api_version": "v1beta"})
        self.system_prompt = system_prompt
        self.model         = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
        self.dashboard_url = dashboard_url
        self.voice_name    = CONFIG["agent"].get("voice", "Puck")
        self.greeting_delay = CONFIG["agent"].get("greeting_delay_ms", 1200) / 1000.0

        self.pya     = pyaudio.PyAudio()
        self.session = None

        self.audio_in_queue:  asyncio.Queue[bytes] = asyncio.Queue()
        self.audio_out_queue: asyncio.Queue[dict]  = asyncio.Queue(maxsize=5)

        # Stop event — kills audio tasks; does NOT touch the server thread
        self._stop = asyncio.Event()

        # Transcript fragment buffers — flushed on turn_complete
        self._jordan_buf:   list[str] = []
        self._customer_buf: list[str] = []

    # ── Internal state writer (same process — no HTTP needed) ─────────────────

    def _write_entry(self, kind: str, text: str) -> None:
        text = text.strip()
        if not text:
            return
        with _lock:
            dashboard_state["conversation"].append({
                "type":      kind,
                "text":      text,
                "timestamp": datetime.now().strftime("%H:%M:%S"),
            })
            if len(dashboard_state["conversation"]) > 300:
                dashboard_state["conversation"] = dashboard_state["conversation"][-300:]
        print(f"  [{kind.upper():8}] {text[:120]}")

    def _flush_jordan(self) -> None:
        if self._jordan_buf:
            self._write_entry("jordan", " ".join(self._jordan_buf))
            self._jordan_buf = []

    def _flush_customer(self) -> None:
        if self._customer_buf:
            self._write_entry("customer", " ".join(self._customer_buf))
            self._customer_buf = []

    # ── Wait for call ─────────────────────────────────────────────────────────

    def _wait_for_call(self) -> None:
        """Block until /start_call is POSTed from the browser."""
        import time
        while True:
            with _lock:
                if dashboard_state.get("call_active"):
                    return
            time.sleep(0.4)

    # ── Monitor (async) ───────────────────────────────────────────────────────

    async def _monitor(self) -> None:
        """Sets _stop when call_active goes False (end call button)."""
        while True:
            await asyncio.sleep(0.5)
            with _lock:
                active = dashboard_state.get("call_active", True)
            if not active:
                print("\n[agent] End-call detected.")
                self._stop.set()
                return

    # ── Audio tasks ───────────────────────────────────────────────────────────

    async def _listen(self) -> None:
        idx = self.pya.get_default_input_device_info()["index"]
        stream = await asyncio.to_thread(
            self.pya.open,
            format=FORMAT, channels=CHANNELS, rate=INPUT_RATE,
            input=True, input_device_index=idx, frames_per_buffer=OUTPUT_CHUNK,
        )
        try:
            while not self._stop.is_set():
                chunk = await asyncio.to_thread(
                    stream.read, OUTPUT_CHUNK, exception_on_overflow=False)
                payload = {"data": chunk, "mime_type": "audio/pcm"}
                try:
                    self.audio_out_queue.put_nowait(payload)
                except asyncio.QueueFull:
                    self.audio_out_queue.get_nowait()
                    self.audio_out_queue.put_nowait(payload)
        finally:
            stream.stop_stream()
            stream.close()

    async def _send(self) -> None:
        while not self._stop.is_set():
            try:
                msg = await asyncio.wait_for(self.audio_out_queue.get(), timeout=0.5)
                await self.session.send_realtime_input(audio=msg)
            except asyncio.TimeoutError:
                continue

    async def _receive(self) -> None:
        """
        Receive loop — handles audio, transcripts, tool calls, and turn_complete.
        """
        while not self._stop.is_set():
            try:
                async for response in self.session.receive():
                    if self._stop.is_set():
                        break

                    # 1. Raw audio → speaker
                    if response.data:
                        self.audio_in_queue.put_nowait(response.data)

                    # 2. Tool calls → execute → send result back
                    if response.tool_call:
                        await self._dispatch_tools(response.tool_call)

                    # 3. Transcription fragments + turn_complete
                    try:
                        sc = response.server_content
                        if sc:
                            ot = getattr(sc, "output_transcription", None)
                            if ot:
                                frag = getattr(ot, "text", "").strip()
                                if frag:
                                    self._jordan_buf.append(frag)

                            it = getattr(sc, "input_transcription", None)
                            if it:
                                frag = getattr(it, "text", "").strip()
                                if frag:
                                    self._customer_buf.append(frag)

                            # Flush complete utterances on turn_complete
                            if getattr(sc, "turn_complete", False):
                                self._flush_jordan()
                                self._flush_customer()
                    except Exception:
                        pass

                    # Fallback: plain text
                    rt = getattr(response, "text", None)
                    if rt and rt.strip():
                        self._jordan_buf.append(rt.strip())

            except Exception as exc:
                if self._stop.is_set():
                    break
                print(f"[receive error] {exc}")
                await asyncio.sleep(0.3)

    async def _dispatch_tools(self, tool_call) -> None:
        """Execute tool calls from the model, post reasoning, send results back."""
        responses = []

        for fn_call in tool_call.function_calls:
            name = fn_call.name
            args = dict(fn_call.args) if fn_call.args else {}

            arg_str = ", ".join(f"{k}={repr(v)}" for k, v in args.items())
            self._write_entry("thinking", f"→ {name}({arg_str})")

            fn = TOOL_FN.get(name)
            if fn:
                try:
                    result = await asyncio.to_thread(fn, **args)
                except Exception as exc:
                    result = {"error": str(exc)}
                    print(f"[tool error] {name}: {exc}")
            else:
                result = {"error": f"Unknown tool: {name}"}

            responses.append(types.FunctionResponse(
                name=name,
                id=fn_call.id,
                response={"result": json.dumps(result, default=str)},
            ))

        if responses:
            await self.session.send_tool_response(function_responses=responses)

    async def _play(self) -> None:
        stream = await asyncio.to_thread(
            self.pya.open,
            format=FORMAT, channels=CHANNELS, rate=OUTPUT_RATE, output=True,
        )
        try:
            while not self._stop.is_set():
                try:
                    chunk = await asyncio.wait_for(
                        self.audio_in_queue.get(), timeout=0.5)
                    await asyncio.to_thread(stream.write, chunk)
                except asyncio.TimeoutError:
                    continue
        finally:
            stream.stop_stream()
            stream.close()

    # ── Session lifecycle ─────────────────────────────────────────────────────

    async def run(self) -> None:
        self._stop.clear()
        self._jordan_buf   = []
        self._customer_buf = []

        self._wait_for_call()

        with _lock:
            dashboard_state["strategy"] = "Connecting…"
            dashboard_state["stage"]    = "GREETING"
            dashboard_state["stage_history"].append({
                "stage":     "GREETING",
                "reason":    "Call accepted",
                "timestamp": datetime.now().isoformat(),
            })

        self._write_entry("thinking", "Call accepted — initialising Gemini Live session")

        live_cfg = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=self.system_prompt,
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=self.voice_name)
                )
            ),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            tools=[TOOL_DECLARATIONS],   # ← THIS is what makes stages update
        )

        async with self.client.aio.live.connect(
                model=self.model, config=live_cfg) as session:
            self.session = session

            with _lock:
                dashboard_state["strategy"] = "Live — Jordan is listening"

            await asyncio.sleep(self.greeting_delay)

            # Trigger greeting — tell model to start speaking now.
            # Injected as a user turn so the model generates its own voice
            # naturally. The system prompt already defines exactly what to say.
            await session.send_client_content(
                turns=[types.Content(
                    role="user",
                    parts=[types.Part(text=(
                        "[The call has connected. Start speaking now. "
                        "Your first words must be: 'Hey — this is Jordan from Apex.' "
                        "Then ask for their name. Nothing else until they respond.]"
                    ))],
                )],
                turn_complete=True,
            )

            tasks = [
                asyncio.create_task(self._listen(),  name="listen"),
                asyncio.create_task(self._send(),    name="send"),
                asyncio.create_task(self._receive(), name="receive"),
                asyncio.create_task(self._play(),    name="play"),
                asyncio.create_task(self._monitor(), name="monitor"),
            ]

            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            self._stop.set()

            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

            # Drain queues
            while not self.audio_in_queue.empty():
                self.audio_in_queue.get_nowait()
            while not self.audio_out_queue.empty():
                self.audio_out_queue.get_nowait()

            self._flush_jordan()
            self._flush_customer()

            print("[agent] Session closed cleanly.")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    api_key       = _check_env()
    prompt_path   = generate_prompt()
    system_prompt = Path(prompt_path).read_text(encoding="utf-8")
    dashboard_url = _get_dashboard_url()

    # Start server once — daemon thread survives all calls
    Thread(target=_start_server, daemon=True).start()

    import time; time.sleep(1.2)

    print(f"\nDashboard → {dashboard_url}")
    print("Open that URL — answer the incoming call to begin.\n")

    loop = GeminiLiveLoop(
        api_key=api_key,
        system_prompt=system_prompt,
        dashboard_url=dashboard_url,
    )

    while True:
        _reset_state()
        try:
            asyncio.run(loop.run())
            print("[agent] Ready for next call.\n")
        except KeyboardInterrupt:
            print("\n[agent] Stopped.")
            break
        except Exception as exc:
            print(f"[agent] Error: {exc}. Resetting in 2s…")
            time.sleep(2)


if __name__ == "__main__":
    main()
