# config.py
# For local use: fill in the values directly.
# For Railway deployment: these are read from environment variables automatically.

import os

API_ID            = int(os.environ.get("API_ID", "12345678"))
API_HASH          = os.environ.get("API_HASH", "your_api_hash_here")
BOT_TOKEN         = os.environ.get("BOT_TOKEN", "123456789:ABCdef...")
OUTPUT_CHANNEL_ID = int(os.environ.get("OUTPUT_CHANNEL_ID", "-1001234567890"))
SOURCE_CHANNELS   = os.environ.get("SOURCE_CHANNELS", "bbcnews,reutersnews").split(",")

OLLAMA_URL   = os.environ.get("OLLAMA_URL", "")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3")
DIGEST_HOUR   = int(os.environ.get("DIGEST_HOUR", "8"))
DIGEST_MINUTE = int(os.environ.get("DIGEST_MINUTE", "0"))
MAX_POSTS_FOR_ANALYSIS = int(os.environ.get("MAX_POSTS_FOR_ANALYSIS", "40"))
