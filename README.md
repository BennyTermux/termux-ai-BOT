# 🤖 Termux AI Coding Assistant

A production-ready personal AI coding assistant that runs on your Android phone via Termux, with Telegram as the frontend interface.

---

## ✨ Features

| Feature | Details |
|---|---|
| 🤖 Multi-AI | OpenAI GPT-4, Claude, Gemini, Grok |
| 📱 Telegram UI | Chat, file upload, file download |
| 💾 File generation | Parses & saves AI-generated project files |
| 🐙 GitHub | Auto-creates repos, pushes files, writes READMEs |
| 🔐 Secure | Single-user access control, `.env` secrets |
| ⚡ Async queue | Concurrent task processing with progress updates |
| 🛠️ Modular | Plug in new AI providers in minutes |

---

## 📁 Project Structure

```
termux-ai-bot/
├── main.py                    ← Entry point
├── .env.example               ← Configuration template
├── requirements.txt
│
├── bot/
│   └── telegram_handler.py    ← Telegram bot (commands, messages, files)
│
├── ai/
│   └── provider_router.py     ← Multi-provider AI engine
│
├── core/
│   ├── file_manager.py        ← File system operations
│   └── task_handler.py        ← Async task queue & pipeline
│
├── github/
│   └── github_manager.py      ← GitHub repo creation & file push
│
├── config/
│   └── config_loader.py       ← Centralized configuration
│
└── logs/
    └── bot.log                ← Auto-created log file
```

---

## 🚀 Termux Setup (Step-by-Step)

### Step 1 — Install Termux

