"""
Telegram News Aggregator Bot
=============================
Monitors public Telegram channels and forwards posts to your private channel.
Supports /summary, /analyze, and /digest commands using Ollama (free, local AI).

Requirements:
    pip install telethon python-telegram-bot apscheduler aiohttp

Setup:
    1. Copy config.example.py → config.py and fill in your values
    2. Run: python bot.py
"""

import asyncio
import logging
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

from telethon import TelegramClient, events
from telegram import Bot, constants
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram import Update
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import (
    API_ID, API_HASH, BOT_TOKEN,
    OUTPUT_CHANNEL_ID, SOURCE_CHANNELS,
    GROQ_API_KEY, GROQ_MODEL,
    DIGEST_HOUR, DIGEST_MINUTE,
    MAX_POSTS_FOR_ANALYSIS
)
from database import Database
from ai_engine import AIEngine

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO
)
log = logging.getLogger("newsbot")

# ── Railway deployment: restore session from environment variable ─────────────
_session_b64 = os.environ.get("SESSION_BASE64", "")
_data_dir = os.environ.get("DATA_DIR", ".")
if _session_b64:
    import base64 as _b64
    import gzip as _gzip
    os.makedirs(_data_dir, exist_ok=True)
    _session_path = os.path.join(_data_dir, "newsbot.session")
    if not os.path.exists(_session_path):
        _decoded = _b64.b64decode(_session_b64)
        # Handle both compressed and uncompressed session files
        try:
            _decoded = _gzip.decompress(_decoded)
        except Exception:
            pass  # not compressed, use as-is
        with open(_session_path, "wb") as _f:
            _f.write(_decoded)


# ── Global instances ──────────────────────────────────────────────────────────

db = Database(os.path.join(os.environ.get("DATA_DIR", "."), "newsbot.db"))
ai = AIEngine(GROQ_API_KEY, GROQ_MODEL)
telegram_bot: Optional[Bot] = None


# ── Telethon listener (reads public channels) ─────────────────────────────────

async def start_channel_listener():
    """
    Uses a Telegram USER session (via Telethon) to monitor public channels.
    On first run this will ask for your phone number and a login code.
    The session is saved to 'newsbot.session' so you only log in once.
    """
    data_dir = os.environ.get("DATA_DIR", ".")
    client = TelegramClient(os.path.join(data_dir, "newsbot"), API_ID, API_HASH)
    await client.start()
    log.info("Telethon client started — monitoring %d channels", len(SOURCE_CHANNELS))

    @client.on(events.NewMessage(chats=SOURCE_CHANNELS))
    async def on_new_post(event):
        message = event.message
        channel = event.chat
        channel_name = getattr(channel, "title", str(event.chat_id))
        channel_username = getattr(channel, "username", None)

        text = message.text or message.caption or ""
        if not text.strip():
            return  # skip media-only posts with no caption

        # Save to DB
        db.save_post(
            channel_id=str(event.chat_id),
            channel_name=channel_name,
            channel_username=channel_username,
            message_id=message.id,
            text=text,
            timestamp=message.date,
        )

        # Forward to your output channel with a source label
        source_link = f"https://t.me/{channel_username}/{message.id}" if channel_username else channel_name
        header = f"📡 <b>{channel_name}</b>\n"
        footer = f'\n\n<a href="{source_link}">→ Source</a>'

        # Trim message if too long for Telegram
        max_body = 4096 - len(header) - len(footer) - 10
        body = text[:max_body] + ("…" if len(text) > max_body else "")

        formatted = header + body + footer

        try:
            await telegram_bot.send_message(
                chat_id=OUTPUT_CHANNEL_ID,
                text=formatted,
                parse_mode=constants.ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception as e:
            log.error("Failed to forward post: %s", e)

    await client.run_until_disconnected()


# ── Bot command handlers ──────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = (
        "👋 <b>News Bot is running!</b>\n\n"
        "Available commands:\n"
        "  /summary [N] — Summarize last N posts (default 20)\n"
        "  /analyze [topic] — Compare how channels cover a topic\n"
        "  /digest — Full daily roundup\n"
        "  /channels — List monitored channels\n"
        "  /status — Bot and AI engine status\n"
    )
    await update.message.reply_text(msg, parse_mode=constants.ParseMode.HTML)


