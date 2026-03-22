import os

API_ID            = int(os.environ.get("API_ID", "0"))
API_HASH          = os.environ.get("API_HASH", "")
BOT_TOKEN         = os.environ.get("BOT_TOKEN", "")
OUTPUT_CHANNEL_ID = int(os.environ.get("OUTPUT_CHANNEL_ID", "0"))
SOURCE_CHANNELS   = os.environ.get("SOURCE_CHANNELS", "").split(",")

GROQ_API_KEY      = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL        = os.environ.get("GROQ_MODEL", "llama3-8b-8192")

DIGEST_HOUR            = int(os.environ.get("DIGEST_HOUR", "8"))
DIGEST_MINUTE          = int(os.environ.get("DIGEST_MINUTE", "0"))
MAX_POSTS_FOR_ANALYSIS = int(os.environ.get("MAX_POSTS_FOR_ANALYSIS", "40"))
DATA_DIR               = os.environ.get("DATA_DIR", ".")