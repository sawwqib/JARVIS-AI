# JARVIS AI 🤖

A desktop AI assistant for Windows with AI chat, voice interaction, and quick actions.

## 📥 Download JARVIS

[![Download JARVIS](https://img.shields.io/github/v/release/sawwqib/JARVIS-AI?label=Download%20JARVIS&style=for-the-badge)](https://github.com/sawwqib/JARVIS-AI/releases/latest)

Download the latest Windows executable from GitHub Releases.

## ✨ Features

- **AI Chat:** Ask questions and get spoken responses.
- **Voice Input:** Talk to JARVIS using your microphone.
- **Windows Apps:** Open supported desktop applications.
- **Web Search:** Search the web and find YouTube videos.
- **Weather:** Get current weather by city.
- **File Generation:** Create files using AI and save them anywhere.
- **Customization:** Change your name, speech rate, and theme.
- **Keyboard Shortcuts:**
  - `Ctrl + Enter` – Send message
  - `Ctrl + J` – Toggle microphone
  - `Ctrl + L` – Clear chat
  - `Ctrl + Alt + J` – Global microphone shortcut

## 📥 Installation

1. Open the GitHub repository.
2. Click **Code → Download ZIP**.
3. Extract the ZIP file.
4. Open PowerShell in the project folder.

Alternatively, clone the repository:

```powershell
git clone https://github.com/sawwqib/JARVIS-AI.git
cd JARVIS-AI
```

## 🚀 Run from Source

Make sure Python is installed, then run:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe jarvis.py
```

## 🔑 Configure AI

JARVIS uses Pollinations AI for chat and file generation.

1. Get an API key from [Pollinations](https://enter.pollinations.ai/keys).
2. Open JARVIS.
3. Go to **Settings**.
4. Paste your key into **Pollinations API Key**.
5. Click **Save**.

Your settings are stored locally at:

```text
%APPDATA%\MiniJarvis\settings.json
```

## 📦 Build Windows EXE

You can package JARVIS into a standalone Windows executable using PyInstaller.

**1. Install PyInstaller**

```powershell
.venv\Scripts\python.exe -m pip install pyinstaller
```

**2. Build the executable**

```powershell
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed --name JARVIS --icon logo.ico --add-data "logo.ico;." jarvis.py
```

**3. Find your EXE**

After building, your executable will be here:

```text
dist\JARVIS.exe
```

You can now run JARVIS without opening Python manually.

**Note:** Build on Windows for a Windows executable. Test the EXE on another Windows machine before distributing it. Some dependencies or resource files may need additional packaging configuration.

## 🎤 How to Use

Type a message or use your microphone to talk to JARVIS.

Try these commands:

- `What is the weather in Tokyo?`
- `Search for beginner Python tutorials`
- `Play jazz piano on YouTube`
- `Open Calculator`
- `Create a Python script named hello.py`

Use **Settings** to customize your assistant and **Theme** to switch between light and dark mode.

## ⚙️ Requirements

- Windows 10 or 11
- Python (for running from source)
- Internet connection
- Pollinations API key
- Working microphone for voice input

## 🔧 Troubleshooting

| Problem | Solution |
|---|---|
| AI not responding | Check your internet and API key. |
| Microphone not working | Check Windows microphone permissions. |
| No speech output | Check your audio device and Windows voices. |
| App won't open | Make sure the application is installed. |
| File already exists | Choose a different filename. |

## 🌐 Services Used

- **Pollinations AI** – AI chat and file generation.
- **Google Speech Recognition** – Voice input.
- **Open-Meteo** – Weather information.
- **YouTube** – Video search and playback.

---

**Built with Python. Made to be your personal AI assistant.** 🤖

## ⭐ Support the Project

If you like JARVIS-AI, consider giving this repository a star on GitHub!

Your support helps the project grow. 🚀

## Views
![Visits](https://count.getloli.com/@jaaaaarviiiiiiiiissss?theme=random&padding=7&offset=0&align=top&scale=1&pixelated=1&darkmode=auto)