async def cmd_channels(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lines = ["📋 <b>Monitored channels:</b>\n"]
    stats = db.channel_stats_by_username()
    for ch in SOURCE_CHANNELS:
        ch = ch.strip()
        count = stats.get(ch.lower(), 0)
        lines.append(f"  • <code>{ch}</code> — {count} posts stored")
    await update.message.reply_text("\n".join(lines), parse_mode=constants.ParseMode.HTML)


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    total = db.total_posts()
    ai_ok = await ai.ping()
    ai_status = f"✅ Groq ({GROQ_MODEL})" if ai_ok else "⚠️ Groq offline — using extractive fallback"
    msg = (
        f"🤖 <b>Bot status</b>\n\n"
        f"Posts in database: <b>{total}</b>\n"
        f"AI engine: {ai_status}\n"
        f"Monitoring: <b>{len(SOURCE_CHANNELS)}</b> channels\n"
        f"Daily digest: <b>{DIGEST_HOUR:02d}:{DIGEST_MINUTE:02d}</b>\n"
    )
    await update.message.reply_text(msg, parse_mode=constants.ParseMode.HTML)


async def cmd_summary(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    n = 20
    if ctx.args:
        try:
            n = max(1, min(int(ctx.args[0]), 100))
        except ValueError:
            pass

    await update.message.reply_text(f"⏳ Summarizing last {n} posts…")

    posts = db.recent_posts(limit=n)
    if not posts:
        await update.message.reply_text("No posts found yet. Wait for some to arrive!")
        return

    summary = await ai.summarize(posts)

    msg = f"📰 <b>Summary of last {len(posts)} posts</b>\n\n{summary}"
    await update.message.reply_text(msg, parse_mode=constants.ParseMode.HTML)


async def cmd_analyze(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    topic = " ".join(ctx.args) if ctx.args else None

    if topic:
        await update.message.reply_text(f"🔍 Analyzing coverage of: <b>{topic}</b>…", parse_mode=constants.ParseMode.HTML)
        posts = db.posts_about(topic, limit=MAX_POSTS_FOR_ANALYSIS)
    else:
        await update.message.reply_text("🔍 Analyzing recent coverage across channels…")
        posts = db.recent_posts(limit=MAX_POSTS_FOR_ANALYSIS)

    if not posts:
        await update.message.reply_text("Not enough posts to analyze. Try again later.")
        return

    # Group posts by channel
    by_channel: dict[str, list[dict]] = {}
    for p in posts:
        by_channel.setdefault(p["channel_name"], []).append(p)

    if len(by_channel) < 2:
        await update.message.reply_text(
            "Need posts from at least 2 channels to compare coverage.\n"
            "More posts will arrive soon!"
        )
        return

    analysis = await ai.analyze_coverage(by_channel, topic)

    header = f"🧠 <b>Coverage analysis</b>"
    if topic:
        header += f" — <i>{topic}</i>"
    msg = f"{header}\n\n{analysis}"

    # Split if too long
    if len(msg) > 4000:
        chunks = [msg[i:i+4000] for i in range(0, len(msg), 4000)]
        for chunk in chunks:
            await update.message.reply_text(chunk, parse_mode=constants.ParseMode.HTML)
    else:
        await update.message.reply_text(msg, parse_mode=constants.ParseMode.HTML)


async def cmd_digest(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📋 Building your digest…")
    await send_daily_digest()


async def send_daily_digest():
    """Called by scheduler every day and also by /digest command."""
    since = datetime.utcnow() - timedelta(hours=24)
    posts = db.posts_since(since)

    if not posts:
        await telegram_bot.send_message(
            chat_id=OUTPUT_CHANNEL_ID,
            text="📋 <b>Daily Digest</b>\n\nNo new posts in the last 24 hours.",
            parse_mode=constants.ParseMode.HTML,
        )
        return

    # Stats header
    by_channel: dict[str, list] = {}
    for p in posts:
        by_channel.setdefault(p["channel_name"], []).append(p)

    stats_lines = [f"  • <b>{ch}</b>: {len(ps)} posts" for ch, ps in by_channel.items()]

    digest_text = await ai.daily_digest(posts)

    date_str = datetime.utcnow().strftime("%B %d, %Y")
    msg = (
        f"📋 <b>Daily Digest — {date_str}</b>\n"
        f"<i>{len(posts)} posts from {len(by_channel)} channels</i>\n\n"
        + "\n".join(stats_lines)
        + "\n\n"
        + digest_text
    )

    if len(msg) > 4000:
        chunks = [msg[i:i+4000] for i in range(0, len(msg), 4000)]
        for chunk in chunks:
            await telegram_bot.send_message(
                chat_id=OUTPUT_CHANNEL_ID,
                text=chunk,
                parse_mode=constants.ParseMode.HTML,
            )
    else:
        await telegram_bot.send_message(
            chat_id=OUTPUT_CHANNEL_ID,
            text=msg,
            parse_mode=constants.ParseMode.HTML,
        )


# ── Entry point ───────────────────────────────────────────────────────────────

async def main():
    global telegram_bot

    # Build the python-telegram-bot Application
    app = Application.builder().token(BOT_TOKEN).build()
    telegram_bot = app.bot

    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("channels", cmd_channels))
    app.add_handler(CommandHandler("status",   cmd_status))
    app.add_handler(CommandHandler("summary",  cmd_summary))
    app.add_handler(CommandHandler("analyze",  cmd_analyze))
    app.add_handler(CommandHandler("digest",   cmd_digest))

    # Daily digest scheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        send_daily_digest,
        trigger="cron",
        hour=DIGEST_HOUR,
        minute=DIGEST_MINUTE,
    )
    scheduler.start()

    # Manually manage the bot lifecycle so it plays nicely with asyncio.gather()
    # (avoids the "event loop already running" conflict with run_polling)
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    log.info("Newsflow bot is running. Press Ctrl+C to stop.")

    try:
        # Run Telethon listener alongside the bot — both share the same event loop
        await start_channel_listener()
    finally:
        # Clean shutdown on Ctrl+C or crash
        log.info("Shutting down...")
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())