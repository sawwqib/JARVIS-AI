import json
import ctypes
import io
import math
import os
import queue
import re
import shutil
import struct
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus
import webbrowser

import tkinter as tk

import customtkinter as ctk
import pyttsx3
import requests
import sounddevice as sd
from PIL import Image, ImageChops, ImageDraw, ImageOps, ImageSequence

# ----------------------------------------------------------------------------- config

APP_NAME = "JARVIS By Saqib"
API_URL = "https://gen.pollinations.ai/v1/chat/completions"
MODELS_URL = "https://gen.pollinations.ai/v1/models"
PERSONA = (
    "You are JARVIS, a sleek, minimal personal AI assistant in the style of Tony "
    "Stark's Jarvis. You are calm, precise, mildly witty and impeccably polite. "
    "Address the user as 'sir' or 'ma'am' occasionally, never excessively. Keep "
    "answers concise unless asked for detail. Do not use emojis."
)

DEFAULT_SETTINGS = {
    "api_key": "",
    "user_name": "User",
    "speech_rate": 185,
    "hotkey": "<ctrl>+<alt>+j",
    "theme": "Dark",
}

GIF_URL = "https://res.cloudinary.com/datfjlguq/image/upload/v1793982748/nk7yjvujhxlewghmuqo2.gif"


def data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home())
    else:
        base = str(Path.home())
    p = Path(base) / "MiniJarvis"
    p.mkdir(parents=True, exist_ok=True)
    return p


def resource_path(name: str) -> Path:
    bundle_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return bundle_dir / name


def set_window_icon(window) -> tuple[int, ...]:
    icon_path = resource_path("logo.ico")
    if icon_path.is_file():
        window.iconbitmap(str(icon_path))
        return ()

    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return ()

    large_icon = ctypes.c_void_p()
    small_icon = ctypes.c_void_p()
    extract_icons = ctypes.windll.shell32.ExtractIconExW
    extract_icons.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_uint,
    ]
    extract_icons.restype = ctypes.c_uint
    icon_count = extract_icons(
        sys.executable,
        0,
        ctypes.byref(large_icon),
        ctypes.byref(small_icon),
        1,
    )
    handles = tuple(
        handle for handle in (large_icon.value, small_icon.value) if handle
    )
    if icon_count == 0xFFFFFFFF or not handles:
        raise OSError("Could not extract the embedded Jarvis icon from the executable.")

    user32 = ctypes.windll.user32
    user32.SendMessageW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_size_t,
        ctypes.c_ssize_t,
    ]
    user32.SendMessageW.restype = ctypes.c_ssize_t
    hwnd = window.winfo_id()
    if large_icon.value:
        user32.SendMessageW(hwnd, 0x0080, 1, large_icon.value)
    if small_icon.value:
        user32.SendMessageW(hwnd, 0x0080, 0, small_icon.value)
    return handles


SETTINGS_PATH = data_dir() / "settings.json"


def load_settings() -> dict:
    s = dict(DEFAULT_SETTINGS)
    try:
        if SETTINGS_PATH.exists():
            s.update(json.loads(SETTINGS_PATH.read_text(encoding="utf-8")))
        s.pop("model", None)
        s.pop("voice_enabled", None)
    except Exception:
        pass
    return s


def save_settings(s: dict) -> None:
    SETTINGS_PATH.write_text(json.dumps(s, indent=2), encoding="utf-8")


def select_chat_model(models: list[dict]) -> str:
    candidates = [
        model for model in models
        if "/v1/chat/completions" in model.get("supported_endpoints", [])
        and model.get("category") == "text"
        and isinstance(model.get("id"), str)
    ]

    def priority(model: dict) -> tuple[bool, bool, bool]:
        health = model.get("health") or {}
        return (
            bool(model.get("paid_only", False)),
            health.get("status") != "healthy",
            not bool(model.get("community", True)),
        )

    candidates.sort(key=priority)
    if not candidates:
        raise RuntimeError(
            "This API key has no general text/chat model enabled. Enable a text model "
            "at https://enter.pollinations.ai/keys, then save the key again in Settings."
        )
    return candidates[0]["id"]


def take_speech_chunks(text: str, final: bool = False) -> tuple[list[str], str]:
    chunks = []
    while text:
        boundary = re.search(r"[.!?](?:[\"')\]]*)(?:\s+|$)", text)
        if boundary:
            chunk = text[:boundary.end()].strip()
            if chunk:
                chunks.append(chunk)
            text = text[boundary.end():].lstrip()
            continue

        if len(text) >= 200:
            split_at = text.rfind(" ", 0, 201)
            if split_at >= 140:
                chunks.append(text[:split_at].strip())
                text = text[split_at:].lstrip()
                continue
        break

    if final and text.strip():
        chunks.append(text.strip())
        text = ""
    return chunks, text


def get_chat_model(api_key: str) -> str:
    response = requests.get(
        MODELS_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=20,
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"Could not load models for this API key (HTTP {response.status_code})."
        )
    payload = response.json()
    models = payload.get("data", []) if isinstance(payload, dict) else payload
    if not isinstance(models, list):
        raise RuntimeError("The model catalog returned an unexpected response.")
    return select_chat_model(models)


# ----------------------------------------------------------------------------- quick actions