Download **Termux** from [F-Droid](https://f-droid.org/packages/com.termux/) (NOT Google Play — the Play version is outdated).

---

### Step 2 — Install System Dependencies

Open Termux and run:

```bash
# Update package lists
pkg update && pkg upgrade -y

# Install Python and essentials
pkg install python python-pip git -y

# Install tmux (to keep bot alive in background)
pkg install tmux -y

# Install libxml2 (needed by some pip packages)
pkg install libxml2 libxslt -y
```

---

### Step 3 — Clone This Project

```bash
# Navigate to home directory
cd ~

# Clone the repository (or copy files manually)
git clone https://github.com/YOUR_USERNAME/termux-ai-bot.git
cd termux-ai-bot
```

---

### Step 4 — Install Python Dependencies

```bash
pip install -r requirements.txt
```

> ⚠️ On Termux, some packages may need extra flags:
> ```bash
> pip install --no-build-isolation anthropic
> ```

---

### Step 5 — Configure Environment Variables

```bash
# Copy the example file
cp .env.example .env

# Edit it with nano
nano .env
```

Fill in all required values:

```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_USER_ID=123456789
AI_PROVIDER=claude
AI_API_KEY=sk-ant-...
GITHUB_TOKEN=ghp_...
GITHUB_USERNAME=yourusername
```

**Save**: Press `Ctrl+X`, then `Y`, then `Enter`.

---

### Step 6 — Get Required Tokens

#### Telegram Bot Token
1. Open Telegram → search **@BotFather**
2. Send `/newbot`
3. Follow prompts → copy the token

#### Your Telegram User ID
1. Open Telegram → search **@userinfobot**
2. Send `/start` → it replies with your user ID

#### AI API Key
- **Claude**: https://console.anthropic.com/settings/keys
- **OpenAI**: https://platform.openai.com/api-keys
- **Gemini**: https://aistudio.google.com/app/apikey

#### GitHub Token
1. Go to https://github.com/settings/tokens
2. Click **Generate new token (classic)**
3. Select scopes: `repo`, `delete_repo`
4. Copy the token

---

### Step 7 — Run the Bot

#### Option A: Simple run (closes when Termux closes)
```bash
python main.py
```

#### Option B: tmux (RECOMMENDED — survives Termux minimizing)
```bash
# Start a named tmux session
tmux new-session -s bot

# Inside tmux, run the bot
python main.py

# Detach from tmux (bot keeps running): Ctrl+B then D
# Reattach later: tmux attach -t bot
```

#### Option C: nohup (runs in background)
```bash
nohup python main.py > logs/bot.log 2>&1 &
echo "Bot started with PID $!"
```

#### Option D: Keep Termux alive (Android)
Go to **Termux → Long press → Battery optimization → Unrestricted**

---

### Step 8 — Verify It's Working

In Telegram, send your bot:
```
/start
```

You should see the welcome message. Then try:
```
Build me a Python hello world script
```

---

## 💬 Bot Commands

| Command | Description |
|---|---|
| `/start` | Welcome message |
| `/help` | Show all commands |
| `/newproject <name>` | Start a named project |
| `/status` | Show active & recent tasks |
| `/projects` | List all saved projects |
| `/clear` | Clear conversation history |
| `/provider` | Show current AI provider |

---

## 🧠 Natural Language Usage

Just type naturally — no commands needed:

```
Build me a simple Python calculator app
```
```
Explain this code  [attach a file]
```
```
Debug this error: IndexError: list index out of range
```
```
Refactor this to use async/await  [attach file]
```
```
Create a Node.js Express API with JWT auth
```

---

## 🔧 Switching AI Providers

Edit `.env`:
```env
AI_PROVIDER=openai    # or: claude | gemini | grok
AI_API_KEY=sk-...     # or set per-provider key
```

Restart the bot. No code changes needed.

---

## 📂 How File Generation Works

When the AI generates files, it uses this format:

```
=== FILE: src/calculator.py ===
def add(a, b):
    return a + b
=== END FILE ===

=== FILE: tests/test_calculator.py ===
from src.calculator import add

def test_add():
    assert add(2, 3) == 5
=== END FILE ===
```

The bot automatically:
1. Parses these blocks
2. Writes them to `~/ai-workspace/<project_name>/`
3. Pushes them to GitHub (if configured)
4. Sends you the files via Telegram

---

## 🐙 GitHub Auto-Push Flow

For every project with generated files:
1. **Creates** a new GitHub repository
2. **Generates** a clean README.md
3. **Pushes** all files via GitHub REST API
4. **Sends** you the repo URL

No `git` CLI required — uses GitHub API directly.

---

## 🔐 Security Notes

- Only your `TELEGRAM_USER_ID` can use the bot
- All secrets are loaded from `.env` — never hardcoded
- API keys are never logged or sent to Telegram
- Add `.env` to `.gitignore` before pushing your fork

---

## 🛠️ Adding a New AI Provider

1. Open `ai/provider_router.py`
2. Create a class extending `BaseProvider`
3. Implement `name()` and `complete()`
4. Add it to `PROVIDER_MAP`

Example:
```python
class MyProvider(BaseProvider):
    def name(self): return "MyProvider"
    async def complete(self, system_prompt, messages):
        # call your API here
        return "response text"

PROVIDER_MAP["myprovider"] = MyProvider
```

Set `AI_PROVIDER=myprovider` in `.env` — done.

---

## 🔍 Troubleshooting

| Problem | Solution |
|---|---|
| `ModuleNotFoundError` | Run `pip install -r requirements.txt` |
| Bot not responding | Check `TELEGRAM_USER_ID` is correct |
| AI errors | Verify API key and provider name in `.env` |
| GitHub push fails | Check token has `repo` scope |
| Bot stops when phone sleeps | Use `tmux` + disable battery optimization |
| `SSL: CERTIFICATE_VERIFY_FAILED` | Run `pkg install ca-certificates` |

---

## 📊 Logs

Logs are written to `logs/bot.log` and stdout:

```bash
# Watch logs live
tail -f logs/bot.log

# Search for errors
grep ERROR logs/bot.log
```

---

## 📄 License

MIT — use freely, modify freely.

---

*Built for Termux (Android) · Powered by Telegram Bot API · Multi-provider AI*
