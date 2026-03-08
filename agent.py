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
from tools import update_sales_stage

try:
    import pyaudio
except ImportError:  # pragma: no cover - runtime environment dependent
    pyaudio = None

FORMAT = pyaudio.paInt16 if pyaudio else None
CHANNELS = 1
INPUT_RATE = 16000
OUTPUT_RATE = 24000
OUTPUT_CHUNK = 1024
DEFAULT_MODEL = "models/gemini-2.5-flash-native-audio-preview-12-2025"
CONFIG = json.load(open("config.json", "r", encoding="utf-8"))


def _check_env() -> str:
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is missing. Add it to a .env file in project root.")
    return api_key


def _get_dashboard_port() -> int:
    raw = os.getenv("DASHBOARD_PORT", "8090").strip()
    try:
        return int(raw)
    except ValueError:
        return 8090


def _get_dashboard_url() -> str:
    port = _get_dashboard_port()
    return os.getenv("DASHBOARD_URL", f"http://localhost:{port}").strip()


def _start_server_background() -> None:
    import uvicorn

    uvicorn.run("server:app", host="0.0.0.0", port=_get_dashboard_port(), reload=False)


class GeminiLiveLoop:
    def __init__(self, api_key: str, system_prompt: str, dashboard_url: str) -> None:
        if pyaudio is None:
            raise RuntimeError(
                "PyAudio is not installed. On macOS run: brew install portaudio && pip3 install pyaudio"
            )
        self.client = genai.Client(api_key=api_key, http_options={"api_version": "v1beta"})
        self.system_prompt = system_prompt
        self.model = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
        self.dashboard_url = dashboard_url
        self.voice_name = CONFIG["agent"].get("voice", "Puck")
        self.greeting_delay_ms = int(CONFIG["agent"].get("greeting_delay_ms", 1200))
        self.pya = pyaudio.PyAudio()
        self.session = None
        self.audio_in_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self.audio_out_queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=5)
        self.audio_stream = None
        self._last_model_text = ""

    def _post_conversation(self, entry_type: str, text: str) -> None:
        if not text.strip():
            return
        try:
            requests.post(
                f"{self.dashboard_url}/add_conversation_entry",
                json={
                    "type": entry_type,
                    "text": text.strip(),
                    "timestamp": datetime.now().strftime("%H:%M:%S"),
                },
                timeout=1.5,
            )
        except requests.RequestException:
            pass

    def _wait_for_call_start(self) -> None:
        print("Jordan is standing by at Apex. Waiting for call...")
        while True:
            try:
                res = requests.get(f"{self.dashboard_url}/state", timeout=1.5)
                data = res.json()
                if data.get("call_active"):
                    return
            except requests.RequestException:
                pass
            import time
            time.sleep(0.5)

    async def listen_audio(self) -> None:
        mic_info = self.pya.get_default_input_device_info()
        self.audio_stream = await asyncio.to_thread(
            self.pya.open,
            format=FORMAT,
            channels=CHANNELS,
            rate=INPUT_RATE,
            input=True,
            input_device_index=mic_info["index"],
            frames_per_buffer=OUTPUT_CHUNK,
        )
        kwargs = {"exception_on_overflow": False}
        try:
            while True:
                chunk = await asyncio.to_thread(self.audio_stream.read, OUTPUT_CHUNK, **kwargs)
                payload = {"data": chunk, "mime_type": "audio/pcm"}
                try:
                    self.audio_out_queue.put_nowait(payload)
                except asyncio.QueueFull:
                    _ = self.audio_out_queue.get_nowait()
                    self.audio_out_queue.put_nowait(payload)
        except asyncio.CancelledError:
            pass
        finally:
            if self.audio_stream:
                self.audio_stream.stop_stream()
                self.audio_stream.close()

    async def send_realtime(self) -> None:
        try:
            while True:
                msg = await self.audio_out_queue.get()
                await self.session.send_realtime_input(audio=msg)
        except asyncio.CancelledError:
            pass

    async def receive_audio(self) -> None:
        try:
            while True:
                turn = self.session.receive()
                async for response in turn:
                    if data := response.data:
                        self.audio_in_queue.put_nowait(data)
                    if text := response.text:
                        print(text, end="", flush=True)
                        if text.strip() and text.strip() != self._last_model_text:
                            self._post_conversation("jordan", text)
                            self._last_model_text = text.strip()
        except asyncio.CancelledError:
            pass

    async def play_audio(self) -> None:
        stream = await asyncio.to_thread(
            self.pya.open,
            format=FORMAT,
            channels=CHANNELS,
            rate=OUTPUT_RATE,
            output=True,
        )
        try:
            while True:
                chunk = await self.audio_in_queue.get()
                await asyncio.to_thread(stream.write, chunk)
        except asyncio.CancelledError:
            pass
        finally:
            stream.stop_stream()
            stream.close()

    async def run(self) -> None:
        self._wait_for_call_start()
        with _lock:
            dashboard_state["strategy"] = "Connecting to Gemini Live API"
        update_sales_stage("GREETING", "Live session started")
        self._post_conversation("thinking", "Call accepted. Initializing Gemini Live session.")

        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=self.system_prompt,
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self.voice_name)
                )
            ),
        )

        async with self.client.aio.live.connect(model=self.model, config=config) as session:
            self.session = session
            with _lock:
                dashboard_state["strategy"] = "Live. Listening on microphone"
            await asyncio.sleep(self.greeting_delay_ms / 1000.0)
            greeting = (
                "Hey - thanks for reaching out to Apex. I'm Jordan. Quick question before we dive in - "
                "are you working on the brokerage side, or more on asset management and portfolio work?"
            )
            self._post_conversation("jordan", greeting)
            await self.session.send_client_content(
                turns=types.Content(
                    parts=[
                        types.Part(text=greeting)
                    ]
                ),
                turn_complete=True,
            )

            async with asyncio.TaskGroup() as tg:
                tg.create_task(self.listen_audio())
                tg.create_task(self.send_realtime())
                tg.create_task(self.receive_audio())
                tg.create_task(self.play_audio())


def main() -> None:
    api_key = _check_env()
    prompt_path = generate_prompt()
    system_prompt = Path(prompt_path).read_text(encoding="utf-8")
    dashboard_url = _get_dashboard_url()

    server_thread = Thread(target=_start_server_background, daemon=True)
    server_thread.start()

    print("Jordan from Apex is ready.")
    print(f"Dashboard: {dashboard_url}")
    print("Press Ctrl C to stop.")

    loop = GeminiLiveLoop(api_key=api_key, system_prompt=system_prompt, dashboard_url=dashboard_url)
    try:
        asyncio.run(loop.run())
    except KeyboardInterrupt:
        print("\nShutting down...")


if __name__ == "__main__":
    main()