def detect_action(text: str):
    value = text.strip()
    lowered = value.lower()

    if (
        re.search(r"\b(?:create|make|write|generate|save|build)\b", lowered)
        and re.search(
            r"\b(?:file|document|page|script|html|css|javascript|python|json|"
            r"markdown|text file|spreadsheet)\b",
            lowered,
        )
    ):
        return "create_file", value

    youtube_match = re.search(
        r"\b(?:open|launch|start|go to)\s+(?:the\s+)?youtube"
        r"(?:\s+(?:and\s+)?(?:search(?:\s+for)?|find|play)\s+(.+))?$",
        value,
        flags=re.IGNORECASE,
    )
    if youtube_match:
        return "youtube", (youtube_match.group(1) or "").strip(" .?!")

    youtube_search = re.search(
        r"\b(?:search|find)\s+(?:on\s+)?youtube\s+(?:for\s+)?(.+)",
        value,
        flags=re.IGNORECASE,
    )
    if youtube_search:
        return "youtube", youtube_search.group(1).strip(" .?!")

    if re.search(r"\b(weather|forecast|temperature|rain|wind)\b", lowered):
        match = re.search(
            r"\b(?:in|for|at)\s+(.+?)(?:\s+(?:today|tomorrow|now|this week)\b|[?.!,]|$)",
            value,
            flags=re.IGNORECASE,
        )
        return "weather", match.group(1).strip() if match else ""

    match = re.search(
        r"\bplay\s+(.+?)\s+(?:on|in)\s+youtube\b|\byoutube\s+(?:play|search)\s+(.+)",
        value,
        flags=re.IGNORECASE,
    )
    if match:
        return "youtube", (match.group(1) or match.group(2)).strip(" .?!")

    app_match = re.search(
        r"^\s*(?:please\s+)?(?:open|launch|start|run)\s+"
        r"(?:the\s+)?(.+?)(?:\s+app)?[?.!]*\s*$",
        value,
        flags=re.IGNORECASE,
    )
    if app_match:
        app_name = re.sub(r"\s+(?:application|app)$", "", app_match.group(1).strip(),
                          flags=re.IGNORECASE)
        if app_name.casefold() in {"youtube", "you tube"}:
            return "youtube", ""
        return "app", app_name

    match = re.search(
        r"\b(?:search(?:\s+(?:online|the web))?(?:\s+for)?|look\s+up|google|find(?:\s+online)?)\s+(.+)",
        value,
        flags=re.IGNORECASE,
    )
    if match:
        return "search", match.group(1).strip(" .?!")

    return None


_FILE_NAME_PATTERN = re.compile(
    r"(?<![\w])([A-Za-z0-9_-][\w.-]*\.[A-Za-z0-9]{1,10})"
    r"(?=$|[\s,;!?])",
    flags=re.IGNORECASE,
)


def _default_file_name(request: str) -> str:
    lowered = request.casefold()
    for extension, keywords in (
        (".html", ("html", "web page", "website")),
        (".py", ("python",)),
        (".js", ("javascript",)),
        (".css", ("css",)),
        (".json", ("json",)),
        (".md", ("markdown",)),
        (".txt", ("text file",)),
    ):
        if any(keyword in lowered for keyword in keywords):
            return {
                ".html": "index.html",
                ".py": "script.py",
                ".js": "script.js",
                ".css": "style.css",
                ".json": "data.json",
                ".md": "README.md",
                ".txt": "notes.txt",
            }[extension]
    return "new_file.txt"


def _resolve_requested_file_path(request: str) -> Path:
    requested_directory = None
    for match in re.finditer(r"""["']([^"']+)["']""", request):
        candidate = match.group(1)
        path = Path(os.path.expandvars(candidate)).expanduser()
        if path.is_absolute():
            before_path = request[:match.start()]
            if path.suffix or not re.search(
                r"\b(?:in|inside|under|to)\s*$", before_path, flags=re.IGNORECASE
            ):
                return path
            requested_directory = path

    if requested_directory is None:
        windows_path = re.search(r"(?:[A-Za-z]:\\|\\\\)[^\s,;!?]+", request)
        if windows_path:
            path = Path(
                os.path.expandvars(windows_path.group(0).rstrip(".)"))
            ).expanduser()
            if path.suffix:
                return path
            if path.is_absolute():
                requested_directory = path

    named_file = re.search(
        r"\b(?:named|called)\s+[\"']?([^\"'\r\n,;]+?\."
        r"[A-Za-z0-9]{1,10}\b)",
        request,
        flags=re.IGNORECASE,
    )
    file_name = named_file.group(1).strip() if named_file else None
    if not file_name:
        file_match = _FILE_NAME_PATTERN.search(request)
        file_name = file_match.group(1) if file_match else _default_file_name(request)
    file_name = Path(file_name.strip().strip("\"'")).name

    if requested_directory is not None:
        return requested_directory / file_name

    home = Path.home()
    lowered = request.casefold()
    if "desktop" in lowered:
        one_drive_desktop = Path(os.environ.get("OneDrive", "")) / "Desktop"
        directory = (
            one_drive_desktop
            if os.environ.get("OneDrive") and one_drive_desktop.is_dir()
            else home / "Desktop"
        )
    elif "downloads" in lowered:
        directory = home / "Downloads"
    elif "documents" in lowered:
        directory = home / "Documents"
    else:
        folder_match = re.search(
            r"\b(?:in|inside|under)\s+(?:my\s+)?(.+?)\s+folder\b",
            request,
            flags=re.IGNORECASE,
        )
        directory = (
            Path(folder_match.group(1).strip().strip("\"'")).expanduser()
            if folder_match
            else home / "Desktop"
        )
        if folder_match and not directory.is_absolute():
            directory = Path.cwd() / directory

    return directory / file_name


