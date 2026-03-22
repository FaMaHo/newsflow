"""
Newsflow — Telegram News Aggregator Bot
"""

import asyncio
import logging
import os
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

# ── Railway: restore Telegram session from env var ────────────────────────────
_session_b64 = os.environ.get("SESSION_BASE64", "")
_data_dir = os.environ.get("DATA_DIR", ".")
if _session_b64:
    import base64 as _b64
    import gzip as _gzip
    os.makedirs(_data_dir, exist_ok=True)
    _session_path = os.path.join(_data_dir, "newsbot.session")
    if not os.path.exists(_session_path):
        _decoded = _b64.b64decode(_session_b64)
        try:
            _decoded = _gzip.decompress(_decoded)
        except Exception:
            pass
        with open(_session_path, "wb") as _f:
            _f.write(_decoded)
        log.info("Session file restored from SESSION_BASE64")

# ── Global instances ──────────────────────────────────────────────────────────
db = Database(os.path.join(_data_dir, "newsbot.db"))
ai = AIEngine(GROQ_API_KEY, GROQ_MODEL)
telegram_bot: Optional[Bot] = None


# ── Telethon listener ─────────────────────────────────────────────────────────

async def start_channel_listener():
    session_path = os.path.join(_data_dir, "newsbot")
    client = TelegramClient(session_path, API_ID, API_HASH)
    await client.start()
    log.info("Telethon client connected")

    # Resolve each channel explicitly and log the result
    resolved = []
    for ch in SOURCE_CHANNELS:
        ch = ch.strip()
        if not ch:
            continue
        try:
            entity = await client.get_entity(ch)
            resolved.append(entity)
            log.info("✅ Resolved channel: %s → %s (id=%s)", ch, entity.title, entity.id)
        except Exception as e:
            log.error("❌ Could not resolve channel '%s': %s", ch, e)

    if not resolved:
        log.error("No channels could be resolved — bot will not forward any posts!")
        return

    @client.on(events.NewMessage(chats=resolved))
    async def on_new_post(event):
        message = event.message
        channel = event.chat
        channel_name = getattr(channel, "title", str(event.chat_id))
        channel_username = getattr(channel, "username", None)

        text = message.text or message.caption or ""
        if not text.strip():
            return

        db.save_post(
            channel_id=str(event.chat_id),
            channel_name=channel_name,
            channel_username=channel_username,
            message_id=message.id,
            text=text,
            timestamp=message.date,
        )
        log.info("New post from %s (len=%d)", channel_name, len(text))

        source_link = f"https://t.me/{channel_username}/{message.id}" if channel_username else channel_name
        header = f"📡 <b>{channel_name}</b>\n"
        footer = f'\n\n<a href="{source_link}">→ Source</a>'
        max_body = 4096 - len(header) - len(footer) - 10
        body = text[:max_body] + ("…" if len(text) > max_body else "")

        try:
            await telegram_bot.send_message(
                chat_id=OUTPUT_CHANNEL_ID,
                text=header + body + footer,
                parse_mode=constants.ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception as e:
            log.error("Failed to forward post: %s", e)

    log.info("Listening to %d channels", len(resolved))
    await client.run_until_disconnected()


# ── Bot command handlers ──────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = (
        "👋 <b>Newsflow is running!</b>\n\n"
        "Commands:\n"
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
        await update.message.reply_text("No posts yet — wait for channels to post something!")
        return
    summary = await ai.summarize(posts)
    await update.message.reply_text(
        f"📰 <b>Summary of last {len(posts)} posts</b>\n\n{summary}",
        parse_mode=constants.ParseMode.HTML
    )


async def cmd_analyze(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    topic = " ".join(ctx.args) if ctx.args else None
    if topic:
        await update.message.reply_text(f"🔍 Analyzing: <b>{topic}</b>…", parse_mode=constants.ParseMode.HTML)
        posts = db.posts_about(topic, limit=MAX_POSTS_FOR_ANALYSIS)
    else:
        await update.message.reply_text("🔍 Analyzing recent coverage…")
        posts = db.recent_posts(limit=MAX_POSTS_FOR_ANALYSIS)

    if not posts:
        await update.message.reply_text("No posts to analyze yet.")
        return

    by_channel: dict[str, list[dict]] = {}
    for p in posts:
        by_channel.setdefault(p["channel_name"], []).append(p)

    if len(by_channel) < 2:
        await update.message.reply_text(
            f"Only have posts from {len(by_channel)} channel so far — need at least 2 to compare.\n"
            "Try again once more channels have posted."
        )
        return

    analysis = await ai.analyze_coverage(by_channel, topic)
    header = "🧠 <b>Coverage analysis</b>"
    if topic:
        header += f" — <i>{topic}</i>"
    msg = f"{header}\n\n{analysis}"

    for chunk in [msg[i:i+4000] for i in range(0, len(msg), 4000)]:
        await update.message.reply_text(chunk, parse_mode=constants.ParseMode.HTML)


async def cmd_digest(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📋 Building digest…")
    await send_daily_digest()


async def send_daily_digest():
    since = datetime.utcnow() - timedelta(hours=24)
    posts = db.posts_since(since)

    if not posts:
        await telegram_bot.send_message(
            chat_id=OUTPUT_CHANNEL_ID,
            text="📋 <b>Daily Digest</b>\n\nNo new posts in the last 24 hours.",
            parse_mode=constants.ParseMode.HTML,
        )
        return

    by_channel: dict[str, list] = {}
    for p in posts:
        by_channel.setdefault(p["channel_name"], []).append(p)

    stats_lines = [f"  • <b>{ch}</b>: {len(ps)} posts" for ch, ps in by_channel.items()]
    digest_text = await ai.daily_digest(posts)
    date_str = datetime.utcnow().strftime("%B %d, %Y")

    msg = (
        f"📋 <b>Daily Digest — {date_str}</b>\n"
        f"<i>{len(posts)} posts from {len(by_channel)} channels</i>\n\n"
        + "\n".join(stats_lines) + "\n\n" + digest_text
    )

    for chunk in [msg[i:i+4000] for i in range(0, len(msg), 4000)]:
        await telegram_bot.send_message(
            chat_id=OUTPUT_CHANNEL_ID,
            text=chunk,
            parse_mode=constants.ParseMode.HTML,
        )


# ── Entry point ───────────────────────────────────────────────────────────────

async def main():
    global telegram_bot

    app = Application.builder().token(BOT_TOKEN).build()
    telegram_bot = app.bot

    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("channels", cmd_channels))
    app.add_handler(CommandHandler("status",   cmd_status))
    app.add_handler(CommandHandler("summary",  cmd_summary))
    app.add_handler(CommandHandler("analyze",  cmd_analyze))
    app.add_handler(CommandHandler("digest",   cmd_digest))

    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_daily_digest, trigger="cron", hour=DIGEST_HOUR, minute=DIGEST_MINUTE)
    scheduler.start()

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    log.info("Newsflow bot is running")

    try:
        await start_channel_listener()
    finally:
        log.info("Shutting down...")
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())