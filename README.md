# 📡 Telegram News Aggregator Bot

Monitors public Telegram channels and forwards posts to your private channel.
Supports AI-powered summaries, multi-channel analysis, and daily digests — all free using Ollama (local AI).

---

## Features

| Command | What it does |
|---|---|
| `/summary [N]` | Summarize the last N posts (default 20) |
| `/analyze [topic]` | Compare how different channels cover a topic or story |
| `/digest` | Full daily roundup of the past 24 hours |
| `/channels` | List monitored channels and post counts |
| `/status` | Show bot health and AI engine status |

Posts are automatically forwarded to your output channel in real-time with a source label and link.

---

## Setup

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 2. Get your Telegram API credentials

Go to https://my.telegram.org → Log in → "API development tools" → Create an app.
You'll get an **API ID** (number) and **API Hash** (string).

### 3. Create your bot

Open Telegram → search for **@BotFather** → send `/newbot` → follow the steps.
You'll get a **Bot Token** like `123456789:ABCdef...`

### 4. Set up your output channel

- Create a private Telegram channel (this is where all news will be collected)
- Add your bot as an **admin** of this channel
- Find the channel ID: forward any message from it to **@userinfobot**
  It will show a negative number like `-1001234567890` — that's your channel ID

### 5. Configure the bot

```bash
cp config.example.py config.py
```
Then open `config.py` and fill in:
- `API_ID` and `API_HASH` from step 2
- `BOT_TOKEN` from step 3
- `OUTPUT_CHANNEL_ID` from step 4
- `SOURCE_CHANNELS` — list of public channel usernames you want to monitor

### 6. Install Ollama (free local AI) — optional but recommended

Download from https://ollama.com and install it, then:

```bash
# Pull a model (pick one — llama3 is a good default)
ollama pull llama3

# Start Ollama (it runs as a background service on most systems)
ollama serve
```

> **If you skip this step**, the bot still works — it uses extractive summarization
> (picks the most important sentences automatically, no AI needed).

### 7. Run the bot

```bash
python bot.py
```

**First run only:** Telethon will ask for your phone number and send you a login code
to confirm your Telegram account. This creates a `newsbot.session` file so you
only need to log in once.

---

## How it works

```
Public channels  →  Telethon (reads as your user account)
                         ↓
                    SQLite database (stores all posts)
                         ↓
                    python-telegram-bot (handles commands)
                         ↓
                    Ollama AI engine (summarize / analyze)
                         ↓
                  Your private output channel
```

**Why two Telegram libraries?**
- **Telethon** uses your personal Telegram account session (MTProto) to read public channels — 
  a regular bot can only receive messages if it's a member of a group/channel it was invited to.
- **python-telegram-bot** handles the bot commands you send via `/summary`, `/analyze`, etc.

---

## Running in the background (Linux/Mac)

```bash
# Using nohup
nohup python bot.py > bot.log 2>&1 &

# Or with screen
screen -S newsbot
python bot.py
# Detach with Ctrl+A, D
```

---

## Adding more channels

Just add usernames to `SOURCE_CHANNELS` in `config.py` and restart the bot.

```python
SOURCE_CHANNELS = [
    "bbcnews",
    "reutersnews",
    "al_jazeera_english",
    "dw_russian",
    "meduzaproject",
]
```

---

## Changing the AI model

In `config.py`, set `OLLAMA_MODEL` to any model you've pulled:

```bash
ollama pull mistral    # fast, good quality
ollama pull phi3       # very small, runs on low RAM
ollama pull gemma2     # Google's model, good for analysis
ollama pull llama3     # Meta's model, well-rounded
```

---

## Troubleshooting

**Bot doesn't forward posts:**
- Make sure the bot is an admin in your OUTPUT channel
- Check that the source channel usernames are correct (no @)

**Ollama not working:**
- Run `ollama serve` in a separate terminal
- Check `http://localhost:11434` is accessible
- The bot will fall back to extractive mode automatically

**Login loop on startup:**
- Delete `newsbot.session` and log in again