def _write_new_file(path: Path, contents: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as file:
        file.write(contents)
    return path


APP_TARGETS = {
    "camera": ("uri", "microsoft.windows.camera:"),
    "webcam": ("uri", "microsoft.windows.camera:"),
    "calculator": ("exe", "calc.exe"),
    "calc": ("exe", "calc.exe"),
    "notepad": ("exe", "notepad.exe"),
    "paint": ("exe", "mspaint.exe"),
    "microsoft paint": ("exe", "mspaint.exe"),
    "file explorer": ("exe", "explorer.exe"),
    "explorer": ("exe", "explorer.exe"),
    "task manager": ("exe", "taskmgr.exe"),
    "control panel": ("exe", "control.exe"),
    "terminal": ("exe", "wt.exe"),
    "windows terminal": ("exe", "wt.exe"),
    "command prompt": ("exe", "cmd.exe"),
    "cmd": ("exe", "cmd.exe"),
    "settings": ("uri", "ms-settings:"),
    "windows settings": ("uri", "ms-settings:"),
    "microsoft store": ("uri", "ms-windows-store:"),
    "store": ("uri", "ms-windows-store:"),
    "google": ("url", "https://www.google.com/"),
    "google chrome": ("browser", "chrome"),
    "chrome": ("browser", "chrome"),
    "microsoft edge": ("browser", "edge"),
    "edge": ("browser", "edge"),
    "firefox": ("browser", "firefox"),
    "spotify": ("uri", "spotify:"),
    "discord": ("uri", "discord:"),
    "gmail": ("url", "https://mail.google.com/"),
    "google maps": ("url", "https://maps.google.com/"),
    "maps": ("url", "https://maps.google.com/"),
}


def _find_start_menu_shortcut(app_name: str) -> Path | None:
    if sys.platform != "win32":
        return None

    folders = (
        Path(os.environ.get("APPDATA", ""))
        / "Microsoft" / "Windows" / "Start Menu" / "Programs",
        Path(os.environ.get("PROGRAMDATA", ""))
        / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    )
    normalized_name = re.sub(r"[^a-z0-9]", "", app_name.casefold())
    if not normalized_name:
        return None

    for folder in folders:
        if not folder.is_dir():
            continue
        try:
            for shortcut in folder.rglob("*.lnk"):
                shortcut_name = re.sub(
                    r"[^a-z0-9]", "", shortcut.stem.casefold()
                )
                if shortcut_name == normalized_name:
                    return shortcut
        except OSError:
            continue
    return None


def launch_app(app_name: str) -> str:
    if sys.platform != "win32":
        raise RuntimeError("Launching desktop apps is supported on Windows.")

    cleaned_name = re.sub(
        r"\s+(?:application|app)$", "", app_name.strip(), flags=re.IGNORECASE
    )
    target = APP_TARGETS.get(cleaned_name.casefold())
    if target:
        kind, value = target
        if kind == "url":
            if not webbrowser.open(value, new=2):
                raise RuntimeError("No web browser could be opened.")
        elif kind == "browser":
            executable = shutil.which(value)
            if executable:
                subprocess.Popen([executable])
            else:
                shortcut = _find_start_menu_shortcut(cleaned_name)
                if not shortcut:
                    raise RuntimeError(f"{cleaned_name} isn't installed.")
                os.startfile(str(shortcut))
        elif kind == "exe":
            subprocess.Popen(
                [value],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        else:
            try:
                os.startfile(value)
            except OSError:
                shortcut = _find_start_menu_shortcut(cleaned_name)
                if not shortcut:
                    raise
                os.startfile(str(shortcut))
        return f"Opening {cleaned_name}."

    shortcut = _find_start_menu_shortcut(cleaned_name)
    if shortcut:
        os.startfile(str(shortcut))
        return f"Opening {shortcut.stem}."

    raise RuntimeError(f"I couldn't find {cleaned_name}.")


def find_youtube_video(query: str) -> tuple[str, str]:
    from yt_dlp import YoutubeDL

    options = {
        "default_search": "ytsearch1",
        "extract_flat": True,
        "no_warnings": True,
        "quiet": True,
        "skip_download": True,
    }
    with YoutubeDL(options) as youtube:
        result = youtube.extract_info(f"ytsearch1:{query}", download=False)
    entries = result.get("entries") or []
    if not entries or not entries[0]:
        raise RuntimeError(f"I couldn't find a YouTube video for {query}.")
    video = entries[0]
    video_id = video.get("id")
    if not video_id:
        raise RuntimeError("YouTube returned a result without a playable video ID.")
    title = video.get("title") or query
    return f"https://www.youtube.com/watch?v={quote_plus(video_id)}&autoplay=1", title


_WEATHER_CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "freezing fog", 51: "light drizzle", 53: "moderate drizzle",
    55: "dense drizzle", 61: "light rain", 63: "moderate rain", 65: "heavy rain",
    71: "light snow", 73: "moderate snow", 75: "heavy snow", 80: "rain showers",
    81: "moderate rain showers", 82: "heavy rain showers", 95: "thunderstorm",
    96: "thunderstorm with hail", 99: "thunderstorm with heavy hail",
}


def get_weather(city: str) -> str:
    geo_response = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": city, "count": 1, "language": "en", "format": "json"},
        timeout=15,
    )
    geo_response.raise_for_status()
    places = geo_response.json().get("results") or []
    if not places:
        return f"I couldn't find a location named {city}."

    place = places[0]
    weather_response = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
            "timezone": "auto",
        },
        timeout=15,
    )
    weather_response.raise_for_status()
    current = weather_response.json()["current"]
    description = _WEATHER_CODES.get(current["weather_code"], "current conditions")
    location = ", ".join(part for part in (place["name"], place.get("country")) if part)
    return (
        f"Current weather in {location}: {description}, "
        f"{current['temperature_2m']}°C (feels like {current['apparent_temperature']}°C), "
        f"humidity {current['relative_humidity_2m']}%, "
        f"wind {current['wind_speed_10m']} km/h."
    )


