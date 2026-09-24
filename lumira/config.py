"""Central configuration: environment + game-balance constants."""
from __future__ import annotations

import os

import pytz

# ----------------------------------------------------------------------------
# Environment
# ----------------------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL")
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
GLOBAL_OWNER_ID = int(os.getenv("GLOBAL_OWNER_ID", "7728424218"))

WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", "8443"))
WEBHOOK_LISTEN = os.getenv("WEBHOOK_LISTEN", "0.0.0.0")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")  # optional, recommended in prod
RUN_MODE = os.getenv("RUN_MODE", "webhook" if WEBHOOK_URL else "polling").lower()

IST = pytz.timezone(os.getenv("TZ", "Asia/Kolkata"))

# Feature toggles (advanced Telegram features degrade gracefully regardless;
# these are master switches).
ENABLE_RICH_MESSAGES = os.getenv("ENABLE_RICH_MESSAGES", "1") != "0"
ENABLE_EPHEMERAL = os.getenv("ENABLE_EPHEMERAL", "1") != "0"
ENABLE_EFFECTS = os.getenv("ENABLE_EFFECTS", "1") != "0"
ENABLE_REACTIONS = os.getenv("ENABLE_REACTIONS", "1") != "0"
ENABLE_DRAFTS = os.getenv("ENABLE_DRAFTS", "1") != "0"  # DM streaming

# ----------------------------------------------------------------------------
# Game balance  (unchanged from v3 — proven values)
# ----------------------------------------------------------------------------
XP_PER_LEVEL = 700
MAX_LEVEL = 70
SHIELD_COST = 1100
SHIELD_DURATION_HOURS = 11
DAILY_COINS = 100
DAILY_COOLDOWN_HOURS = 11
SCRATCH_COOLDOWN_HOURS = 1
REVIVE_SELF_COST = 700
REVIVE_OTHER_COST = 800
XP_PER_MESSAGE = 10

# v4 additions
STREAK_WINDOW_HOURS = 36          # claim within this window to keep the streak
STREAK_BONUS_EVERY = 7            # every N streak days...
STREAK_BONUS_COINS = 350          # ...earn this bonus
SLOTS_MIN_BET = 10
SLOTS_MAX_BET = 2500
SLOTS_COOLDOWN_SEC = 30
PAY_MAX = 100_000

# Guild system
MAX_GUILDS = 10
MAX_GUILD_MEMBERS = 100
GUILD_CREATION_COST = 10000
GUILD_XP_MESSAGE = 1
GUILD_XP_DAILY = 5
GUILD_XP_SCRATCH = 2
GUILD_XP_KILL = 15
GUILD_XP_ROB = 10
GUILD_XP_REVIVE = 8
GUILD_XP_GIFT = 3
GUILD_XP_SLOTS_WIN = 2
GUILD_XP_PAY = 2
GUILD_LEVEL_THRESHOLDS = [0, 5000, 15000, 30000, 50000, 75000, 100000, 150000, 200000, 300000]

GIFT_TYPES = {
    "teddy": {"emoji": "🧸", "price": 50},
    "rose": {"emoji": "🌹", "price": 30},
    "heart": {"emoji": "❤️", "price": 20},
    "slap": {"emoji": "🤚", "price": 10},
    "cake": {"emoji": "🍰", "price": 100},
    "ring": {"emoji": "💍", "price": 500},
    "kiss": {"emoji": "💋", "price": 40},
    "hug": {"emoji": "🤗", "price": 25},
}

LEVEL_SYMBOLS = [
    (0, 9, "⛧"),
    (10, 19, "⛦"),
    (20, 29, "✞"),
    (30, 39, "✠"),
    (40, 49, "♱"),
    (50, 59, "☾"),
    (60, 69, "☽"),
    (70, 70, "☬"),
]

RICHES_TITLES = [
    "🥇 ⟡𝐓𝐎𝐏 𝟏⟡",
    "🥈 ⟡𝐓𝐎𝐏 𝟐⟡",
    "🥉 ⟡𝐓𝐎𝐏 𝟑⟡",
    "♛ 𝐄𝐌𝐏𝐄𝐑𝐎𝐑 ♛",
    "𓆩𝐑𝐎𝐘𝐀𝐋𓆪",
    "✦ 𝐌𝐈𝐋𝐋𝐈𝐎𝐍𝐀𝐈𝐑 ✦",
    "💎 𝐁𝐈𝐋𝐋𝐈𝐎𝐍𝐀𝐈𝐑 💎",
    "⚜ 𝐂𝐑𝐎𝐖𝐍𝐄𝐃 ⚜",
    "⛧ 𝐃𝐎𝐌𝐈𝐍𝐀𝐓𝐎𝐑 ⛧",
    "👑 𝐋𝐄𝐆𝐀𝐂𝐘 𝐊𝐈𝐍𝐆 👑",
]

MEDALS = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

# Pending states / rate limits
PENDING_MAX_SIZE = 1000
PENDING_CLEANUP_INTERVAL = 300
RATE_LIMIT_MAX = 10
RATE_LIMIT_WINDOW = 60
BROADCAST_RATE_LIMIT_MAX = 1
BROADCAST_RATE_LIMIT_WINDOW = 3600
GUILD_REJOIN_COOLDOWN = 86400

# Anti-flood guard for all message edits
EDIT_MIN_INTERVAL = 0.35
