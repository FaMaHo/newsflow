"""
AI Engine — uses Ollama (free, local) for summarization and analysis.
If Ollama is not running, falls back to simple extractive summarization (no AI needed).
"""

import re
import heapq
import logging
import aiohttp
from collections import Counter

log = logging.getLogger("newsbot.ai")


class AIEngine:
    def __init__(self, ollama_url: str, model: str):
        self.ollama_url = ollama_url.rstrip("/")
        self.model = model

    # ── Ollama helpers ────────────────────────────────────────────────────────

    async def ping(self) -> bool:
        """Check if Ollama is running."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.ollama_url}/api/tags", timeout=aiohttp.ClientTimeout(total=3)) as r:
                    return r.status == 200
        except Exception:
            return False

    async def _ask(self, prompt: str, system: str = "") -> str:
        """Send a prompt to Ollama and return the response text."""
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system,
            "stream": False,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.ollama_url}/api/generate",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=120),
                ) as r:
                    if r.status == 200:
                        data = await r.json()
                        return data.get("response", "").strip()
                    else:
                        log.warning("Ollama returned status %d", r.status)
                        return ""
        except Exception as e:
            log.warning("Ollama unavailable: %s", e)
            return ""

    # ── Public methods ────────────────────────────────────────────────────────

    async def summarize(self, posts: list[dict]) -> str:
        """Summarize a list of posts into key points."""
        combined = _format_posts_for_prompt(posts, max_chars=6000)

        system = (
            "You are a concise news summarizer. "
            "Given a set of Telegram channel posts, extract the key news points. "
            "Write in clear, short bullet points. No fluff."
        )
        prompt = (
            f"Here are {len(posts)} recent posts from news channels:\n\n"
            f"{combined}\n\n"
            "Summarize the main news stories in 5-10 bullet points. "
            "Each bullet should be one clear sentence."
        )

        result = await self._ask(prompt, system)
        if result:
            return result

        # Fallback: extractive summarization
        log.info("Using extractive fallback for summarize()")
        return _extractive_summary(posts, n_sentences=8)

    async def analyze_coverage(self, by_channel: dict[str, list[dict]], topic: str | None) -> str:
        """Compare how different channels cover the same story."""
        sections = []
        for channel, posts in by_channel.items():
            texts = [p["text"][:400] for p in posts[:5]]
            sections.append(f"[{channel}]\n" + "\n---\n".join(texts))
        combined = "\n\n".join(sections)

        topic_line = f'about "{topic}"' if topic else "from the same time period"
        system = (
            "You are a media analyst who studies how different news sources cover the same events. "
            "Be specific, neutral, and insightful."
        )
        prompt = (
            f"Below are posts {topic_line} from {len(by_channel)} different Telegram channels.\n\n"
            f"{combined[:5000]}\n\n"
            "Analyze:\n"
            "1. What story or event do they all cover (if any)?\n"
            "2. How does each channel's framing or angle differ?\n"
            "3. What details does each channel emphasize or omit?\n"
            "4. What does this reveal about each channel's perspective or agenda?\n\n"
            "Be direct and specific. Name the channels."
        )

        result = await self._ask(prompt, system)
        if result:
            return result

        # Fallback: keyword comparison
        log.info("Using extractive fallback for analyze_coverage()")
        return _extractive_comparison(by_channel)

    async def daily_digest(self, posts: list[dict]) -> str:
        """Produce a narrative daily digest."""
        combined = _format_posts_for_prompt(posts, max_chars=8000)

        system = (
            "You are a news editor writing a brief daily briefing. "
            "Be factual, organized, and concise."
        )
        prompt = (
            f"Here are posts from the past 24 hours across multiple channels:\n\n"
            f"{combined}\n\n"
            "Write a daily news digest with:\n"
            "• A 2-sentence overview of the day's main themes\n"
            "• Top 5-7 stories as bullet points (one sentence each)\n"
            "• A one-line 'Notable' section for anything unusual or worth watching"
        )

        result = await self._ask(prompt, system)
        if result:
            return result

        log.info("Using extractive fallback for daily_digest()")
        return _extractive_summary(posts, n_sentences=10)


# ── Fallback: extractive summarization (no AI needed) ─────────────────────────

def _clean(text: str) -> str:
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) > 30]


def _extractive_summary(posts: list[dict], n_sentences: int = 8) -> str:
    """
    Pick the most 'important' sentences using TF-IDF-style word frequency scoring.
    No AI required.
    """
    all_text = " ".join(_clean(p["text"]) for p in posts)
    sents = _sentences(all_text)
    if not sents:
        return "No content to summarize."

    # Word frequency
    words = re.findall(r"\b[a-zA-Z]{4,}\b", all_text.lower())
    freq = Counter(words)

    # Score each sentence
    def score(s):
        ws = re.findall(r"\b[a-zA-Z]{4,}\b", s.lower())
        return sum(freq[w] for w in ws) / max(len(ws), 1)

    top = heapq.nlargest(n_sentences, sents, key=score)
    # Restore original order
    ordered = [s for s in sents if s in set(top)][:n_sentences]
    bullets = "\n".join(f"• {s}" for s in ordered)
    return f"<i>(AI offline — extractive summary)</i>\n\n{bullets}"


def _extractive_comparison(by_channel: dict[str, list[dict]]) -> str:
    """Simple keyword-diff comparison when Ollama is offline."""
    lines = ["<i>(AI offline — keyword comparison)</i>\n"]
    channel_words: dict[str, Counter] = {}
    for channel, posts in by_channel.items():
        text = " ".join(_clean(p["text"]) for p in posts)
        words = re.findall(r"\b[a-zA-Z]{5,}\b", text.lower())
        channel_words[channel] = Counter(words)

    for channel, freq in channel_words.items():
        top = [w for w, _ in freq.most_common(10)]
        lines.append(f"<b>{channel}</b> top keywords: {', '.join(top)}")

    return "\n".join(lines)


def _format_posts_for_prompt(posts: list[dict], max_chars: int = 6000) -> str:
    """Format posts for inclusion in a prompt, trimmed to max_chars."""
    parts = []
    total = 0
    for p in posts:
        entry = f"[{p['channel_name']}] {_clean(p['text'])[:300]}"
        if total + len(entry) > max_chars:
            break
        parts.append(entry)
        total += len(entry)
    return "\n\n".join(parts)