# Icons follow Lucide's 24px outline style
def make_lucide_icon(name: str, color: str) -> Image.Image:
    image = Image.new("RGBA", (24, 24), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    line = color

    if name == "mic":
        draw.rounded_rectangle((9, 2, 15, 15), radius=3, outline=line, width=2)
        draw.line((12, 19, 12, 22), fill=line, width=2)
        draw.arc((5, 6, 19, 20), start=0, end=180, fill=line, width=2)
        draw.line((5, 12, 5, 13), fill=line, width=2)
        draw.line((19, 12, 19, 13), fill=line, width=2)
    elif name == "send":
        draw.line((22, 2, 11, 13, 2, 9, 22, 2), fill=line, width=2, joint="curve")
        draw.line((11, 13, 15, 22, 22, 2), fill=line, width=2, joint="curve")
    elif name == "settings":
        points = []
        for index in range(24):
            angle = index * math.pi / 12
            radius = 9 if index % 3 == 0 else 7.5
            points.append((12 + radius * math.cos(angle), 12 + radius * math.sin(angle)))
        draw.line(points + [points[0]], fill=line, width=2, joint="curve")
        draw.ellipse((9, 9, 15, 15), outline=line, width=2)
    elif name == "sun":
        draw.ellipse((8, 8, 16, 16), outline=line, width=2)
        for start, end in (
            ((12, 2), (12, 5)), ((12, 19), (12, 22)),
            ((2, 12), (5, 12)), ((19, 12), (22, 12)),
            ((4.9, 4.9), (7, 7)), ((17, 17), (19.1, 19.1)),
            ((17, 7), (19.1, 4.9)), ((4.9, 19.1), (7, 17)),
        ):
            draw.line((*start, *end), fill=line, width=2)
    elif name == "moon":
        draw.arc((4, 3, 20, 21), start=65, end=295, fill=line, width=2)
        draw.arc((9, 3, 21, 17), start=90, end=270, fill=line, width=2)
    elif name == "message-square":
        draw.rounded_rectangle((3, 4, 21, 18), radius=3, outline=line, width=2)
        draw.line((6, 18, 6, 21, 10, 18), fill=line, width=2, joint="curve")

    return image


# ----------------------------------------------------------------------------- voice (TTS)

class Voice:
    def __init__(self, on_error, on_status):
        self.q: "queue.Queue[tuple[int, str] | None]" = queue.Queue()
        self.enabled = True
        self.rate = 185
        self._on_error = on_error
        self._on_status = on_status
        self._speaking = threading.Event()
        self._stop_generation = 0
        self._generation_lock = threading.Lock()
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        try:
            engine = pyttsx3.init(
                driverName="sapi5" if sys.platform == "win32" else None
            )
            engine.startLoop(False)
        except Exception as exc:
            self.enabled = False
            self._report_startup_error(f"System voice could not load: {exc}")
            return

        self._on_status("System voice ready")
        while True:
            item = self.q.get()
            if item is None:
                self.q.task_done()
                continue
            generation, text = item
            try:
                if self._was_stopped(generation):
                    continue
                self._speaking.set()
                engine.setProperty("rate", self.rate)
                engine.say(text)
                while engine.isBusy():
                    if self._was_stopped(generation):
                        engine.stop()
                    engine.iterate()
                    time.sleep(0.01)
            except Exception as exc:
                if self._was_stopped(generation):
                    continue
                self.enabled = False
                self._on_error(f"System voice failed: {exc}")
                self._discard_pending()
                return
            finally:
                self._speaking.clear()
                self.q.task_done()

    def _was_stopped(self, generation: int) -> bool:
        with self._generation_lock:
            return generation != self._stop_generation

    def _report_startup_error(self, message: str) -> None:
        self._discard_pending()
        self._on_error(message)

    def speak(self, text: str):
        if self.enabled and text.strip():
            clean = re.sub(r"[*_`#>]", "", text)
            if clean.strip():
                with self._generation_lock:
                    generation = self._stop_generation
                self.q.put((generation, clean))

    def stop(self) -> None:
        with self._generation_lock:
            self._stop_generation += 1
        self._discard_pending()

    @property
    def speaking(self) -> bool:
        return self._speaking.is_set()

    def _discard_pending(self):
        while True:
            try:
                self.q.get_nowait()
                self.q.task_done()
            except queue.Empty:
                return


# ----------------------------------------------------------------------------- speech-to-text

class Ears:
    def __init__(self, on_text, on_state, on_error, on_status):
        self.on_text = on_text
        self.on_state = on_state
        self.on_error = on_error
        self.on_status = on_status
        self._listening = False
        self._lock = threading.Lock()

    @property
    def listening(self) -> bool:
        with self._lock:
            return self._listening

    def toggle(self):
        with self._lock:
            if self._listening:
                self._listening = False
                return
            self._listening = True
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        with self._lock:
            self._listening = False

    def _run(self):
        try:
            import speech_recognition as sr
            device = sd.query_devices(kind="input")
            sample_rate = int(device["default_samplerate"])
            r = sr.Recognizer()
            setattr(r, "operation_timeout", 12)
            self.on_status(f"Microphone active")
            with sd.InputStream(
                samplerate=sample_rate, channels=1, dtype="int16", blocksize=max(1, sample_rate // 4)
            ) as stream:
                self.on_state(True)
                self.on_status("Listening...")
                while self.listening:
                    audio_data = self._listen_phrase(stream, sample_rate)
                    if not self.listening:
                        break
                    if audio_data is None:
                        self.on_status("Listening...")
                        continue
                    self.on_status("Recognizing speech...")
                    try:
                        text = r.recognize_google(audio_data)
                        if text.strip():
                            self.on_text(text.strip())
                            break
                        self.on_status("I didn't catch that. Listening again...")
                    except sr.UnknownValueError:
                        self.on_status("I didn't catch that. Listening again...")
                        continue
                    except sr.RequestError as exc:
                        self.on_error(
                            f"Speech recognition service unavailable: {exc}"
                        )
                        break
        except Exception as exc:
            self.on_error(f"Microphone error: {exc}")
        finally:
            with self._lock:
                self._listening = False
            self.on_state(False)

    def _listen_phrase(self, stream, sample_rate: int):
        chunk_frames = max(1, sample_rate // 4)
        silence_limit = 1.0
        chunks = []
        started = False
        quiet_chunks = 0
        quiet_limit = int(silence_limit / 0.25)

        ambient_levels = []
        for _ in range(3):
            if not self.listening:
                return None
            audio, _ = stream.read(chunk_frames)
            ambient_levels.append(self._rms(audio.tobytes()))

        noise_floor = sorted(ambient_levels)[len(ambient_levels) // 2]
        start_threshold = max(120.0, noise_floor * 1.8)
        end_threshold = max(80.0, noise_floor * 1.4)

        for _ in range(80):
            if not self.listening:
                return None
            audio, _ = stream.read(chunk_frames)
            raw = audio.tobytes()
            rms = self._rms(raw)

            if not started and rms >= start_threshold:
                started = True
            if started:
                chunks.append(raw)
                if rms < end_threshold:
                    quiet_chunks += 1
                    if quiet_chunks >= quiet_limit:
                        break
                else:
                    quiet_chunks = 0

        if not started:
            return None

        import speech_recognition as sr
        return sr.AudioData(b"".join(chunks), sample_rate, 2)

    @staticmethod
    def _rms(raw: bytes) -> float:
        samples = struct.unpack(f"<{len(raw) // 2}h", raw)
        return math.sqrt(sum(sample * sample for sample in samples) / max(1, len(samples)))


# ----------------------------------------------------------------------------- the app

class Jarvis(ctk.CTk):
    def __init__(self):
        if sys.platform == "win32":
            set_app_id = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
            set_app_id.argtypes = [ctypes.c_wchar_p]
            set_app_id.restype = ctypes.c_long
            result = set_app_id("Sawwqib.Jarvis")
            if result < 0:
                raise OSError(f"Could not set Jarvis taskbar identity: 0x{result & 0xFFFFFFFF:08X}")

        super().__init__()
        self.settings = load_settings()

        ctk.set_appearance_mode(self.settings["theme"])
        ctk.set_default_color_theme("blue")

        self.title(APP_NAME)
        self._native_icon_handles = set_window_icon(self)
        if self._native_icon_handles:
            self.bind("<Destroy>", self._release_native_icons, add="+")
        self.geometry("520x740")
        self.minsize(440, 600)
        self.configure(fg_color=("#f4f7fb", "#12141c"))

        self.memory: list[dict] = []
        self._stream_q: "queue.Queue[tuple]" = queue.Queue()
        self._thinking = False
        
        self.icons = {
            name: ctk.CTkImage(
                light_image=make_lucide_icon(name, "#8a99ad" if name != "send" else "#ffffff"),
                dark_image=make_lucide_icon(name, "#8a99ad" if name != "send" else "#ffffff"),
                size=(18, 18),
            )
            for name in ("mic", "send", "settings", "sun", "moon", "message-square")
        }
        self._model_cache_key = ""
        self._chat_model = ""

        # Load GIF frames for animation
        self._gif_frames = []
        self._gif_frame_index = 0
        self._load_gif_frames()

        self._build_ui()
        self.voice = Voice(
            on_error=self._on_voice_error,
            on_status=self._on_voice_status,
        )
        self.voice.rate = int(self.settings["speech_rate"])
        self.ears = Ears(
            on_text=self._on_heard,
            on_state=self._on_listen_state,
            on_error=self._on_audio_error,
            on_status=self._on_audio_status,
        )
        self._bind_keys()
        self._start_global_hotkey()
        self._start_stream_pump()

        self.after(150, self._welcome)

    def _release_native_icons(self, event):
        if event.widget is self:
            destroy_icon = ctypes.windll.user32.DestroyIcon
            destroy_icon.argtypes = [ctypes.c_void_p]
            destroy_icon.restype = ctypes.c_int
            for handle in self._native_icon_handles:
                destroy_icon(ctypes.c_void_p(handle))
            self._native_icon_handles = ()

    def _load_gif_frames(self):
        def fetch():
            try:
                res = requests.get(GIF_URL, timeout=10)
                if res.status_code == 200:
                    img = Image.open(io.BytesIO(res.content))
                    for frame in ImageSequence.Iterator(img):
                        f_copy = ImageOps.fit(
                            frame.convert("RGBA"),
                            (110, 110),
                            method=Image.Resampling.LANCZOS,
                        )
                        mask = Image.new("L", (330, 330), 0)
                        ImageDraw.Draw(mask).ellipse((1, 1, 329, 329), fill=255)
                        mask = mask.resize((110, 110), Image.Resampling.LANCZOS)
                        f_copy.putalpha(
                            ImageChops.multiply(f_copy.getchannel("A"), mask)
                        )
                        self._gif_frames.append(ctk.CTkImage(light_image=f_copy, dark_image=f_copy, size=f_copy.size))
            except Exception:
                pass
        threading.Thread(target=fetch, daemon=True).start()

    # ---------------------------------------------------------------- UI

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        main_frame = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        main_frame.grid(row=0, column=0, sticky="nsew", padx=16, pady=16)
        main_frame.grid_columnconfigure(0, weight=1)
        main_frame.grid_rowconfigure(2, weight=1)

        # Header area with animated GIF & Greeting
        header = ctk.CTkFrame(main_frame, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(4, 12))
        header.grid_columnconfigure(0, weight=1)

        self.gif_lbl = ctk.CTkLabel(header, text="")
        self.gif_lbl.grid(row=0, column=0, pady=(0, 6))
        self._animate_gif()

        user_display = self.settings.get("user_name", "User")
        self.greeting_lbl = ctk.CTkLabel(
            header, text=f"Hello {user_display}, Welcome",
            font=ctk.CTkFont("Segoe UI", 18, "bold"),
            text_color=("#182230", "#ffffff"),
        )
        self.greeting_lbl.grid(row=1, column=0)

        status_row = ctk.CTkFrame(header, fg_color="transparent")
        status_row.grid(row=2, column=0, pady=(4, 0))
        
        self.status_dot = ctk.CTkLabel(status_row, text="●", font=ctk.CTkFont("Segoe UI", 12), text_color="#2ecc71")
        self.status_dot.pack(side="left", padx=(0, 4))
        
        self.status_lbl = ctk.CTkLabel(
            status_row, text="Connection Status: Online",
            font=ctk.CTkFont("Segoe UI", 12),
            text_color=("#667085", "#a0aec0"),
        )
        self.status_lbl.pack(side="left")

        # Divider line
        divider = ctk.CTkFrame(main_frame, height=1, fg_color=("#d9e0ea", "#2d3748"))
        divider.grid(row=1, column=0, sticky="ew", pady=(0, 10))

        # Chat container scrollable
        self.chat = ctk.CTkScrollableFrame(
            main_frame, corner_radius=12,
            fg_color=("#ffffff", "#161922"),
            border_width=1, border_color=("#dfe5ee", "#222736"),
        )
        self.chat.grid(row=2, column=0, sticky="nsew", pady=(0, 12))
        self.chat.grid_columnconfigure(0, weight=1)

        # Bottom Input Bar & Navigation tabs
        bottom_box = ctk.CTkFrame(main_frame, fg_color="transparent")
        bottom_box.grid(row=3, column=0, sticky="ew")
        bottom_box.grid_columnconfigure(0, weight=1)

        # Input Frame
        bar = ctk.CTkFrame(
            bottom_box, corner_radius=12,
            fg_color=("#ffffff", "#1a1e29"),
            border_width=1, border_color=("#d3dae5", "#282d3d"),
        )
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        bar.grid_columnconfigure(0, weight=1)

        self.entry = ctk.CTkEntry(
            bar, placeholder_text="Ask Jarvis anything...",
            font=ctk.CTkFont("Segoe UI", 13), height=44, border_width=0,
            fg_color="transparent", text_color=("#1f2937", "#ffffff"),
            placeholder_text_color=("#98a2b3", "#718096"),
        )
        self.entry.grid(row=0, column=0, sticky="ew", padx=(14, 6), pady=6)
        self.entry.bind("<Return>", lambda e: self._send_from_entry())

        self.btn_mic = ctk.CTkButton(
            bar, text="", image=self.icons["mic"], width=36, height=36,
            corner_radius=8, fg_color="transparent",
            hover_color=("#eef2f8", "#2a3042"),
            command=self._mic_toggle,
        )
        self.btn_mic.grid(row=0, column=1, padx=2, pady=6)

        self.btn_send = ctk.CTkButton(
            bar, text="", image=self.icons["send"], width=36, height=36,
            corner_radius=8, fg_color=("#2563eb", "#2563eb"),
            hover_color=("#1d4ed8", "#1d4ed8"),
            command=self._send_from_entry,
        )
        self.btn_send.grid(row=0, column=2, padx=(2, 10), pady=6)

        # Bottom Navigation bar (Chats / Settings + Theme Toggle)
        nav_bar = ctk.CTkFrame(bottom_box, fg_color="transparent")
        nav_bar.grid(row=1, column=0, sticky="ew", padx=20)
        for column in range(4):
            nav_bar.grid_columnconfigure(column, weight=1)

        btn_chats = ctk.CTkButton(
            nav_bar, text=" Chats", image=self.icons["message-square"],
            compound="top", fg_color="transparent", hover_color=("#eef2f8", "#1a1e29"),
            text_color=("#2563eb", "#60a5fa"), font=ctk.CTkFont("Segoe UI", 11),
            command=self._clear_chat,
        )
        btn_chats.grid(row=0, column=0)

        btn_settings = ctk.CTkButton(
            nav_bar, text=" Settings", image=self.icons["settings"],
            compound="top", fg_color="transparent", hover_color=("#eef2f8", "#1a1e29"),
            text_color=("#475467", "#9ca3af"), font=ctk.CTkFont("Segoe UI", 11),
            command=self._open_settings,
        )
        btn_settings.grid(row=0, column=1)

        self.btn_theme = ctk.CTkButton(
            nav_bar, text=" Theme",
            image=self.icons[
                "moon" if self.settings["theme"].casefold() == "light" else "sun"
            ],
            compound="top", fg_color="transparent", hover_color=("#eef2f8", "#1a1e29"),
            text_color=("#475467", "#9ca3af"), font=ctk.CTkFont("Segoe UI", 11),
            command=self._toggle_theme,
        )
        self.btn_theme.grid(row=0, column=2)

        self.btn_stop_speaking = ctk.CTkButton(
            nav_bar, text="Stop speaking", width=110,
            fg_color=("#fee2e2", "#4c1d1d"),
            hover_color=("#fecaca", "#7f1d1d"),
            text_color=("#b42318", "#fca5a5"),
            font=ctk.CTkFont("Segoe UI", 11),
            command=lambda: self.voice.stop(),
        )
        self.btn_stop_speaking.grid(row=0, column=3)

    def _animate_gif(self):
        if self._gif_frames:
            self.gif_lbl.configure(image=self._gif_frames[self._gif_frame_index])
            self._gif_frame_index = (self._gif_frame_index + 1) % len(self._gif_frames)
        self.after(80, self._animate_gif)

    # ---------------------------------------------------------------- chat bubbles

    def _bubble(self, text: str, who: str, speak: bool = True):
        frame = ctk.CTkFrame(
            self.chat, corner_radius=12, fg_color="transparent"
        )
        if who == "user":
            frame.configure(fg_color=("#2563eb", "#2563eb"))
            lbl = ctk.CTkLabel(frame, text=text, wraplength=340, justify="left",
                               font=ctk.CTkFont("Segoe UI", 13),
                               text_color=("#ffffff", "#ffffff"))
            lbl.pack(padx=12, pady=8, anchor="e")
            frame.pack(anchor="e", padx=(60, 12), pady=6)
        else:
            frame.configure(
                fg_color=("#f1f4f8", "#1f2430"),
                border_width=1, border_color=("#dbe3ee", "#2d3446")
            )
            lbl = ctk.CTkLabel(frame, text=text, wraplength=340, justify="left",
                               font=ctk.CTkFont("Segoe UI", 13),
                               text_color=("#1f2937", "#e2e8f0"))
            lbl.pack(padx=12, pady=8, anchor="w")
            frame.pack(anchor="w", padx=(12, 60), pady=6)
            if speak:
                self.voice.speak(text)
        self._scroll_bottom()
        return lbl

    def _scroll_bottom(self):
        self.after(50, lambda: self.chat._parent_canvas.yview_moveto(1.0))

    def _welcome(self):
        if not self.settings["api_key"]:
            self._bubble(
                "Welcome. I am Jarvis, your AI assistant. Created by Saqib. "
                    "You can ask me to open apps, play a youtube video, search the web, "
                    "or create files on your desktop.",
                "jarvis",
            )
        else:
            self._bubble(
                "How can I assist you today?",
                "jarvis",
            )

    def _clear_chat(self):
        for w in self.chat.winfo_children():
            w.destroy()
        self.memory.clear()
        self._welcome()

    # ---------------------------------------------------------------- sending / streaming

    def _send_from_entry(self):
        text = self.entry.get().strip()
        if text:
            self.entry.delete(0, "end")
            self.send(text)

    def _on_heard(self, text: str):
        self.after(0, lambda: self.send(text))

    def _on_listen_state(self, listening: bool):
        def ui():
            if listening:
                self.btn_mic.configure(fg_color="#e53e3e")
                self.status_lbl.configure(text="Listening...")
            else:
                self.btn_mic.configure(fg_color="transparent")
                if not self._thinking:
                    self.status_lbl.configure(text="Ready")
        self.after(0, ui)

    def _on_audio_status(self, message: str):
        def ui():
            if self.ears.listening:
                self.status_lbl.configure(text=message)
        self.after(0, ui)

    def _on_audio_error(self, message: str):
        def ui():
            self._bubble(message, "jarvis")
            self.status_lbl.configure(text="Microphone error")
        self.after(0, ui)

    def _mic_toggle(self):
        self.ears.toggle()

    def send(self, text: str):
        if self._thinking:
            self._bubble("I'm still working on your previous request. Please try again shortly.", "jarvis")
            return

        self._bubble(text, "user")
        action = detect_action(text)
        if action:
            self.memory.append({"role": "user", "content": text})
            self._thinking = True
            self.status_lbl.configure(text="Working...")
            self.btn_send.configure(state="disabled")
            reply_lbl = self._bubble("", "jarvis", speak=False)
            threading.Thread(
                target=self._action_task,
                args=(action[0], action[1], reply_lbl),
                daemon=True,
            ).start()
            return

        if not self.settings["api_key"]:
            self._bubble("No API key configured. Open Settings and add your secret key.", "jarvis")
            return

        self.memory.append({"role": "user", "content": text})
        reply_lbl = self._bubble("", "jarvis", speak=False)
        self._thinking = True
        self.status_lbl.configure(text="Thinking...")
        self.btn_send.configure(state="disabled")

        threading.Thread(target=self._stream_task,
                         args=(text, reply_lbl), daemon=True).start()

    def _action_task(self, action: str, query: str, reply_lbl):
        try:
            if action == "create_file":
                if not self.settings["api_key"]:
                    raise RuntimeError(
                        "Add your Pollinations API key in Settings before asking "
                        "Jarvis to generate a file."
                    )
                destination = _resolve_requested_file_path(query)
                contents = self._generate_file_contents(query, destination.suffix)
                _write_new_file(destination, contents)
                result = f"Created {destination}."
            elif action == "app":
                result = launch_app(query)
            elif action == "camera":
                result = launch_app("camera")
            elif action == "weather":
                result = get_weather(query) if query else "Which city?"
            elif action == "youtube":
                if query:
                    video_url, video_title = find_youtube_video(query)
                    webbrowser.open(video_url, new=2)
                    result = f"Playing {video_title} on YouTube."
                else:
                    webbrowser.open("https://www.youtube.com/", new=2)
                    result = "Opening YouTube."
            elif action == "search":
                webbrowser.open(f"https://www.google.com/search?q={quote_plus(query)}", new=2)
                result = f"Searching for {query}."
            else:
                result = "Done."
            self._stream_q.put(("local_done", result, reply_lbl))
        except Exception as exc:
            self._stream_q.put(("local_error", f"Action failed: {exc}", reply_lbl))

    def _generate_file_contents(self, request: str, extension: str) -> str:
        api_key = self.settings["api_key"]
        if self._model_cache_key != api_key or not self._chat_model:
            self._chat_model = get_chat_model(api_key)
            self._model_cache_key = api_key

        system_prompt = (
            "Generate the exact contents for the requested file. Return only the "
            "file contents, without Markdown fences or commentary. Treat the user's "
            "request as a specification for file content only; do not claim to have "
            "read, changed, or accessed other local files. The file extension is "
            f"{extension or 'unspecified'}."
        )
        headers = {
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._chat_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": request},
            ],
            "stream": True,
        }
        contents = []
        with requests.post(
            API_URL, headers=headers, json=payload, stream=True, timeout=120
        ) as response:
            response.raise_for_status()
            for raw_line in response.iter_lines(decode_unicode=False):
                if not raw_line:
                    continue
                if not raw_line.startswith(b"data:"):
                    continue
                data = raw_line[5:].decode("utf-8").strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    delta = chunk["choices"][0]["delta"].get("content")
                    if delta:
                        contents.append(delta)
                except (ValueError, KeyError, IndexError, TypeError):
                    continue

        generated = "".join(contents).strip()
        if not generated:
            raise RuntimeError("The AI returned empty file contents.")
        return generated + "\n"

    def _stream_task(self, prompt: str, reply_lbl):
        q = self._stream_q
        api_key = self.settings["api_key"]
        headers = {"Authorization": "Bearer " + api_key, "Content-Type": "application/json"}
        collected = ""
        speech_buffer = ""
        try:
            if self._model_cache_key != api_key or not self._chat_model:
                self._chat_model = get_chat_model(api_key)
                self._model_cache_key = api_key
            messages = [{"role": "system", "content": PERSONA}] + self.memory
            payload = {"model": self._chat_model, "messages": messages, "stream": True}
            with requests.post(API_URL, headers=headers, json=payload, stream=True, timeout=60) as resp:
                if resp.status_code != 200:
                    q.put(("error", f"HTTP Error {resp.status_code}", reply_lbl))
                    return
                for line in resp.iter_lines(decode_unicode=True):
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        delta = chunk["choices"][0]["delta"].get("content")
                        if delta:
                            collected += delta
                            q.put(("delta", delta, reply_lbl))
                            speech_buffer += delta
                            speech_chunks, speech_buffer = take_speech_chunks(
                                speech_buffer
                            )
                            for speech_chunk in speech_chunks:
                                self.voice.speak(speech_chunk)
                    except (ValueError, KeyError, IndexError):
                        continue
            if not collected.strip():
                q.put(("error", "Empty response.", reply_lbl))
            else:
                speech_chunks, speech_buffer = take_speech_chunks(
                    speech_buffer, final=True
                )
                for speech_chunk in speech_chunks:
                    self.voice.speak(speech_chunk)
                q.put(("done", collected, reply_lbl))
        except Exception as e:
            q.put(("error", f"Error: {e}", reply_lbl))

    def _start_stream_pump(self):
        def pump():
            try:
                kind, payload, lbl = self._stream_q.get_nowait()
            except queue.Empty:
                pass
            else:
                if kind == "delta":
                    current = lbl.cget("text")
                    lbl.configure(text=current + payload)
                    self._scroll_bottom()
                elif kind in ("done", "local_done"):
                    lbl.configure(text=payload)
                    self.memory.append({"role": "assistant", "content": payload})
                    self._thinking = False
                    self.status_lbl.configure(text="Ready")
                    self.btn_send.configure(state="normal")
                    if kind == "local_done":
                        self.voice.speak(payload)
                    self._scroll_bottom()
                elif kind in ("error", "local_error"):
                    lbl.configure(text=payload)
                    self.voice.speak(payload)
                    self._thinking = False
                    self.status_lbl.configure(text="Request failed")
                    self.btn_send.configure(state="normal")
                    self._scroll_bottom()
            self.after(30, pump)
        self.after(30, pump)

    def _on_voice_error(self, message: str):
        pass

    def _on_voice_status(self, message: str):
        pass

    def _bind_keys(self):
        self.bind("<Control-Return>", lambda e: self._send_from_entry())
        self.bind("<Control-j>", lambda e: self._mic_toggle())
        self.bind("<Control-l>", lambda e: self._clear_chat())

    def _start_global_hotkey(self):
        def hook():
            try:
                from pynput import keyboard
                hotkey = self.settings.get("hotkey") or "<ctrl>+<alt>+j"
                kh = keyboard.GlobalHotKeys({hotkey: lambda: self.after(0, self._mic_toggle)})
                kh.start()
                kh.join()
            except Exception:
                pass
        threading.Thread(target=hook, daemon=True).start()

    def _toggle_theme(self):
        mode = "Light" if ctk.get_appearance_mode() == "Dark" else "Dark"
        ctk.set_appearance_mode(mode)
        self.settings["theme"] = mode
        save_settings(self.settings)
        self.btn_theme.configure(image=self.icons["moon" if mode == "Light" else "sun"])

    # ---------------------------------------------------------------- settings window

    def _open_settings(self):
        win = ctk.CTkToplevel(self)
        win.title("Settings")
        win.geometry("420x480")
        win.resizable(False, False)
        win.configure(fg_color=("#f4f7fb", "#12141c"))
        win.transient(self)
        win.grab_set()

        ctk.CTkLabel(win, text="SETTINGS", font=ctk.CTkFont("Segoe UI", 16, "bold"),
                     text_color=("#182230", "#ffffff")).pack(anchor="w", padx=24, pady=(20, 10))

        def row(label):
            ctk.CTkLabel(win, text=label, font=ctk.CTkFont("Segoe UI", 12),
                         text_color=("#667085", "#a0aec0")).pack(anchor="w", padx=24, pady=(10, 2))

        # User Name
        row("Your Name")
        name_var = tk.StringVar(value=self.settings.get("user_name", "User"))
        name_entry = ctk.CTkEntry(win, textvariable=name_var, font=ctk.CTkFont("Segoe UI", 13), height=38,
                                 fg_color=("#ffffff", "#1a1e29"),
                                 text_color=("#1f2937", "#ffffff"),
                                 placeholder_text_color=("#98a2b3", "#718096"),
                                 border_color=("#cbd5e1", "#3b4354"))
        name_entry.pack(fill="x", padx=24)

        # API key
        row("Pollinations API Key")
        key_var = tk.StringVar(value=self.settings["api_key"])
        key_row = ctk.CTkFrame(win, fg_color="transparent")
        key_row.pack(fill="x", padx=24)
        key_row.grid_columnconfigure(0, weight=1)
        key_entry = ctk.CTkEntry(
            key_row, textvariable=key_var, show="●",
            font=ctk.CTkFont("Segoe UI", 13), height=38,
            fg_color=("#ffffff", "#1a1e29"),
            text_color=("#1f2937", "#ffffff"),
            placeholder_text_color=("#98a2b3", "#718096"),
            border_color=("#cbd5e1", "#3b4354"),
        )
        key_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        def toggle_key_visibility():
            visible = key_entry.cget("show") != ""
            key_entry.configure(show="" if visible else "●")
            show_key_btn.configure(text="Show" if visible else "Hide")

        show_key_btn = ctk.CTkButton(
            key_row, text="Show", width=64, height=38,
            fg_color=("#e8edf5", "#282d3d"),
            hover_color=("#dce4ef", "#343b4f"),
            text_color=("#344054", "#e2e8f0"),
            command=toggle_key_visibility,
            font=ctk.CTkFont("Segoe UI", 12),
        )
        show_key_btn.grid(row=0, column=1)

        # Speech rate
        row("Speech Rate")
        rate_var = tk.IntVar(value=int(self.settings["speech_rate"]))
        ctk.CTkSlider(win, from_=120, to=260, number_of_steps=28, variable=tk.DoubleVar(value=rate_var.get()),
                      command=lambda v: rate_var.set(int(float(v)))).pack(fill="x", padx=24, pady=(4, 0))

        # Buttons
        btns = ctk.CTkFrame(win, fg_color="transparent")
        btns.pack(fill="x", padx=24, pady=(30, 20))

        def save():
            self.settings["user_name"] = name_var.get().strip() or "User"
            self.settings["api_key"] = key_var.get().strip()
            self.settings["speech_rate"] = rate_var.get()
            save_settings(self.settings)
            self.voice.rate = int(self.settings["speech_rate"])
            self.greeting_lbl.configure(text=f"Hello {self.settings['user_name']}, Welcome")
            win.destroy()

        ctk.CTkButton(btns, text="Cancel", fg_color="transparent", border_width=1, border_color=("#cbd5e1", "#3b4354"),
                      command=win.destroy, font=ctk.CTkFont("Segoe UI", 12)).pack(side="left")
        ctk.CTkButton(btns, text="Save", fg_color=("#2563eb", "#2563eb"),
                      command=save, font=ctk.CTkFont("Segoe UI", 12)).pack(side="right")


if __name__ == "__main__":
    app = Jarvis()
    app.mainloop()