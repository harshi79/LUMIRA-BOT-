#!/usr/bin/env python3
"""
Group Master Elite - Production-Grade Telegram Bot (Lumira)
Single-file architecture with internal service layers and premium UI/UX.
"""

# =============================================================================
# SECTION 1: IMPORTS & CONFIGURATION
# =============================================================================
import os
import re
import sys
import asyncio
import logging
import random
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple, Any, Callable, Union
from functools import wraps
import time

import pytz
import asyncpg
from groq import Groq

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ChatType, ParseMode

# =============================================================================
# SECTION 2: CONFIGURATION (ENVIRONMENT-BASED)
# =============================================================================
DATABASE_URL = os.getenv("DATABASE_URL")
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GLOBAL_OWNER_ID = int(os.getenv("GLOBAL_OWNER_ID", "7728424218"))

# Webhook & Run Mode configuration
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", 8443))
WEBHOOK_LISTEN = os.getenv("WEBHOOK_LISTEN", "0.0.0.0")
RUN_MODE = os.getenv("RUN_MODE", "webhook" if WEBHOOK_URL else "polling").lower()

IST = pytz.timezone("Asia/Kolkata")

# =============================================================================
# SECTION 3: CONSTANTS & GAME BALANCE
# =============================================================================
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

# Guild System Constants
MAX_GUILDS = 10                     # Maximum number of guilds owner can create
MAX_GUILD_MEMBERS = 100             # Maximum members per guild
GUILD_CREATION_COST = 10000         # Coins required to create a guild (optional)
GUILD_XP_MESSAGE = 1                # Guild XP per message
GUILD_XP_DAILY = 5                  # Guild XP for /daily
GUILD_XP_SCRATCH = 2                # Guild XP for /scratch
GUILD_XP_KILL = 15                  # Guild XP for killing someone
GUILD_XP_ROB = 10                   # Guild XP for successful rob
GUILD_XP_REVIVE = 8                 # Guild XP for reviving someone
GUILD_XP_GIFT = 3                   # Guild XP for sending a gift
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

# Pending state manager limits
PENDING_MAX_SIZE = 1000
PENDING_CLEANUP_INTERVAL = 300  # seconds

# Rate limiting
RATE_LIMIT_MAX = 10
RATE_LIMIT_WINDOW = 60
BROADCAST_RATE_LIMIT_MAX = 1
BROADCAST_RATE_LIMIT_WINDOW = 3600  # 1 hour

# Cooldown for rejoining guild after leaving (seconds)
GUILD_REJOIN_COOLDOWN = 86400  # 24 hours

# =============================================================================
# SECTION 4: LOGGING CONFIGURATION
# =============================================================================
logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger("GME")

# =============================================================================
# SECTION 5: RATE LIMITING SYSTEM
# =============================================================================
@dataclass
class RateLimitEntry:
    count: int
    window_start: datetime

class RateLimiter:
    def __init__(self, max_requests: int = 5, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._storage: Dict[Tuple[int, str], RateLimitEntry] = {}
        self._lock = asyncio.Lock()
    
    async def check(self, user_id: int, command: str) -> Tuple[bool, int]:
        key = (user_id, command)
        now = datetime.now(IST)
        async with self._lock:
            entry = self._storage.get(key)
            if entry is None or (now - entry.window_start).total_seconds() > self.window_seconds:
                self._storage[key] = RateLimitEntry(1, now)
                return True, self.max_requests - 1
            if entry.count >= self.max_requests:
                remaining = self.window_seconds - int((now - entry.window_start).total_seconds())
                return False, max(remaining, 1)
            entry.count += 1
            return True, self.max_requests - entry.count

rate_limiter = RateLimiter(max_requests=RATE_LIMIT_MAX, window_seconds=RATE_LIMIT_WINDOW)
broadcast_rate_limiter = RateLimiter(max_requests=BROADCAST_RATE_LIMIT_MAX, window_seconds=BROADCAST_RATE_LIMIT_WINDOW)

# =============================================================================
# SECTION 6: PENDING STATE MANAGER (THREAD-SAFE) WITH CLEANUP
# =============================================================================
class PendingStateManager:
    """Thread-safe pending action manager with automatic cleanup and size limit."""
    
    def __init__(self, expiry_seconds: int = 300, max_size: int = PENDING_MAX_SIZE):
        self._storage: Dict[int, Dict[int, Dict[str, Any]]] = {}
        self._expiry: Dict[int, Dict[int, datetime]] = {}
        self._lock = asyncio.Lock()
        self._expiry_seconds = expiry_seconds
        self._max_size = max_size
        self._cleanup_task: Optional[asyncio.Task] = None
    
    async def start_cleanup_task(self, app: Application):
        """Start background cleanup job."""
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("PendingStateManager cleanup task started")
    
    async def _cleanup_loop(self):
        """Run cleanup every PENDING_CLEANUP_INTERVAL seconds."""
        while True:
            await asyncio.sleep(PENDING_CLEANUP_INTERVAL)
            await self._cleanup_expired()
    
    async def _cleanup_expired(self):
        """Remove expired entries."""
        now = datetime.now(IST)
        async with self._lock:
            for chat_id in list(self._expiry.keys()):
                for user_id in list(self._expiry[chat_id].keys()):
                    if now > self._expiry[chat_id][user_id]:
                        self._storage[chat_id].pop(user_id, None)
                        self._expiry[chat_id].pop(user_id, None)
                if not self._expiry[chat_id]:
                    del self._expiry[chat_id]
                if not self._storage[chat_id]:
                    del self._storage[chat_id]
    
    async def set(self, chat_id: int, user_id: int, data: Dict[str, Any]) -> bool:
        """Set pending data. Returns True if successful, False if size limit exceeded."""
        async with self._lock:
            total = sum(len(users) for users in self._storage.values())
            if total >= self._max_size:
                logger.warning("PendingStateManager size limit reached, rejecting new entry")
                return False
            if chat_id not in self._storage:
                self._storage[chat_id] = {}
                self._expiry[chat_id] = {}
            self._storage[chat_id][user_id] = data
            self._expiry[chat_id][user_id] = datetime.now(IST) + timedelta(seconds=self._expiry_seconds)
            return True
    
    async def get(self, chat_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        async with self._lock:
            if chat_id not in self._storage:
                return None
            expiry = self._expiry.get(chat_id, {}).get(user_id)
            if expiry and datetime.now(IST) > expiry:
                self._storage[chat_id].pop(user_id, None)
                self._expiry[chat_id].pop(user_id, None)
                return None
            return self._storage[chat_id].get(user_id)
    
    async def delete(self, chat_id: int, user_id: int) -> None:
        async with self._lock:
            if chat_id in self._storage:
                self._storage[chat_id].pop(user_id, None)
                self._expiry[chat_id].pop(user_id, None)

pending_manager = PendingStateManager(expiry_seconds=300)

# =============================================================================
# SECTION 7: DATABASE SERVICE LAYER
# =============================================================================
class DatabaseService:
    """Singleton database service with connection pooling."""
    
    _instance: Optional['DatabaseService'] = None
    _pool: Optional[asyncpg.Pool] = None
    _lock = asyncio.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    async def initialize(self) -> None:
        async with self._lock:
            if self._pool is None:
                self._pool = await asyncpg.create_pool(
                    DATABASE_URL,
                    min_size=5,
                    max_size=20,
                    command_timeout=60,
                )
                logger.info("Database pool initialized")
    
    async def close(self) -> None:
        async with self._lock:
            if self._pool:
                await self._pool.close()
                self._pool = None
                logger.info("Database pool closed")
    
    @asynccontextmanager
    async def acquire(self):
        if self._pool is None:
            await self.initialize()
        async with self._pool.acquire() as conn:
            yield conn
    
    @asynccontextmanager
    async def transaction(self):
        async with self.acquire() as conn:
            async with conn.transaction():
                yield conn
    
    # ==================== SCHEMA INITIALIZATION ====================
    async def init_schema(self) -> None:
        async with self.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users_global (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT NOT NULL DEFAULT 'Unknown',
                    total_xp BIGINT NOT NULL DEFAULT 0,
                    total_coins BIGINT NOT NULL DEFAULT 0,
                    level INT NOT NULL DEFAULT 0,
                    last_updated TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS groups (
                    chat_id BIGINT PRIMARY KEY,
                    title TEXT,
                    username TEXT,
                    invite_link TEXT,
                    added_on TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users_per_group (
                    user_id BIGINT NOT NULL,
                    chat_id BIGINT NOT NULL,
                    username TEXT NOT NULL DEFAULT 'Unknown',
                    msg_count INT NOT NULL DEFAULT 0,
                    xp INT NOT NULL DEFAULT 0,
                    coins INT NOT NULL DEFAULT 0,
                    last_daily TIMESTAMPTZ,
                    last_scratch TIMESTAMPTZ,
                    shield_expiry TIMESTAMPTZ,
                    is_dead BOOLEAN NOT NULL DEFAULT FALSE,
                    is_verified_owner INT NOT NULL DEFAULT 0,
                    PRIMARY KEY (user_id, chat_id)
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS gifts (
                    id SERIAL PRIMARY KEY,
                    from_user BIGINT NOT NULL,
                    to_user BIGINT NOT NULL,
                    chat_id BIGINT NOT NULL,
                    gift_type TEXT NOT NULL,
                    amount INT NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            # Guild tables with owner_id support
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS guilds (
                    guild_id SERIAL PRIMARY KEY,
                    name TEXT UNIQUE NOT NULL,
                    owner_id BIGINT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    total_xp BIGINT NOT NULL DEFAULT 0,
                    member_count INT NOT NULL DEFAULT 0
                )
            """)
            await conn.execute("ALTER TABLE guilds ADD COLUMN IF NOT EXISTS owner_id BIGINT")
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS guild_members (
                    user_id BIGINT PRIMARY KEY,
                    guild_id INT REFERENCES guilds(guild_id) ON DELETE CASCADE,
                    joined_at TIMESTAMPTZ DEFAULT NOW(),
                    contribution_xp BIGINT NOT NULL DEFAULT 0
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS guild_leave_cooldown (
                    user_id BIGINT PRIMARY KEY,
                    left_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            # Indexes
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_global_xp ON users_global(total_xp DESC)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_global_coins ON users_global(total_coins DESC)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_per_group_chat ON users_per_group(chat_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_per_group_xp ON users_per_group(chat_id, xp DESC)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_per_group_coins ON users_per_group(chat_id, coins DESC)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_per_group_username ON users_per_group(chat_id, username)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_gifts_to_user ON gifts(to_user)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_guilds_name ON guilds(name)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_guilds_created_at ON guilds(created_at)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_guild_members_guild_user ON guild_members(guild_id, user_id)")
            logger.info("Database schema initialized successfully")
    
    # ==================== USER GLOBAL OPERATIONS ====================
    async def get_user_global(self, user_id: int) -> Optional[Dict[str, Any]]:
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM users_global WHERE user_id = $1",
                user_id
            )
            return dict(row) if row else None
    
    async def update_user_global(self, user_id: int, username: str, xp_delta: int = 0, coins_delta: int = 0) -> None:
        async with self.acquire() as conn:
            await conn.execute("""
                INSERT INTO users_global (user_id, username, total_xp, total_coins, last_updated)
                VALUES ($1, $2, GREATEST($3, 0), GREATEST($4, 0), NOW())
                ON CONFLICT (user_id) DO UPDATE
                SET username = EXCLUDED.username,
                    total_xp = GREATEST(users_global.total_xp + EXCLUDED.total_xp, 0),
                    total_coins = GREATEST(users_global.total_coins + EXCLUDED.total_coins, 0),
                    last_updated = NOW()
            """, user_id, username, xp_delta, coins_delta)
    
    async def get_global_leaderboard(self, limit: int = 10) -> List[Dict[str, Any]]:
        async with self.acquire() as conn:
            rows = await conn.fetch("""
                SELECT username, total_xp, total_coins, (total_xp / $1)::int as level
                FROM users_global
                ORDER BY total_xp DESC
                LIMIT $2
            """, XP_PER_LEVEL, limit)
            return [dict(r) for r in rows]
    
    async def get_riches_leaderboard(self, limit: int = 10) -> List[Dict[str, Any]]:
        async with self.acquire() as conn:
            rows = await conn.fetch("""
                SELECT username, total_coins
                FROM users_global
                ORDER BY total_coins DESC
                LIMIT $1
            """, limit)
            return [dict(r) for r in rows]
    
    async def get_user_total_messages(self, user_id: int) -> int:
        async with self.acquire() as conn:
            result = await conn.fetchval(
                "SELECT COALESCE(SUM(msg_count), 0) FROM users_per_group WHERE user_id = $1",
                user_id
            )
            return result or 0
    
    async def get_all_user_ids(self) -> List[int]:
        """Get all user IDs from users_global."""
        async with self.acquire() as conn:
            rows = await conn.fetch("SELECT user_id FROM users_global")
            return [r['user_id'] for r in rows]
    
    # ==================== USER PER GROUP OPERATIONS ====================
    async def get_user_per_group(self, user_id: int, chat_id: int) -> Optional[Dict[str, Any]]:
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM users_per_group WHERE user_id = $1 AND chat_id = $2",
                user_id, chat_id
            )
            return dict(row) if row else None
    
    async def update_user_per_group(
        self,
        user_id: int,
        chat_id: int,
        username: str,
        xp_delta: int = 0,
        coins_delta: int = 0,
        msg_inc: bool = False,
        shield_expiry: Optional[datetime] = None,
        set_dead: Optional[bool] = None,
        last_daily: bool = False,
        last_scratch: bool = False,
        is_verified_owner: Optional[int] = None,
    ) -> None:
        async with self.acquire() as conn:
            set_clauses = ["username = EXCLUDED.username"]
            
            if xp_delta != 0:
                set_clauses.append("xp = GREATEST(users_per_group.xp + $4, 0)")
            if coins_delta != 0:
                set_clauses.append("coins = GREATEST(users_per_group.coins + $5, 0)")
            if msg_inc:
                set_clauses.append("msg_count = users_per_group.msg_count + 1")
            if shield_expiry is not None:
                set_clauses.append("shield_expiry = $6")
            if set_dead is not None:
                set_clauses.append("is_dead = $7")
            if last_daily:
                set_clauses.append("last_daily = NOW()")
            if last_scratch:
                set_clauses.append("last_scratch = NOW()")
            if is_verified_owner is not None:
                set_clauses.append("is_verified_owner = $8")
            
            set_clause_str = ", ".join(set_clauses)
            
            query = f"""
                INSERT INTO users_per_group (
                    user_id, chat_id, username,
                    xp, coins, msg_count,
                    shield_expiry, is_dead, is_verified_owner,
                    last_daily, last_scratch
                )
                VALUES (
                    $1, $2, $3,
                    GREATEST($4, 0), GREATEST($5, 0), CASE WHEN $9::bool THEN 1 ELSE 0 END,
                    $6, COALESCE($7, FALSE), COALESCE($8, 0),
                    CASE WHEN $10::bool THEN NOW() ELSE NULL END,
                    CASE WHEN $11::bool THEN NOW() ELSE NULL END
                )
                ON CONFLICT (user_id, chat_id) DO UPDATE
                SET {set_clause_str}
            """
            
            await conn.execute(
                query,
                user_id,
                chat_id,
                username,
                xp_delta,
                coins_delta,
                shield_expiry,
                set_dead,
                is_verified_owner,
                msg_inc,
                last_daily,
                last_scratch,
            )
    
    async def get_group_leaderboard(self, chat_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        async with self.acquire() as conn:
            rows = await conn.fetch("""
                SELECT username, xp, (xp / $1)::int as level
                FROM users_per_group
                WHERE chat_id = $2
                ORDER BY xp DESC
                LIMIT $3
            """, XP_PER_LEVEL, chat_id, limit)
            return [dict(r) for r in rows]
    
    async def get_group_riches(self, chat_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        async with self.acquire() as conn:
            rows = await conn.fetch("""
                SELECT username, coins
                FROM users_per_group
                WHERE chat_id = $1
                ORDER BY coins DESC
                LIMIT $2
            """, chat_id, limit)
            return [dict(r) for r in rows]
    
    async def find_user_by_username(self, chat_id: int, username: str) -> Optional[int]:
        clean_name = username.lstrip('@').strip()
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT user_id FROM users_per_group WHERE chat_id = $1 AND (LOWER(username) = LOWER($2) OR LOWER(username) = LOWER($3)) LIMIT 1",
                chat_id, clean_name, f"@{clean_name}"
            )
            if not row:
                row = await conn.fetchrow(
                    "SELECT user_id FROM users_global WHERE LOWER(username) = LOWER($1) OR LOWER(username) = LOWER($2) LIMIT 1",
                    clean_name, f"@{clean_name}"
                )
            return row['user_id'] if row else None
    
    async def get_user_chat_ids(self, user_id: int) -> List[int]:
        async with self.acquire() as conn:
            rows = await conn.fetch(
                "SELECT DISTINCT chat_id FROM users_per_group WHERE user_id = $1",
                user_id
            )
            return [r['chat_id'] for r in rows]
    
    # ==================== ATOMIC COIN OPERATIONS ====================
    async def transfer_coins(
        self,
        from_user_id: int,
        to_user_id: int,
        chat_id: int,
        amount: int,
        from_username: str,
        to_username: str,
    ) -> Tuple[bool, str]:
        async with self.transaction() as conn:
            sender = await conn.fetchrow(
                "SELECT coins FROM users_per_group WHERE user_id = $1 AND chat_id = $2 FOR UPDATE",
                from_user_id, chat_id
            )
            if not sender:
                return False, "Sender not found in this group."
            if sender['coins'] < amount:
                return False, f"Insufficient coins. You have {format_number(sender['coins'])}."
            
            await conn.execute("""
                UPDATE users_per_group
                SET coins = coins - $1
                WHERE user_id = $2 AND chat_id = $3
            """, amount, from_user_id, chat_id)
            
            await conn.execute("""
                INSERT INTO users_per_group (user_id, chat_id, username, coins)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (user_id, chat_id) DO UPDATE
                SET coins = users_per_group.coins + EXCLUDED.coins,
                    username = EXCLUDED.username
            """, to_user_id, chat_id, to_username, amount)
            
            await conn.execute("""
                INSERT INTO users_global (user_id, username, total_coins)
                VALUES ($1, $2, 0)
                ON CONFLICT (user_id) DO UPDATE
                SET total_coins = GREATEST(users_global.total_coins - $3, 0),
                    username = EXCLUDED.username
            """, from_user_id, from_username, amount)
            
            await conn.execute("""
                INSERT INTO users_global (user_id, username, total_coins)
                VALUES ($1, $2, $3)
                ON CONFLICT (user_id) DO UPDATE
                SET total_coins = users_global.total_coins + EXCLUDED.total_coins,
                    username = EXCLUDED.username
            """, to_user_id, to_username, amount)
            
            return True, "Transfer successful"
    
    # ==================== GIFT OPERATIONS ====================
    async def add_gift(self, from_user: int, to_user: int, chat_id: int, gift_type: str, amount: int) -> None:
        async with self.acquire() as conn:
            await conn.execute("""
                INSERT INTO gifts (from_user, to_user, chat_id, gift_type, amount, created_at)
                VALUES ($1, $2, $3, $4, $5, NOW())
            """, from_user, to_user, chat_id, gift_type, amount)
    
    async def get_gifts(self, user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        async with self.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM gifts WHERE to_user = $1
                ORDER BY created_at DESC LIMIT $2
            """, user_id, limit)
            return [dict(r) for r in rows]
    
    # ==================== GROUP OPERATIONS ====================
    async def add_group(self, chat_id: int, title: str, username: Optional[str], invite_link: Optional[str]) -> None:
        async with self.acquire() as conn:
            await conn.execute("""
                INSERT INTO groups (chat_id, title, username, invite_link, added_on)
                VALUES ($1, $2, $3, $4, NOW())
                ON CONFLICT (chat_id) DO UPDATE
                SET title = EXCLUDED.title,
                    username = EXCLUDED.username,
                    invite_link = EXCLUDED.invite_link
            """, chat_id, title, username, invite_link)
    
    async def remove_group(self, chat_id: int) -> None:
        async with self.acquire() as conn:
            await conn.execute("DELETE FROM groups WHERE chat_id = $1", chat_id)
    
    async def get_all_groups(self) -> List[Dict[str, Any]]:
        async with self.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM groups ORDER BY added_on DESC")
            return [dict(r) for r in rows]
    
    async def get_group_stats(self, chat_id: int) -> Dict[str, Any]:
        async with self.acquire() as conn:
            top_user = await conn.fetchrow("""
                SELECT username, xp FROM users_per_group
                WHERE chat_id = $1 ORDER BY xp DESC LIMIT 1
            """, chat_id)
            user_count = await conn.fetchval(
                "SELECT COUNT(*) FROM users_per_group WHERE chat_id = $1",
                chat_id
            )
            return {
                "top_user": dict(top_user) if top_user else None,
                "user_count": user_count or 0,
            }
    
    # ==================== GUILD OPERATIONS ====================
    async def create_guild(self, name: str, creator_id: Optional[int] = None) -> int:
        """Create a new guild. Returns guild_id. Raises ValueError if name exists or max guilds reached."""
        async with self.transaction() as conn:
            count = await conn.fetchval("SELECT COUNT(*) FROM guilds")
            if count >= MAX_GUILDS:
                raise ValueError(f"Maximum guilds ({MAX_GUILDS}) reached.")
            guild_id = await conn.fetchval(
                "INSERT INTO guilds (name, owner_id) VALUES ($1, $2) RETURNING guild_id",
                name, creator_id
            )
            logger.info(f"Guild created: {name} (ID: {guild_id}) by user {creator_id}")
            return guild_id
    
    async def delete_guild(self, guild_id: int, admin_id: Optional[int] = None) -> None:
        """Delete a guild. Members are automatically removed via CASCADE."""
        async with self.acquire() as conn:
            guild = await self.get_guild_by_id(guild_id)
            name = guild['name'] if guild else 'Unknown'
            await conn.execute("DELETE FROM guilds WHERE guild_id = $1", guild_id)
            logger.info(f"Guild deleted: {name} (ID: {guild_id}) by admin {admin_id}")
    
    async def get_guild_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        async with self.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM guilds WHERE LOWER(name) = LOWER($1)", name)
            return dict(row) if row else None
    
    async def get_guild_by_id(self, guild_id: int) -> Optional[Dict[str, Any]]:
        async with self.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM guilds WHERE guild_id = $1", guild_id)
            return dict(row) if row else None
    
    async def list_guilds(self) -> List[Dict[str, Any]]:
        async with self.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM guilds ORDER BY name")
            return [dict(r) for r in rows]
    
    async def get_user_guild(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get the guild of a user, if any."""
        async with self.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT g.* FROM guilds g
                JOIN guild_members gm ON g.guild_id = gm.guild_id
                WHERE gm.user_id = $1
            """, user_id)
            return dict(row) if row else None
    
    async def add_user_to_guild(self, user_id: int, guild_id: int, username: str) -> Tuple[bool, str]:
        """Add user to guild. Returns (success, message)."""
        async with self.transaction() as conn:
            guild = await conn.fetchrow("SELECT * FROM guilds WHERE guild_id = $1 FOR UPDATE", guild_id)
            if not guild:
                return False, "Guild does not exist."
            member_count = guild['member_count']
            if member_count >= MAX_GUILD_MEMBERS:
                return False, f"Guild is full (max {MAX_GUILD_MEMBERS} members)."
            existing = await conn.fetchval("SELECT 1 FROM guild_members WHERE user_id = $1", user_id)
            if existing:
                return False, "You are already in a guild."
            cooldown_row = await conn.fetchrow(
                "SELECT left_at FROM guild_leave_cooldown WHERE user_id = $1",
                user_id
            )
            if cooldown_row:
                left_at = cooldown_row['left_at']
                if left_at.tzinfo is None:
                    left_at = IST.localize(left_at)
                now = datetime.now(IST)
                if (now - left_at).total_seconds() < GUILD_REJOIN_COOLDOWN:
                    remaining = GUILD_REJOIN_COOLDOWN - int((now - left_at).total_seconds())
                    hours = remaining // 3600
                    minutes = (remaining % 3600) // 60
                    return False, f"You must wait {hours}h {minutes}m before joining another guild."
            await conn.execute("""
                INSERT INTO guild_members (user_id, guild_id, contribution_xp)
                VALUES ($1, $2, 0)
            """, user_id, guild_id)
            await conn.execute("UPDATE guilds SET member_count = member_count + 1 WHERE guild_id = $1", guild_id)
            await conn.execute("DELETE FROM guild_leave_cooldown WHERE user_id = $1", user_id)
            logger.info(f"User {user_id} joined guild {guild_id}")
            return True, "Successfully joined the guild."
    
    async def remove_user_from_guild(self, user_id: int) -> Tuple[bool, str]:
        """Remove user from their current guild. Returns (success, message)."""
        async with self.transaction() as conn:
            guild_id = await conn.fetchval("SELECT guild_id FROM guild_members WHERE user_id = $1", user_id)
            if not guild_id:
                return False, "You are not in any guild."
            await conn.execute("DELETE FROM guild_members WHERE user_id = $1", user_id)
            await conn.execute("UPDATE guilds SET member_count = GREATEST(member_count - 1, 0) WHERE guild_id = $1", guild_id)
            await conn.execute("""
                INSERT INTO guild_leave_cooldown (user_id, left_at)
                VALUES ($1, NOW())
                ON CONFLICT (user_id) DO UPDATE SET left_at = NOW()
            """, user_id)
            logger.info(f"User {user_id} left guild {guild_id}")
            return True, "You have left the guild."
    
    async def add_guild_xp(self, guild_id: int, xp: int, user_id: Optional[int] = None) -> None:
        """Add XP to a guild. If user_id provided, also update user's contribution."""
        async with self.transaction() as conn:
            await conn.execute("UPDATE guilds SET total_xp = total_xp + $1 WHERE guild_id = $2", xp, guild_id)
            if user_id:
                await conn.execute("""
                    UPDATE guild_members SET contribution_xp = contribution_xp + $1
                    WHERE user_id = $2 AND guild_id = $3
                """, xp, user_id, guild_id)
    
    async def add_guild_xp_for_user(self, user_id: int, xp: int) -> None:
        """If user is in a guild, add XP to that guild and update their contribution."""
        guild = await self.get_user_guild(user_id)
        if guild:
            await self.add_guild_xp(guild['guild_id'], xp, user_id)
    
    async def get_guild_leaderboard(self, limit: int = 10) -> List[Dict[str, Any]]:
        async with self.acquire() as conn:
            rows = await conn.fetch("""
                SELECT name, total_xp, member_count,
                       (SELECT COUNT(*) FROM guild_members gm WHERE gm.guild_id = g.guild_id) as members
                FROM guilds g
                ORDER BY total_xp DESC
                LIMIT $1
            """, limit)
            result = []
            for r in rows:
                d = dict(r)
                d['level'] = self.calculate_guild_level(d['total_xp'])
                result.append(d)
            return result
    
    async def get_guild_members(self, guild_id: int) -> List[Dict[str, Any]]:
        async with self.acquire() as conn:
            rows = await conn.fetch("""
                SELECT gm.user_id, gm.joined_at, gm.contribution_xp,
                       COALESCE(ug.username, 'Unknown') as username
                FROM guild_members gm
                LEFT JOIN users_global ug ON gm.user_id = ug.user_id
                WHERE gm.guild_id = $1
                ORDER BY gm.contribution_xp DESC
            """, guild_id)
            return [dict(r) for r in rows]
    
    @staticmethod
    def calculate_guild_level(total_xp: int) -> int:
        """Calculate guild level based on XP thresholds."""
        level = 1
        for i, thresh in enumerate(GUILD_LEVEL_THRESHOLDS[1:], start=2):
            if total_xp >= thresh:
                level = i
            else:
                break
        return level

# Global database service instance
db = DatabaseService()

# =============================================================================
# SECTION 8: AI SERVICE
# =============================================================================
class AIService:
    def __init__(self):
        self._client: Optional[Groq] = None
        if GROQ_API_KEY:
            self._client = Groq(api_key=GROQ_API_KEY)
    
    async def roast(self, target_name: str, context: str = "") -> str:
        if not self._client:
            return "AI is not configured right now. Stay safe!"
        
        prompt = f"Roast {target_name}. Keep it under 20 words, savage, witty, use modern slang and emojis."
        if context:
            prompt += f" Context: {context}"
        
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self._client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=[
                        {"role": "system", "content": "You are a savage, witty roaster."},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=100,
                )
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"AI error: {e}")
            return "AI is recharging its savage energy. Try again later!"
    
    async def ask(self, question: str) -> str:
        if not self._client:
            return "AI is not configured."
        
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self._client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=[
                        {"role": "system", "content": "You are a helpful, elite AI assistant named Lumira."},
                        {"role": "user", "content": question},
                    ],
                    max_tokens=500,
                )
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"AI error: {e}")
            return "AI is sleeping. Try again later!"

ai_service = AIService()

# =============================================================================
# SECTION 9: UI FORMATTING UTILITIES (PREMIUM VIBE)
# =============================================================================
def get_level_symbol(level: int) -> str:
    for low, high, sym in LEVEL_SYMBOLS:
        if low <= level <= high:
            return sym
    return "☬"

def format_number(num: Union[int, float]) -> str:
    try:
        return f"{int(num):,}"
    except Exception:
        return str(num)

def create_progress_bar(current: int, total: int, length: int = 12) -> str:
    if total <= 0:
        return f"[{'▒' * length}] 0%"
    percentage = min(100, max(0, int((current / total) * 100)))
    filled = int((percentage / 100) * length)
    bar = "█" * filled + "▒" * (length - filled)
    return f"[{bar}] {percentage}%"

def border_text(title: str, content: str) -> str:
    separator = "─" * 22
    clean_title = title.strip().upper()
    return f"╔════ ✧ {clean_title} ✧ ════╗\n{content.strip()}\n╚{separator}╝"

def styled_box(title: str, lines: List[str], emoji: str = "✨") -> str:
    content = "\n".join(f" {emoji} ❭ {line}" for line in lines)
    return border_text(title, content)

# =============================================================================
# SECTION 10: DECORATORS & MIDDLEWARE
# =============================================================================
def require_group(func: Callable) -> Callable:
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if not update.effective_chat:
            return
        if update.effective_chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
            await update.message.reply_text(
                border_text("𝐍𝐎𝐓𝐈𝐂𝐄", "❌ This command can only be used inside Telegram Groups or Supergroups."),
                parse_mode=ParseMode.HTML
            )
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

def rate_limit_command(command_name: str):
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            user_id = update.effective_user.id
            allowed, remaining = await rate_limiter.check(user_id, command_name)
            if not allowed:
                await update.message.reply_text(
                    border_text("⏳ 𝐑𝐀𝐓𝐄 𝐋𝐈𝐌𝐈𝐓", f"Please wait <b>{remaining}s</b> before using <code>/{command_name}</code> again."),
                    parse_mode=ParseMode.HTML
                )
                return
            return await func(update, context, *args, **kwargs)
        return wrapper
    return decorator

def safe_reply(func: Callable) -> Callable:
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        try:
            return await func(update, context, *args, **kwargs)
        except Exception as e:
            if "Message is not modified" in str(e):
                return
            logger.exception(f"Error in {func.__name__}")
            try:
                if update and update.effective_message:
                    await update.effective_message.reply_text(
                        border_text("❌ 𝐄𝐑𝐑𝐎𝐑", "An internal error occurred while processing your request. Please try again soon."),
                        parse_mode=ParseMode.HTML
                    )
            except Exception:
                pass
    return wrapper

# =============================================================================
# SECTION 11: OWNER VERIFICATION
# =============================================================================
async def is_owner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check if user is global owner or verified group owner."""
    if not update.effective_user:
        return False
    user_id = update.effective_user.id
    if user_id == GLOBAL_OWNER_ID:
        return True
    
    if not update.effective_chat:
        return False
    chat_id = update.effective_chat.id
    try:
        perms = await context.bot.get_chat_member(chat_id, user_id)
        if perms.status == "creator":
            user_data = await db.get_user_per_group(user_id, chat_id)
            if user_data and user_data.get("is_verified_owner") == 1:
                return True
    except Exception as e:
        logger.error(f"Owner check error: {e}")
    
    return False

async def require_owner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not await is_owner(update, context):
        await update.message.reply_text(
            border_text("❌ 𝐀𝐂𝐂𝐄𝐒𝐒 𝐃𝐄𝐍𝐈𝐄𝐃", "Only the verified Group Owner or Global Master can execute this command."),
            parse_mode=ParseMode.HTML
        )
        return False
    return True

# =============================================================================
# SECTION 12: LEVEL & XP SYSTEM
# =============================================================================
async def process_message_xp(
    user_id: int,
    username: str,
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Process XP gain and handle level ups with broadcasting."""
    old_global = await db.get_user_global(user_id)
    old_level = old_global['total_xp'] // XP_PER_LEVEL if old_global else 0
    
    await db.update_user_per_group(user_id, chat_id, username, xp_delta=XP_PER_MESSAGE, msg_inc=True)
    await db.update_user_global(user_id, username, xp_delta=XP_PER_MESSAGE)
    await db.add_guild_xp_for_user(user_id, GUILD_XP_MESSAGE)
    
    new_global = await db.get_user_global(user_id)
    new_level = new_global['total_xp'] // XP_PER_LEVEL if new_global else 0
    
    if new_level > old_level:
        await handle_level_up(user_id, username, old_level, new_level, chat_id, context)

async def handle_level_up(
    user_id: int,
    username: str,
    old_level: int,
    new_level: int,
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Broadcast level up messages."""
    symbol = get_level_symbol(new_level)
    msg = border_text(
        "🎉 𝐋𝐄𝐕𝐄𝐋 𝐔𝐏 !",
        f"⚡ <b>@{username}</b> has ascended to <b>𝐋𝐞𝐯𝐞𝐥 {new_level}</b> (<code>{symbol}</code>)!\n"
        f"Keep chatting and conquering the ranks! 🔥"
    )
    try:
        await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Level up broadcast failed: {e}")
    
    if new_level >= MAX_LEVEL and old_level < MAX_LEVEL:
        await broadcast_elite(user_id, username, symbol, context)

async def broadcast_elite(
    user_id: int,
    username: str,
    symbol: str,
    context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Broadcast elite achievement to all user's groups."""
    chat_ids = await db.get_user_chat_ids(user_id)
    elite_msg = border_text(
        "★ 𝐄𝐋𝐈𝐓𝐄 𝐀𝐂𝐇𝐈𝐄𝐕𝐄𝐃 ★",
        f"👑 <b>@{username}</b> has reached the pinnacle of Lumira: <b>𝐄𝐋𝐈𝐓𝐄 {symbol}</b>!\n"
        f"A historic milestone! Everyone pay respects! 🎊"
    )
    for grp_id in chat_ids:
        try:
            await context.bot.send_message(chat_id=grp_id, text=elite_msg, parse_mode=ParseMode.HTML)
        except Exception:
            pass

# =============================================================================
# SECTION 13: SHIELD UTILITIES
# =============================================================================
def has_active_shield(user_data: Optional[Dict[str, Any]]) -> bool:
    if not user_data:
        return False
    shield_expiry = user_data.get('shield_expiry')
    if not shield_expiry:
        return False
    now = datetime.now(IST)
    if shield_expiry.tzinfo is None:
        shield_expiry = IST.localize(shield_expiry)
    return shield_expiry > now

# =============================================================================
# SECTION 14: COMMAND & INTERACTIVE WELCOME HANDLERS
# =============================================================================

@safe_reply
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Luxurious, clean premium welcome interface for private and group chats."""
    user = update.effective_user
    username = user.username or user.first_name
    await db.update_user_global(user.id, username)
    
    chat_type = update.effective_chat.type
    if chat_type == ChatType.PRIVATE:
        content = (
            f"👋 Welcome, <b>{user.first_name}</b>, to <b>𝓛𝓾𝓶𝓲𝓻𝓪</b>!\n\n"
            f"🌟 <b>Your Ultimate Production-Grade Group Master</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🛡️ <b>Advanced Economy & Shop</b> — Earn coins, shields & lottery tickets\n"
            f"⚡ <b>RPG Level & XP System</b> — Level up from 0 to 70 with custom emblems\n"
            f"🏰 <b>Guild Wars & Alliances</b> — Create or join guilds and dominate leaderboards\n"
            f"🤖 <b>AI Assistant & Savagery</b> — Powered by AI for savage roasts and Q&A\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"✨ <i>Add me to your group and promote to Admin for complete automation!</i>"
        )
        keyboard = [
            [
                InlineKeyboardButton("👑 Add to Group", url=f"https://t.me/{context.bot.username}?startgroup=true"),
                InlineKeyboardButton("📚 Help Dashboard", callback_data="help_main")
            ],
            [
                InlineKeyboardButton("📊 My Stats", callback_data="start_my_stats"),
                InlineKeyboardButton("🏆 Leaderboard", callback_data="start_leaderboard")
            ],
            [
                InlineKeyboardButton("💎 Top Riches", callback_data="start_riches"),
                InlineKeyboardButton("🏰 Guilds List", callback_data="start_guilds")
            ]
        ]
        await update.message.reply_text(
            border_text("𝓛𝓤𝓜𝓘𝓡𝓐 • 𝐏𝐑𝐄𝐌𝐈𝐔𝐌 𝐌𝐀𝐒𝐓𝐄𝐑", content),
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )
    else:
        content = (
            f"👋 Greetings, <b>{user.first_name}</b>!\n"
            f"✨ <b>𝓛𝓾𝓶𝓲𝓻𝓪</b> is actively monitoring <b>{update.effective_chat.title}</b>.\n\n"
            f"💬 Chat to earn XP & Coins automatically!\n"
            f"💡 Type /help or click below to view commands."
        )
        keyboard = [
            [
                InlineKeyboardButton("📚 Group Help", url=f"https://t.me/{context.bot.username}?start=help"),
                InlineKeyboardButton("🏆 Group Top XP", callback_data="help_grp_top")
            ]
        ]
        await update.message.reply_text(
            border_text("𝓛𝓤𝓜𝓘𝓡𝓐 • 𝐆𝐑𝐎𝐔𝐏 𝐀𝐂𝐓𝐈𝐕𝐄", content),
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )

@safe_reply
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Categorized interactive help menu with premium border layout."""
    user = update.effective_user.first_name or "User"
    content = (
        f"👋 Hello, <b>{user}</b>! Welcome to the <b>𝓛𝓾𝓶𝓲𝓻𝓪 Help Center</b>.\n\n"
        f"Select a category below to explore all available features, game mechanics, and commands:\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚡ <b>Level Up:</b> {format_number(XP_PER_LEVEL)} XP per level\n"
        f"🛡️ <b>Shield:</b> {format_number(SHIELD_COST)} coins ({SHIELD_DURATION_HOURS}h)\n"
        f"💰 <b>Daily Reward:</b> {format_number(DAILY_COINS)} coins every {DAILY_COOLDOWN_HOURS}h\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )
    keyboard = [
        [
            InlineKeyboardButton("👤 User & Economy", callback_data="help_user"),
            InlineKeyboardButton("⚔️ PVP & Games", callback_data="help_pvp")
        ],
        [
            InlineKeyboardButton("🏰 Guild System", callback_data="help_guild"),
            InlineKeyboardButton("📊 Group & Ranks", callback_data="help_group")
        ],
        [
            InlineKeyboardButton("👑 Owner Commands", callback_data="help_owner")
        ]
    ]
    await update.message.reply_text(
        border_text("𝓛𝓤𝓜𝓘𝓡𝓐 • 𝐂𝐎𝐌𝐌𝐀𝐍𝐃 𝐂𝐄𝐍𝐓𝐄𝐑", content),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )

@safe_reply
async def nav_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle interactive tab switching for /start and /help menus."""
    query = update.callback_query
    await query.answer()
    data = query.data
    user = query.from_user
    username = user.username or user.first_name

    if data == "help_main":
        content = (
            f"👋 Hello, <b>{user.first_name}</b>! Welcome to the <b>𝓛𝓾𝓶𝓲𝓻𝓪 Help Center</b>.\n\n"
            f"Select a category below to explore all available features and commands:\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ <b>Level Up:</b> {format_number(XP_PER_LEVEL)} XP per level\n"
            f"🛡️ <b>Shield:</b> {format_number(SHIELD_COST)} coins ({SHIELD_DURATION_HOURS}h)\n"
            f"💰 <b>Daily Reward:</b> {format_number(DAILY_COINS)} coins every {DAILY_COOLDOWN_HOURS}h\n"
            f"━━━━━━━━━━━━━━━━━━━━━━"
        )
        keyboard = [
            [
                InlineKeyboardButton("👤 User & Economy", callback_data="help_user"),
                InlineKeyboardButton("⚔️ PVP & Games", callback_data="help_pvp")
            ],
            [
                InlineKeyboardButton("🏰 Guild System", callback_data="help_guild"),
                InlineKeyboardButton("📊 Group & Ranks", callback_data="help_group")
            ],
            [
                InlineKeyboardButton("👑 Owner Commands", callback_data="help_owner")
            ]
        ]
        await query.edit_message_text(
            border_text("𝓛𝓤𝓜𝓘𝓡𝓐 • 𝐂𝐎𝐌𝐌𝐀𝐍𝐃 𝐂𝐄𝐍𝐓𝐄𝐑", content),
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )

    elif data == "help_user":
        content = (
            "<b>👤 USER & ECONOMY COMMANDS</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "┣ <code>/rank</code> — Check your profile & XP progress\n"
            "┣ <code>/daily</code> — Claim 100 free daily coins\n"
            "┣ <code>/scratch</code> — Try your luck on scratch card\n"
            "┣ <code>/shop</code> — Open item shop (Shields, XP, Lottery)\n"
            "┣ <code>/gift</code> (reply) — Send luxury gifts to users\n"
            "┣ <code>/mygifts</code> — View gifts received\n"
            "┗ <code>/ai &lt;question&gt;</code> — Ask AI assistant anything\n"
            "━━━━━━━━━━━━━━━━━━━━━━"
        )
        keyboard = [[InlineKeyboardButton("🔙 Back to Categories", callback_data="help_main")]]
        await query.edit_message_text(
            border_text("𝐇𝐄𝐋𝐏 • 𝐔𝐒𝐄𝐑 𝐂𝐎𝐌𝐌𝐀𝐍𝐃𝐒", content),
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )

    elif data == "help_pvp":
        content = (
            "<b>⚔️ PVP & FUN COMMANDS</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "┣ <code>/roast @user</code> — AI-powered savage roast\n"
            "┣ <code>/kill (reply)</code> — Assassinate a chat member\n"
            "┣ <code>/rob &lt;amount&gt; (reply)</code> — Steal coins\n"
            "┗ <code>/revive [@user]</code> — Revive yourself or friend\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "💡 <i>Tip: Buy a shield (`/shop`) to block roasts, robs, and kills!</i>"
        )
        keyboard = [[InlineKeyboardButton("🔙 Back to Categories", callback_data="help_main")]]
        await query.edit_message_text(
            border_text("𝐇𝐄𝐋𝐏 • 𝐏𝐕𝐏 & 𝐅𝐔𝐍", content),
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )

    elif data == "help_guild":
        content = (
            "<b>🏰 GUILD COMMANDS</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "┣ <code>/join_guild &lt;name&gt;</code> — Join a guild\n"
            "┣ <code>/leave_guild</code> — Leave your current guild\n"
            "┣ <code>/myguild</code> — View your guild's status\n"
            "┣ <code>/guild_leaderboard</code> — Top XP guilds\n"
            "┣ <code>/guild_members</code> — List members in your guild\n"
            "┗ <code>/guild_info &lt;name&gt;</code> — Inspect any guild\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "⚡ <i>Every chat message contributes XP to your guild!</i>"
        )
        keyboard = [[InlineKeyboardButton("🔙 Back to Categories", callback_data="help_main")]]
        await query.edit_message_text(
            border_text("𝐇𝐄𝐋𝐏 • 𝐆𝐔𝐈𝐋𝐃𝐒", content),
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )

    elif data == "help_group":
        content = (
            "<b>📊 GROUP & LEADERBOARD COMMANDS</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "┣ <code>/leaderboard</code> — Top 10 Global XP Masters\n"
            "┣ <code>/riches</code> — Top 10 Global Millionaires\n"
            "┣ <code>/grpleaderboard</code> — Top 10 Group XP Elite\n"
            "┗ <code>/grpriches</code> — Top 10 Group Coin Kings\n"
            "━━━━━━━━━━━━━━━━━━━━━━"
        )
        keyboard = [[InlineKeyboardButton("🔙 Back to Categories", callback_data="help_main")]]
        await query.edit_message_text(
            border_text("𝐇𝐄𝐋𝐏 • 𝐋𝐄𝐀𝐃𝐄𝐑𝐁𝐎𝐀𝐑𝐃𝐒", content),
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )

    elif data == "help_owner":
        content = (
            "<b>👑 OWNER & ADMIN COMMANDS</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "┣ <code>/analytics</code> — Detailed chat statistics\n"
            "┣ <code>/members</code> — Total members & admin info\n"
            "┣ <code>/top</code> — Quick group XP leaderboard\n"
            "┣ <code>/addcoins</code> (reply) — Add coins to user\n"
            "┣ <code>/removecoins</code> (reply) — Deduct coins\n"
            "┣ <code>/stats</code> — List all monitored bot groups\n"
            "┣ <code>/newguild &lt;name&gt;</code> — Create new guild\n"
            "┣ <code>/delguild &lt;name&gt;</code> — Delete a guild\n"
            "┣ <code>/guilds_list</code> — List all registered guilds\n"
            "┣ <code>/transfer_guild</code> — Transfer/assign ownership\n"
            "┣ <code>/rename_guild</code> — Rename existing guild\n"
            "┣ <code>/guild_stats &lt;name&gt;</code> — Deep guild analytics\n"
            "┗ <code>/broadcast</code> (DM) — Broadcast message globally\n"
            "━━━━━━━━━━━━━━━━━━━━━━"
        )
        keyboard = [[InlineKeyboardButton("🔙 Back to Categories", callback_data="help_main")]]
        await query.edit_message_text(
            border_text("𝐇𝐄𝐋𝐏 • 𝐎𝐖𝐍𝐄𝐑 & 𝐀𝐃𝐌𝐈𝐍", content),
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )

    elif data == "start_my_stats":
        global_data = await db.get_user_global(user.id)
        if not global_data:
            await query.edit_message_text("❌ No profile records found yet. Send a message to start tracking!")
            return
        total_xp = global_data['total_xp']
        total_coins = global_data['total_coins']
        level = min(total_xp // XP_PER_LEVEL, MAX_LEVEL)
        symbol = get_level_symbol(level)
        xp_to_next = XP_PER_LEVEL - (total_xp % XP_PER_LEVEL) if level < MAX_LEVEL else 0
        total_msgs = await db.get_user_total_messages(user.id)
        progress = create_progress_bar(XP_PER_LEVEL - xp_to_next, XP_PER_LEVEL)
        content = (
            f"👤 <b>@{username}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"✨ <b>𝐓𝐨𝐭𝐚𝐥 𝐗𝐏 :</b> {format_number(total_xp)}\n"
            f"🆙 <b>𝐋𝐞𝐯𝐞𝐥    :</b> {level} <code>{symbol}</code>\n"
            f"📊 <b>𝐏𝐫𝐨𝐠𝐫𝐞𝐬𝐬 :</b> {progress}\n"
            f"💰 <b>𝐂𝐨𝐢𝐧𝐬    :</b> {format_number(total_coins)} 💰\n"
            f"📨 <b>𝐌𝐞𝐬𝐬𝐚𝐠𝐞𝐬 :</b> {format_number(total_msgs)}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━"
        )
        keyboard = [[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="help_main")]]
        await query.edit_message_text(
            border_text("𝐘𝐎𝐔𝐑 𝐆𝐋𝐎𝐁𝐀𝐋 𝐏𝐑𝐎𝐅𝐈𝐋𝐄", content),
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )

    elif data == "start_leaderboard":
        rows = await db.get_global_leaderboard(limit=10)
        lines = []
        for i, row in enumerate(rows):
            name = row['username'] or "Unknown"
            level = min(row['level'], MAX_LEVEL)
            symbol = get_level_symbol(level)
            xp = format_number(row['total_xp'])
            lines.append(f"{MEDALS[i] if i < len(MEDALS) else f'{i+1}.'} @{name} • L{level}<code>{symbol}</code> • {xp} XP")
        content = "\n".join(lines) if lines else "No global XP recorded yet."
        keyboard = [[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="help_main")]]
        await query.edit_message_text(
            border_text("𝐆𝐋𝐎𝐁𝐀𝐋 𝐗𝐏 𝐋𝐄𝐀𝐃𝐄𝐑𝐁𝐎𝐀𝐑𝐃", content),
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )

    elif data == "start_riches":
        rows = await db.get_riches_leaderboard(limit=10)
        lines = []
        for i, row in enumerate(rows):
            title = RICHES_TITLES[i] if i < len(RICHES_TITLES) else f"{i+1}."
            name = row['username'] or "Unknown"
            coins = format_number(row['total_coins'])
            lines.append(f"{title} @{name} • {coins} 💰")
        content = "\n".join(lines) if lines else "No coin hoarders yet."
        keyboard = [[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="help_main")]]
        await query.edit_message_text(
            border_text("𝐆𝐋𝐎𝐁𝐀𝐋 𝐂𝐎𝐈𝐍 𝐇𝐎𝐀𝐑𝐃𝐄𝐑𝐒", content),
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )

    elif data == "start_guilds":
        guilds = await db.get_guild_leaderboard(limit=10)
        lines = []
        for i, g in enumerate(guilds):
            medal = MEDALS[i] if i < len(MEDALS) else f"{i+1}."
            lines.append(f"{medal} <b>{g['name']}</b>")
            lines.append(f"   📊 Lvl {g['level']} • {format_number(g['total_xp'])} XP • 👥 {g['members']} members")
        content = "\n".join(lines) if lines else "No guilds created yet. Use /newguild or /join_guild!"
        keyboard = [[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="help_main")]]
        await query.edit_message_text(
            border_text("𝐓𝐎𝐏 𝐆𝐔𝐈𝐋𝐃𝐒 𝐋𝐄𝐀𝐃𝐄𝐑𝐁𝐎𝐀𝐑𝐃", content),
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )

    elif data == "help_grp_top":
        if not query.message.chat or query.message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
            await query.answer("❌ This option works best inside a group chat!", show_alert=True)
            return
        chat_id = query.message.chat.id
        rows = await db.get_group_leaderboard(chat_id, limit=10)
        lines = []
        for i, row in enumerate(rows):
            name = row['username'] or "Unknown"
            level = min(row['level'], MAX_LEVEL)
            symbol = get_level_symbol(level)
            xp = format_number(row['xp'])
            lines.append(f"{MEDALS[i] if i < len(MEDALS) else f'{i+1}.'} @{name} • L{level}<code>{symbol}</code> • {xp} XP")
        content = "\n".join(lines) if lines else "No chat XP in this group yet."
        await query.edit_message_text(
            border_text("𝐓𝐇𝐈𝐒 𝐆𝐑𝐎𝐔𝐏'𝐒 𝐗𝐏 𝐄𝐋𝐈𝐓𝐄", content),
            parse_mode=ParseMode.HTML
        )

@safe_reply
@require_group
async def rank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    
    global_data = await db.get_user_global(user_id)
    if not global_data:
        await update.message.reply_text(
            border_text("𝐍𝐎 𝐒𝐓𝐀𝐓𝐒", "❌ You don't have any stats yet. Send a few messages to start your journey!"),
            parse_mode=ParseMode.HTML
        )
        return
    
    total_xp = global_data['total_xp']
    total_coins = global_data['total_coins']
    level = min(total_xp // XP_PER_LEVEL, MAX_LEVEL)
    symbol = get_level_symbol(level)
    xp_to_next = XP_PER_LEVEL - (total_xp % XP_PER_LEVEL) if level < MAX_LEVEL else 0
    total_msgs = await db.get_user_total_messages(user_id)
    
    progress = create_progress_bar(XP_PER_LEVEL - xp_to_next, XP_PER_LEVEL)
    
    content = (
        f"👤 <b>@{username}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✨ <b>𝐓𝐨𝐭𝐚𝐥 𝐗𝐏    :</b> {format_number(total_xp)}\n"
        f"🆙 <b>𝐋𝐞𝐯𝐞𝐥       :</b> {level} <code>{symbol}</code>\n"
        f"📊 <b>𝐏𝐫𝐨𝐠𝐫𝐞𝐬𝐬    :</b> {progress}\n"
        f"💰 <b>𝐓𝐨𝐭𝐚𝐥 𝐂𝐨𝐢𝐧𝐬 :</b> {format_number(total_coins)}\n"
        f"📨 <b>𝐌𝐞𝐬𝐬𝐚𝐠𝐞𝐬    :</b> {format_number(total_msgs)}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🕒 <i>Status: Active & Synchronized</i>"
    )
    await update.message.reply_text(border_text("𝐘𝐎𝐔𝐑 𝐆𝐋𝐎𝐁𝐀𝐋 𝐏𝐑𝐎𝐅𝐈𝐋𝐄", content), parse_mode=ParseMode.HTML)

@safe_reply
async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = await db.get_global_leaderboard(limit=10)
    if not rows:
        await update.message.reply_text(border_text("𝐋𝐄𝐀𝐃𝐄𝐑𝐁𝐎𝐀𝐑𝐃", "❌ No global XP records yet."), parse_mode=ParseMode.HTML)
        return
    
    lines = []
    for i, row in enumerate(rows):
        name = row['username'] or "Unknown"
        level = min(row['level'], MAX_LEVEL)
        symbol = get_level_symbol(level)
        xp = format_number(row['total_xp'])
        medal = MEDALS[i] if i < len(MEDALS) else f"{i+1}."
        lines.append(f"{medal} @{name} • L{level}<code>{symbol}</code> • {xp} XP")
    
    content = "\n".join(lines) + "\n\n🔥 <i>Keep active in chat to ascend the hierarchy!</i>"
    await update.message.reply_text(border_text("𝐆𝐋𝐎𝐁𝐀𝐋 𝐗𝐏 𝐋𝐄𝐀𝐃𝐄𝐑𝐁𝐎𝐀𝐑𝐃", content), parse_mode=ParseMode.HTML)

@safe_reply
async def riches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = await db.get_riches_leaderboard(limit=10)
    if not rows:
        await update.message.reply_text(border_text("𝐑𝐈𝐂𝐇𝐄𝐒", "❌ No coin records yet."), parse_mode=ParseMode.HTML)
        return
    
    lines = []
    for i, row in enumerate(rows):
        title = RICHES_TITLES[i] if i < len(RICHES_TITLES) else f"{i+1}."
        name = row['username'] or "Unknown"
        coins = format_number(row['total_coins'])
        lines.append(f"{title} @{name} • {coins} 💰")
    
    content = "\n".join(lines) + "\n\n💎 <i>Hoard coins through daily rewards and lucky scratch cards!</i>"
    await update.message.reply_text(border_text("𝐆𝐋𝐎𝐁𝐀𝐋 𝐂𝐎𝐈𝐍 𝐇𝐎𝐀𝐑𝐃𝐄𝐑𝐒", content), parse_mode=ParseMode.HTML)

@safe_reply
@require_group
async def grpleaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    rows = await db.get_group_leaderboard(chat_id, limit=10)
    if not rows:
        await update.message.reply_text(border_text("𝐆𝐑𝐎𝐔𝐏 𝐑𝐀𝐍𝐊𝐒", "❌ No group stats recorded yet."), parse_mode=ParseMode.HTML)
        return
    
    lines = []
    for i, row in enumerate(rows):
        name = row['username'] or "Unknown"
        level = min(row['level'], MAX_LEVEL)
        symbol = get_level_symbol(level)
        xp = format_number(row['xp'])
        medal = MEDALS[i] if i < len(MEDALS) else f"{i+1}."
        lines.append(f"{medal} @{name} • L{level}<code>{symbol}</code> • {xp} XP")
    
    content = "\n".join(lines) + "\n\n🚀 <i>The most elite conversationalists of this group!</i>"
    await update.message.reply_text(border_text("𝐓𝐇𝐈𝐒 𝐆𝐑𝐎𝐔𝐏'𝐒 𝐗𝐏 𝐄𝐋𝐈𝐓𝐄", content), parse_mode=ParseMode.HTML)

@safe_reply
@require_group
async def grpriches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    rows = await db.get_group_riches(chat_id, limit=10)
    if not rows:
        await update.message.reply_text(border_text("𝐆𝐑𝐎𝐔𝐏 𝐑𝐈𝐂𝐇𝐄𝐒", "❌ No group coin stats recorded yet."), parse_mode=ParseMode.HTML)
        return
    
    lines = []
    for i, row in enumerate(rows):
        name = row['username'] or "Unknown"
        coins = format_number(row['coins'])
        medal = MEDALS[i] if i < len(MEDALS) else f"{i+1}."
        lines.append(f"{medal} @{name} • {coins} 💰")
    
    content = "\n".join(lines) + "\n\n💸 <i>Use /shop to spend your wealth!</i>"
    await update.message.reply_text(border_text("𝐓𝐇𝐈𝐒 𝐆𝐑𝐎𝐔𝐏'𝐒 𝐂𝐎𝐈𝐍 𝐊𝐈𝐍𝐆𝐒", content), parse_mode=ParseMode.HTML)

@safe_reply
@require_group
@rate_limit_command("daily")
async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    username = update.effective_user.username or update.effective_user.first_name
    now = datetime.now(IST)
    
    user_data = await db.get_user_per_group(user_id, chat_id)
    if user_data and user_data.get('last_daily'):
        last = user_data['last_daily']
        if last.tzinfo is None:
            last = IST.localize(last)
        if (now - last) < timedelta(hours=DAILY_COOLDOWN_HOURS):
            remaining = timedelta(hours=DAILY_COOLDOWN_HOURS) - (now - last)
            hours, rem = divmod(int(remaining.total_seconds()), 3600)
            minutes = rem // 60
            content = (
                f"⏳ <b>Already Claimed!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"⏰ Next reward in: <b>{hours}h {minutes}m</b>\n"
                f"💎 Check back soon or try your luck with /scratch!"
            )
            await update.message.reply_text(border_text("𝐂𝐎𝐎𝐋𝐃𝐎𝐖𝐍 • 𝐃𝐀𝐈𝐋𝐘", content), parse_mode=ParseMode.HTML)
            return
    
    await db.update_user_global(user_id, username, coins_delta=DAILY_COINS)
    await db.update_user_per_group(user_id, chat_id, username, coins_delta=DAILY_COINS, last_daily=True)
    await db.add_guild_xp_for_user(user_id, GUILD_XP_DAILY)
    
    global_data = await db.get_user_global(user_id)
    new_balance = global_data['total_coins'] if global_data else DAILY_COINS
    
    content = (
        f"✨ +{format_number(DAILY_COINS)} coins credited to your vault!\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>Total Balance:</b> {format_number(new_balance)} 💰\n"
        f"📅 Next claim available in: {DAILY_COOLDOWN_HOURS}h\n"
        f"💡 <i>Tip: Visit /shop to buy active protection!</i>"
    )
    await update.message.reply_text(border_text("𝐃𝐀𝐈𝐋𝐘 𝐑𝐄𝐖𝐀𝐑𝐃 • 𝐂𝐋𝐀𝐈𝐌𝐄𝐃", content), parse_mode=ParseMode.HTML)

@safe_reply
@require_group
@rate_limit_command("scratch")
async def scratch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    username = update.effective_user.username or update.effective_user.first_name
    now = datetime.now(IST)
    
    user_data = await db.get_user_per_group(user_id, chat_id)
    if user_data and user_data.get('last_scratch'):
        last = user_data['last_scratch']
        if last.tzinfo is None:
            last = IST.localize(last)
        if (now - last) < timedelta(hours=SCRATCH_COOLDOWN_HOURS):
            remaining = timedelta(hours=SCRATCH_COOLDOWN_HOURS) - (now - last)
            minutes = int(remaining.total_seconds()) // 60
            content = (
                f"⏳ <b>Card Already Scratched!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"⏰ Next card in: <b>{minutes}m</b>\n"
                f"💡 Try /daily if you haven't claimed it yet!"
            )
            await update.message.reply_text(border_text("𝐂𝐎𝐎𝐋𝐃𝐎𝐖𝐍 • 𝐒𝐂𝐑𝐀𝐓𝐂𝐇", content), parse_mode=ParseMode.HTML)
            return
    
    win = random.randint(1, 1000)
    await db.update_user_global(user_id, username, coins_delta=win)
    await db.update_user_per_group(user_id, chat_id, username, coins_delta=win, last_scratch=True)
    await db.add_guild_xp_for_user(user_id, GUILD_XP_SCRATCH)
    
    global_data = await db.get_user_global(user_id)
    new_balance = global_data['total_coins'] if global_data else win
    
    if win > 0:
        content = (
            f"🎉 <b>JACKPOT!</b> You won <b>{format_number(win)} coins</b>!\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 <b>Total Balance:</b> {format_number(new_balance)} 💰\n"
            f"✨ Keep up the lucky streak!"
        )
    else:
        content = (
            f"😬 <b>Scratch Card Empty!</b> No win this time.\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 <b>Total Balance:</b> {format_number(new_balance)} 💰\n"
            f"🔄 Grab a new card in {SCRATCH_COOLDOWN_HOURS}h!"
        )
    await update.message.reply_text(border_text("𝐒𝐂𝐑𝐀𝐓𝐂𝐇 𝐂𝐀𝐑𝐃 • 𝐋𝐔𝐂𝐊", content), parse_mode=ParseMode.HTML)

@safe_reply
@require_group
async def shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton(f"🛡️ Shield ({format_number(SHIELD_COST)} coins)", callback_data="buy_shield")],
        [InlineKeyboardButton("✨ Random XP Boost (100 coins)", callback_data="buy_xp")],
        [InlineKeyboardButton("🎟️ Lottery Ticket (50 coins)", callback_data="buy_lottery")],
        [InlineKeyboardButton(f"💪 Revive Self ({format_number(REVIVE_SELF_COST)} coins)", callback_data="buy_revive_self")],
        [InlineKeyboardButton(f"👥 Revive Other ({format_number(REVIVE_OTHER_COST)} coins)", callback_data="buy_revive_other")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    content = (
        "🛒 <b>Welcome to the Lumira Marketplace!</b>\n\n"
        "Select an item from the options below to purchase directly with your coin balance:\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🛡️ <b>Shield:</b> Protects against /rob, /kill & /roast for {SHIELD_DURATION_HOURS}h\n"
        f"🎟️ <b>Lottery Ticket:</b> Win instant jackpot coin prizes\n"
        f"💪 <b>Revive:</b> Restore your alive status after assassination"
    )
    await update.message.reply_text(border_text("𝐋𝐔𝐌𝐈𝐑𝐀 𝐒𝐇𝐎𝐏 • 𝐈𝐓𝐄𝐌𝐒", content), reply_markup=reply_markup, parse_mode=ParseMode.HTML)

@safe_reply
async def buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    username = query.from_user.username or query.from_user.first_name
    data = query.data
    
    user_per_group = await db.get_user_per_group(user_id, chat_id)
    if not user_per_group:
        await query.edit_message_text(border_text("𝐒𝐇𝐎𝐏 • 𝐄𝐑𝐑𝐎𝐑", "❌ You need to participate in chat first before making purchases!"), parse_mode=ParseMode.HTML)
        return
    
    coins = user_per_group['coins']
    
    if data == "buy_shield":
        if coins >= SHIELD_COST:
            expiry = datetime.now(IST) + timedelta(hours=SHIELD_DURATION_HOURS)
            await db.update_user_per_group(user_id, chat_id, username, coins_delta=-SHIELD_COST, shield_expiry=expiry)
            await db.update_user_global(user_id, username, coins_delta=-SHIELD_COST)
            content = (
                f"🛡️ <b>Shield Activated Successfully!</b>\n"
                f"Protected against PVP attacks for {SHIELD_DURATION_HOURS} hours.\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💰 <b>Remaining Balance:</b> {format_number(coins - SHIELD_COST)}"
            )
            await query.edit_message_text(border_text("𝐏𝐔𝐑𝐂𝐇𝐀𝐒𝐄 • 𝐒𝐔𝐂𝐂𝐄𝐒𝐒", content), parse_mode=ParseMode.HTML)
        else:
            content = (
                f"❌ <b>Insufficient Coins!</b>\n"
                f"Shield requires {format_number(SHIELD_COST)} coins. You currently have {format_number(coins)}.\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💡 Use /daily or /scratch to earn more coins!"
            )
            await query.edit_message_text(border_text("𝐏𝐔𝐑𝐂𝐇𝐀𝐒𝐄 • 𝐅𝐀𝐈𝐋𝐄𝐃", content), parse_mode=ParseMode.HTML)
    
    elif data == "buy_xp":
        price = 100
        if coins >= price:
            gain = random.randint(1, 50)
            await db.update_user_per_group(user_id, chat_id, username, coins_delta=-price, xp_delta=gain)
            await db.update_user_global(user_id, username, coins_delta=-price, xp_delta=gain)
            await db.add_guild_xp_for_user(user_id, 1)
            content = (
                f"✨ <b>XP Boost Purchased!</b>\n"
                f"You instantly gained +{gain} XP!\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💰 <b>Remaining Balance:</b> {format_number(coins - price)}"
            )
            await query.edit_message_text(border_text("𝐏𝐔𝐑𝐂𝐇𝐀𝐒𝐄 • 𝐒𝐔𝐂𝐂𝐄𝐒𝐒", content), parse_mode=ParseMode.HTML)
        else:
            content = f"❌ Need {price} coins! You have {format_number(coins)}."
            await query.edit_message_text(border_text("𝐏𝐔𝐑𝐂𝐇𝐀𝐒𝐄 • 𝐅𝐀𝐈𝐋𝐄𝐃", content), parse_mode=ParseMode.HTML)
    
    elif data == "buy_lottery":
        price = 50
        if coins >= price:
            win = random.choice([0, 100, 200, 500])
            await db.update_user_per_group(user_id, chat_id, username, coins_delta=-price + win)
            await db.update_user_global(user_id, username, coins_delta=-price + win)
            await db.add_guild_xp_for_user(user_id, 1)
            if win > 0:
                content = (
                    f"🎟️ <b>WINNER!</b> Your lottery ticket matched jackpot numbers!\n"
                    f"Prize awarded: <b>{format_number(win)} coins</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"💰 <b>Remaining Balance:</b> {format_number(coins - price + win)}"
                )
            else:
                content = (
                    f"🎟️ <b>Lottery Ticket Scratched!</b> No win this time.\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"💰 <b>Remaining Balance:</b> {format_number(coins - price)}"
                )
            await query.edit_message_text(border_text("𝐋𝐎𝐓𝐓𝐄𝐑𝐘 • 𝐑𝐄𝐒𝐔𝐋𝐓", content), parse_mode=ParseMode.HTML)
        else:
            content = f"❌ Need {price} coins! You have {format_number(coins)}."
            await query.edit_message_text(border_text("𝐏𝐔𝐑𝐂𝐇𝐀𝐒𝐄 • 𝐅𝐀𝐈𝐋𝐄𝐃", content), parse_mode=ParseMode.HTML)
    
    elif data == "buy_revive_self":
        if not user_per_group.get('is_dead'):
            await query.edit_message_text(border_text("𝐒𝐇𝐎𝐏 • 𝐍𝐎𝐓𝐈𝐂𝐄", "❌ You are already alive and well!"), parse_mode=ParseMode.HTML)
            return
        if coins >= REVIVE_SELF_COST:
            await db.update_user_per_group(user_id, chat_id, username, coins_delta=-REVIVE_SELF_COST, set_dead=False)
            await db.update_user_global(user_id, username, coins_delta=-REVIVE_SELF_COST)
            await db.add_guild_xp_for_user(user_id, GUILD_XP_REVIVE)
            content = (
                f"💪 <b>Revive Successful!</b>\n"
                f"You have returned from the grave and are ready for combat.\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💰 <b>Remaining Balance:</b> {format_number(coins - REVIVE_SELF_COST)}"
            )
            await query.edit_message_text(border_text("𝐑𝐄𝐕𝐈𝐕𝐄𝐃 • 𝐒𝐔𝐂𝐂𝐄𝐒𝐒", content), parse_mode=ParseMode.HTML)
        else:
            content = f"❌ Need {format_number(REVIVE_SELF_COST)} coins! You have {format_number(coins)}."
            await query.edit_message_text(border_text("𝐏𝐔𝐑𝐂𝐇𝐀𝐒𝐄 • 𝐅𝐀𝐈𝐋𝐄𝐃", content), parse_mode=ParseMode.HTML)
    
    elif data == "buy_revive_other":
        await query.edit_message_text(border_text("𝐒𝐇𝐎𝐏 • 𝐈𝐍𝐒𝐓𝐑𝐔𝐂𝐓𝐈𝐎𝐍", "📝 To revive someone else, type <code>/revive @username</code> in the group!"), parse_mode=ParseMode.HTML)

@safe_reply
@require_group
@rate_limit_command("roast")
async def roast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    attacker = update.effective_user
    
    target_user = None
    target_name = None
    
    if update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
        target_name = target_user.username or target_user.first_name
    elif context.args:
        target_name = context.args[0].lstrip('@')
        target_id = await db.find_user_by_username(chat_id, target_name)
        if target_id:
            try:
                member = await context.bot.get_chat_member(chat_id, target_id)
                target_user = member.user
            except Exception:
                pass
    else:
        await update.message.reply_text(border_text("𝐑𝐎𝐀𝐒𝐓 • 𝐔𝐒𝐀𝐆𝐄", "❌ Reply to someone or use <code>/roast @username</code> to unleash a savage roast!"), parse_mode=ParseMode.HTML)
        return
    
    if target_user and target_user.id == attacker.id:
        await update.message.reply_text(border_text("𝐑𝐎𝐀𝐒𝐓 • 𝐍𝐎𝐓𝐈𝐂𝐄", "🤡 Why roast yourself? Practice self-love!"), parse_mode=ParseMode.HTML)
        return
    
    if target_user and target_user.id == context.bot.id:
        roast_text = await ai_service.roast(context.bot.first_name, "roasting myself")
        content = f"🔥 {roast_text}\n━━━━━━━━━━━━━━━━━━━━━━\n💀 Self-aware AI mastery!"
        await update.message.reply_text(border_text("𝐑𝐎𝐀𝐒𝐓 • 𝐒𝐀𝐕𝐀𝐆𝐄", content), parse_mode=ParseMode.HTML)
        return
    
    if target_user:
        target_data = await db.get_user_per_group(target_user.id, chat_id)
        if target_data and target_data.get('is_verified_owner') == 1:
            roast_text = await ai_service.roast(attacker.first_name, "tried to roast group owner")
            content = f"🔥 @{attacker.username or attacker.first_name}, {roast_text}\n━━━━━━━━━━━━━━━━━━━━━━\n💀 Never mess with the Group Owner!"
            await update.message.reply_text(border_text("𝐑𝐎𝐀𝐒𝐓 • 𝐁𝐀𝐂𝐊𝐅𝐈𝐑𝐄", content), parse_mode=ParseMode.HTML)
            return
        
        if has_active_shield(target_data):
            content = f"🛡️ <b>@{target_user.username or target_user.first_name}</b> is protected by an active shield! Your roast bounced back."
            await update.message.reply_text(border_text("𝐒𝐇𝐈𝐄𝐋𝐃 • 𝐃𝐄𝐅𝐄𝐍𝐒𝐄", content), parse_mode=ParseMode.HTML)
            return
    
    roast_text = await ai_service.roast(target_name or "Unknown target")
    content = f"🔥 <b>@{target_name}</b>, {roast_text}\n━━━━━━━━━━━━━━━━━━━━━━\n💀 Destroyed!"
    await update.message.reply_text(border_text("𝐑𝐎𝐀𝐒𝐓 • 𝐒𝐀𝐕𝐀𝐆𝐄", content), parse_mode=ParseMode.HTML)

@safe_reply
@require_group
@rate_limit_command("kill")
async def kill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text(border_text("𝐊𝐈𝐋𝐋 • 𝐔𝐒𝐀𝐆𝐄", "❌ Reply to someone's message with <code>/kill</code> to assassinate them!"), parse_mode=ParseMode.HTML)
        return
    
    target = update.message.reply_to_message.from_user
    attacker = update.effective_user
    chat_id = update.effective_chat.id
    
    if target.id == context.bot.id:
        await update.message.reply_text(border_text("𝐊𝐈𝐋𝐋 • 𝐍𝐎𝐓𝐈𝐂𝐄", "😵 I am an immortal digital entity. You cannot harm me!"), parse_mode=ParseMode.HTML)
        return
    if target.id == attacker.id:
        await update.message.reply_text(border_text("𝐊𝐈𝐋𝐋 • 𝐍𝐎𝐓𝐈𝐂𝐄", "🤡 You cannot assassinate yourself."), parse_mode=ParseMode.HTML)
        return
    
    target_data = await db.get_user_per_group(target.id, chat_id)
    
    if target_data and target_data.get('is_verified_owner') == 1:
        await db.update_user_per_group(attacker.id, chat_id, attacker.username or attacker.first_name, set_dead=True)
        await update.message.reply_text(
            border_text("𝐀𝐒𝐒𝐀𝐒𝐒𝐈𝐍𝐀𝐓𝐈𝐎𝐍 • 𝐁𝐀𝐂𝐊𝐅𝐈𝐑𝐄", f"⚰️ <b>@{attacker.username or attacker.first_name}</b> attempted to kill the Group Owner and was instantly executed!"),
            parse_mode=ParseMode.HTML
        )
        return
    
    if has_active_shield(target_data):
        content = f"🛡️ <b>@{target.username or target.first_name}</b> is shielded! The assassination attempt was deflected."
        await update.message.reply_text(border_text("𝐒𝐇𝐈𝐄𝐋𝐃 • 𝐏𝐑𝐎𝐓𝐄𝐂𝐓𝐈𝐎𝐍", content), parse_mode=ParseMode.HTML)
        return
    
    if target_data and target_data.get('is_dead'):
        await update.message.reply_text(border_text("𝐊𝐈𝐋𝐋 • 𝐍𝐎𝐓𝐈𝐂𝐄", f"💀 <b>@{target.username or target.first_name}</b> is already dead!"), parse_mode=ParseMode.HTML)
        return
    
    await db.update_user_per_group(target.id, chat_id, target.username or target.first_name, set_dead=True)
    await db.add_guild_xp_for_user(attacker.id, GUILD_XP_KILL)
    content = (
        f"🔪 <b>@{attacker.username or attacker.first_name}</b> successfully assassinated <b>@{target.username or target.first_name}</b>!\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💀 Rest in peace. Use <code>/revive</code> or visit <code>/shop</code> to return!"
    )
    await update.message.reply_text(border_text("𝐀𝐒𝐒𝐀𝐒𝐒𝐈𝐍𝐀𝐓𝐈𝐎𝐍 • 𝐒𝐔𝐂𝐂𝐄𝐒𝐒", content), parse_mode=ParseMode.HTML)

@safe_reply
@require_group
@rate_limit_command("rob")
async def rob(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text(border_text("𝐑𝐎𝐁 • 𝐔𝐒𝐀𝐆𝐄", "❌ Reply to someone's message with <code>/rob &lt;amount&gt;</code> to steal their coins!"), parse_mode=ParseMode.HTML)
        return
    if not context.args:
        await update.message.reply_text(border_text("𝐑𝐎𝐁 • 𝐔𝐒𝐀𝐆𝐄", "❌ Please specify an amount: <code>/rob 500</code> (replying to a user)"), parse_mode=ParseMode.HTML)
        return
    
    try:
        amount = int(context.args[0])
    except ValueError:
        await update.message.reply_text(border_text("𝐑𝐎𝐁 • 𝐄𝐑𝐑𝐎𝐑", "❌ Amount must be a valid number."), parse_mode=ParseMode.HTML)
        return
    
    if amount <= 0:
        await update.message.reply_text(border_text("𝐑𝐎𝐁 • 𝐄𝐑𝐑𝐎𝐑", "❌ Amount must be positive."), parse_mode=ParseMode.HTML)
        return
    if amount > 10000:
        await update.message.reply_text(border_text("𝐑𝐎𝐁 • 𝐄𝐑𝐑𝐎𝐑", "❌ Maximum heist limit is 10,000 coins at a time."), parse_mode=ParseMode.HTML)
        return
    
    target = update.message.reply_to_message.from_user
    thief = update.effective_user
    chat_id = update.effective_chat.id
    
    if target.id == thief.id:
        await update.message.reply_text(border_text("𝐑𝐎𝐁 • 𝐍𝐎𝐓𝐈𝐂𝐄", "🤡 You cannot rob yourself."), parse_mode=ParseMode.HTML)
        return
    if target.id == context.bot.id:
        await update.message.reply_text(border_text("𝐑𝐎𝐁 • 𝐍𝐎𝐓𝐈𝐂𝐄", "😤 I have no physical coins to steal!"), parse_mode=ParseMode.HTML)
        return
    
    target_data = await db.get_user_per_group(target.id, chat_id)
    thief_data = await db.get_user_per_group(thief.id, chat_id)
    
    if not thief_data:
        await update.message.reply_text(border_text("𝐑𝐎𝐁 • 𝐄𝐑𝐑𝐎𝐑", "❌ You must participate in chat first to earn your own balance!"), parse_mode=ParseMode.HTML)
        return
    
    if target_data and target_data.get('is_verified_owner') == 1:
        fine = min(amount * 2, thief_data['coins'])
        await db.update_user_per_group(thief.id, chat_id, thief.username or thief.first_name, coins_delta=-fine)
        await db.update_user_global(thief.id, thief.username or thief.first_name, coins_delta=-fine)
        content = (
            f"👑 <b>Group Owner Protection Triggered!</b>\n"
            f"You attempted to rob the Group Owner and were fined <b>{format_number(fine)} coins</b>.\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 <b>Your New Balance:</b> {format_number(max(0, thief_data['coins'] - fine))}"
        )
        await update.message.reply_text(border_text("𝐇𝐄𝐈𝐒𝐓 • 𝐁𝐀𝐂𝐊𝐅𝐈𝐑𝐄", content), parse_mode=ParseMode.HTML)
        return
    
    if has_active_shield(target_data):
        content = f"🛡️ <b>@{target.username or target.first_name}</b> is protected by a shield! Your heist failed."
        await update.message.reply_text(border_text("𝐒𝐇𝐈𝐄𝐋𝐃 • 𝐃𝐄𝐅𝐄𝐍𝐒𝐄", content), parse_mode=ParseMode.HTML)
        return
    
    if target_data and target_data.get('is_dead'):
        await update.message.reply_text(border_text("𝐑𝐎𝐁 • 𝐍𝐎𝐓𝐈𝐂𝐄", f"💀 <b>@{target.username or target.first_name}</b> is dead. You cannot rob a ghost."), parse_mode=ParseMode.HTML)
        return
    
    if not target_data or target_data['coins'] < amount:
        await update.message.reply_text(border_text("𝐑𝐎𝐁 • 𝐅𝐀𝐈𝐋𝐄𝐃", f"❌ <b>@{target.username or target.first_name}</b> does not have {format_number(amount)} coins."), parse_mode=ParseMode.HTML)
        return
    
    success, msg = await db.transfer_coins(
        target.id, thief.id, chat_id, amount,
        target.username or target.first_name,
        thief.username or thief.first_name
    )
    
    if success:
        await db.add_guild_xp_for_user(thief.id, GUILD_XP_ROB)
        thief_new = thief_data['coins'] + amount
        content = (
            f"💰 <b>Heist Successful!</b>\n"
            f"You robbed <b>{format_number(amount)} coins</b> from @{target.username or target.first_name}!\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 <b>Your Balance:</b> {format_number(thief_new)}"
        )
        await update.message.reply_text(border_text("𝐇𝐄𝐈𝐒𝐓 • 𝐒𝐔𝐂𝐂𝐄𝐒𝐒", content), parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(border_text("𝐑𝐎𝐁 • 𝐅𝐀𝐈𝐋𝐄𝐃", f"❌ {msg}"), parse_mode=ParseMode.HTML)

@safe_reply
@require_group
async def revive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    username = update.effective_user.username or update.effective_user.first_name
    
    if context.args:
        target_name = context.args[0].lstrip('@')
        target_id = await db.find_user_by_username(chat_id, target_name)
        
        if not target_id:
            await update.message.reply_text(border_text("𝐑𝐄𝐕𝐈𝐕𝐄 • 𝐄𝐑𝐑𝐎𝐑", f"❌ User @{target_name} not found in this group."), parse_mode=ParseMode.HTML)
            return
        
        target_data = await db.get_user_per_group(target_id, chat_id)
        if not target_data or not target_data.get('is_dead'):
            await update.message.reply_text(border_text("𝐑𝐄𝐕𝐈𝐕𝐄 • 𝐍𝐎𝐓𝐈𝐂𝐄", f"❌ @{target_name} is already alive and well."), parse_mode=ParseMode.HTML)
            return
        
        self_data = await db.get_user_per_group(user_id, chat_id)
        if not self_data or self_data['coins'] < REVIVE_OTHER_COST:
            await update.message.reply_text(border_text("𝐑𝐄𝐕𝐈𝐕𝐄 • 𝐈𝐍𝐒𝐔𝐅𝐅𝐈𝐂𝐈𝐄𝐍𝐓", f"❌ You need {format_number(REVIVE_OTHER_COST)} coins to revive another member."), parse_mode=ParseMode.HTML)
            return
        
        await db.update_user_per_group(target_id, chat_id, target_name, set_dead=False)
        await db.update_user_per_group(user_id, chat_id, username, coins_delta=-REVIVE_OTHER_COST)
        await db.update_user_global(user_id, username, coins_delta=-REVIVE_OTHER_COST)
        await db.add_guild_xp_for_user(user_id, GUILD_XP_REVIVE)
        
        content = (
            f"💪 <b>Heroic Resurrection!</b>\n"
            f"<b>@{username}</b> revived <b>@{target_name}</b> from the dead!\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 <b>Cost:</b> {format_number(REVIVE_OTHER_COST)} coins"
        )
        await update.message.reply_text(border_text("𝐑𝐄𝐒𝐔𝐑𝐑𝐄𝐂𝐓𝐈𝐎𝐍 • 𝐒𝐔𝐂𝐂𝐄𝐒𝐒", content), parse_mode=ParseMode.HTML)
    else:
        user_data = await db.get_user_per_group(user_id, chat_id)
        if not user_data:
            await update.message.reply_text(border_text("𝐑𝐄𝐕𝐈𝐕𝐄 • 𝐄𝐑𝐑𝐎𝐑", "❌ You must chat first to earn coins."), parse_mode=ParseMode.HTML)
            return
        if not user_data.get('is_dead'):
            await update.message.reply_text(border_text("𝐑𝐄𝐕𝐈𝐕𝐄 • 𝐍𝐎𝐓𝐈𝐂𝐄", "❌ You are already alive!"), parse_mode=ParseMode.HTML)
            return
        if user_data['coins'] < REVIVE_SELF_COST:
            await update.message.reply_text(border_text("𝐑𝐄𝐕𝐈𝐕𝐄 • 𝐈𝐍𝐒𝐔𝐅𝐅𝐈𝐂𝐈𝐄𝐍𝐓", f"❌ You need {format_number(REVIVE_SELF_COST)} coins to revive yourself."), parse_mode=ParseMode.HTML)
            return
        
        await db.update_user_per_group(user_id, chat_id, username, coins_delta=-REVIVE_SELF_COST, set_dead=False)
        await db.update_user_global(user_id, username, coins_delta=-REVIVE_SELF_COST)
        await db.add_guild_xp_for_user(user_id, GUILD_XP_REVIVE)
        
        content = (
            f"💪 <b>Self Resurrection Complete!</b>\n"
            f"You have revived yourself and returned to action.\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 <b>Remaining Balance:</b> {format_number(user_data['coins'] - REVIVE_SELF_COST)}"
        )
        await update.message.reply_text(border_text("𝐑𝐄𝐒𝐔𝐑𝐑𝐄𝐂𝐓𝐈𝐎𝐍 • 𝐒𝐔𝐂𝐂𝐄𝐒𝐒", content), parse_mode=ParseMode.HTML)

@safe_reply
@require_group
async def gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text(border_text("𝐆𝐈𝐅𝐓 • 𝐔𝐒𝐀𝐆𝐄", "❌ Reply to a user's message with <code>/gift</code> to send them a gift!"), parse_mode=ParseMode.HTML)
        return
    
    target = update.message.reply_to_message.from_user
    sender = update.effective_user
    chat_id = update.effective_chat.id
    
    if target.id == sender.id:
        await update.message.reply_text(border_text("𝐆𝐈𝐅𝐓 • 𝐍𝐎𝐓𝐈𝐂𝐄", "❌ You cannot gift yourself! Spread the love to others."), parse_mode=ParseMode.HTML)
        return
    
    success = await pending_manager.set(chat_id, sender.id, {
        "action": "gift",
        "target_id": target.id,
        "target_name": target.username or target.first_name
    })
    if not success:
        await update.message.reply_text(border_text("𝐆𝐈𝐅𝐓 • 𝐄𝐑𝐑𝐎𝐑", "❌ Too many pending actions right now. Try again later."), parse_mode=ParseMode.HTML)
        return
    
    keyboard = [
        [InlineKeyboardButton(f"{info['emoji']} {gtype.capitalize()} ({info['price']} coins)", callback_data=f"gift_{gtype}")]
        for gtype, info in GIFT_TYPES.items()
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        border_text("𝐆𝐈𝐅𝐓 𝐒𝐄𝐋𝐄𝐂𝐓𝐈𝐎𝐍", f"🎁 Select a gift for <b>@{target.username or target.first_name}</b>:"),
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

@safe_reply
async def gift_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    data = query.data
    
    if not data.startswith("gift_"):
        return
    
    gift_type = data[5:]
    if gift_type not in GIFT_TYPES:
        return
    
    pending = await pending_manager.get(chat_id, user_id)
    if not pending or pending.get("action") != "gift":
        await query.edit_message_text(border_text("𝐆𝐈𝐅𝐓 • 𝐄𝐗𝐏𝐈𝐑𝐄𝐃", "❌ No pending gift action. Use <code>/gift</code> again."), parse_mode=ParseMode.HTML)
        return
    
    target_id = pending["target_id"]
    target_name = pending["target_name"]
    price = GIFT_TYPES[gift_type]["price"]
    emoji = GIFT_TYPES[gift_type]["emoji"]
    
    sender_data = await db.get_user_per_group(user_id, chat_id)
    if not sender_data or sender_data['coins'] < price:
        await query.edit_message_text(border_text("𝐆𝐈𝐅𝐓 • 𝐈𝐍𝐒𝐔𝐅𝐅𝐈𝐂𝐈𝐄𝐍𝐓", f"❌ You need {price} coins to send this gift. Balance: {format_number(sender_data['coins'] if sender_data else 0)}."), parse_mode=ParseMode.HTML)
        await pending_manager.delete(chat_id, user_id)
        return
    
    await db.update_user_per_group(user_id, chat_id, query.from_user.username or query.from_user.first_name, coins_delta=-price)
    await db.update_user_global(user_id, query.from_user.username or query.from_user.first_name, coins_delta=-price)
    await db.add_gift(user_id, target_id, chat_id, gift_type, price)
    await db.add_guild_xp_for_user(user_id, GUILD_XP_GIFT)
    
    content = (
        f"🎁 <b>Gift Delivered!</b>\n"
        f"Sent {emoji} <b>{gift_type.capitalize()}</b> to @{target_name}!\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>Spent:</b> {price} coins"
    )
    await query.edit_message_text(border_text("𝐆𝐈𝐅𝐓 • 𝐒𝐔𝐂𝐂𝐄𝐒𝐒", content), parse_mode=ParseMode.HTML)
    try:
        await context.bot.send_message(chat_id, f"🎁 @{target_name}, you received a special gift from @{query.from_user.username or query.from_user.first_name}! Check with /mygifts")
    except Exception:
        pass
    await pending_manager.delete(chat_id, user_id)

@safe_reply
async def mygifts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    gifts = await db.get_gifts(user_id, limit=10)
    
    if not gifts:
        await update.message.reply_text(border_text("𝐘𝐎𝐔𝐑 𝐆𝐈𝐅𝐓𝐒", "❌ You have not received any gifts yet."), parse_mode=ParseMode.HTML)
        return
    
    lines = []
    for g in gifts:
        from_data = await db.get_user_global(g['from_user'])
        from_un = from_data['username'] if from_data else str(g['from_user'])
        emoji = GIFT_TYPES.get(g['gift_type'], {}).get('emoji', '🎁')
        date_str = g['created_at'].strftime('%Y-%m-%d') if g['created_at'] else 'Unknown'
        lines.append(f"{emoji} From @{from_un} • <b>{g['gift_type'].capitalize()}</b> ({format_number(g['amount'])} 💰) • <i>{date_str}</i>")
    
    content = "\n".join(lines)
    await update.message.reply_text(border_text("𝐘𝐎𝐔𝐑 𝐑𝐄𝐂𝐄𝐈𝐕𝐄𝐃 𝐆𝐈𝐅𝐓𝐒", content), parse_mode=ParseMode.HTML)

@safe_reply
@rate_limit_command("ai")
async def ai_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(context.args)
    if not prompt:
        await update.message.reply_text(border_text("𝐀𝐈 • 𝐔𝐒𝐀𝐆𝐄", "❌ Usage: <code>/ai &lt;question&gt;</code> to consult the Lumira AI assistant."), parse_mode=ParseMode.HTML)
        return
    
    await update.message.reply_chat_action("typing")
    response = await ai_service.ask(prompt)
    await update.message.reply_text(border_text("𝐋𝐔𝐌𝐈𝐑𝐀 • 𝐀𝐈 𝐀𝐒𝐒𝐈𝐒𝐓𝐀𝐍𝐓", response), parse_mode=ParseMode.HTML)

# ==================== GUILD COMMANDS ====================

@safe_reply
async def newguild(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner-only: Create a new guild (max 10). Optionally deduct coins if cost set."""
    if update.effective_user.id != GLOBAL_OWNER_ID:
        await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃𝐒 • 𝐀𝐂𝐂𝐄𝐒𝐒", "❌ Only the Global Master can create official guilds."), parse_mode=ParseMode.HTML)
        return
    if not context.args:
        await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃𝐒 • 𝐔𝐒𝐀𝐆𝐄", "❌ Usage: <code>/newguild &lt;name&gt;</code>"), parse_mode=ParseMode.HTML)
        return
    name = " ".join(context.args).strip()
    if len(name) > 30:
        await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃𝐒 • 𝐄𝐑𝐑𝐎𝐑", "❌ Guild name too long (maximum 30 characters)."), parse_mode=ParseMode.HTML)
        return
    if not re.match(r'^[a-zA-Z0-9 ]+$', name):
        await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃𝐒 • 𝐄𝐑𝐑𝐎𝐑", "❌ Guild name can only contain alphanumeric characters and spaces."), parse_mode=ParseMode.HTML)
        return
    try:
        if GUILD_CREATION_COST > 0:
            user_data = await db.get_user_global(GLOBAL_OWNER_ID)
            if not user_data or user_data['total_coins'] < GUILD_CREATION_COST:
                await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃𝐒 • 𝐂𝐎𝐒𝐓", f"❌ You need {format_number(GUILD_CREATION_COST)} coins to create a guild."), parse_mode=ParseMode.HTML)
                return
            await db.update_user_global(GLOBAL_OWNER_ID, update.effective_user.username or "Owner", coins_delta=-GUILD_CREATION_COST)
        
        guild_id = await db.create_guild(name, creator_id=GLOBAL_OWNER_ID)
        content = (
            f"✅ <b>Guild Created Successfully!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🏰 <b>Guild Name:</b> {name}\n"
            f"🆔 <b>Guild ID:</b> {guild_id}\n"
            f"👑 <b>Created By:</b> @{update.effective_user.username or 'Owner'}"
        )
        await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃 𝐂𝐑𝐄𝐀𝐓𝐄𝐃", content), parse_mode=ParseMode.HTML)
    except ValueError as e:
        await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃𝐒 • 𝐄𝐑𝐑𝐎𝐑", f"❌ {e}"), parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.exception("Error creating guild")
        await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃𝐒 • 𝐄𝐑𝐑𝐎𝐑", "❌ An error occurred while creating the guild."), parse_mode=ParseMode.HTML)

@safe_reply
async def delguild(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner-only: Delete a guild by name."""
    if update.effective_user.id != GLOBAL_OWNER_ID:
        await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃𝐒 • 𝐀𝐂𝐂𝐄𝐒𝐒", "❌ Only the Global Master can delete guilds."), parse_mode=ParseMode.HTML)
        return
    if not context.args:
        await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃𝐒 • 𝐔𝐒𝐀𝐆𝐄", "❌ Usage: <code>/delguild &lt;name&gt;</code>"), parse_mode=ParseMode.HTML)
        return
    name = " ".join(context.args).strip()
    guild = await db.get_guild_by_name(name)
    if not guild:
        await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃𝐒 • 𝐄𝐑𝐑𝐎𝐑", "❌ Guild not found."), parse_mode=ParseMode.HTML)
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ YES, Delete Guild", callback_data=f"delguild_confirm_{guild['guild_id']}"),
         InlineKeyboardButton("❌ Cancel", callback_data="delguild_cancel")]
    ])
    await update.message.reply_text(
        border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐂𝐎𝐍𝐅𝐈𝐑𝐌 𝐃𝐄𝐋𝐄𝐓𝐈𝐎𝐍", f"⚠️ Are you sure you want to permanently delete guild <b>{name}</b>? All member contribution records will be cleared."),
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )

async def delguild_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("delguild_confirm_"):
        guild_id = int(data.split("_")[2])
        await db.delete_guild(guild_id, admin_id=query.from_user.id)
        await query.edit_message_text(border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐃𝐄𝐋𝐄𝐓𝐄𝐃", "✅ Guild has been permanently deleted."), parse_mode=ParseMode.HTML)
    elif data == "delguild_cancel":
        await query.edit_message_text(border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐂𝐀𝐍𝐂𝐄𝐋𝐋𝐄𝐃", "❌ Deletion action cancelled."), parse_mode=ParseMode.HTML)

@safe_reply
async def guilds_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner-only: List all guilds."""
    if update.effective_user.id != GLOBAL_OWNER_ID:
        await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃𝐒 • 𝐀𝐂𝐂𝐄𝐒𝐒", "❌ Only the Global Master can view the full guild registry."), parse_mode=ParseMode.HTML)
        return
    guilds = await db.list_guilds()
    if not guilds:
        await update.message.reply_text(border_text("𝐀𝐋𝐋 𝐆𝐔𝐈𝐋𝐃𝐒", "No guilds have been created yet."), parse_mode=ParseMode.HTML)
        return
    lines = [f"📋 <b>Total Registered Guilds: {len(guilds)}</b>", "━━━━━━━━━━━━━━━━━━━━━━"]
    for g in guilds:
        lines.append(f"🏰 <b>{g['name']}</b> (ID: {g['guild_id']})")
        lines.append(f"   👥 Members: {g['member_count']} | 📊 Total XP: {format_number(g['total_xp'])}")
    content = "\n".join(lines)
    await update.message.reply_text(border_text("𝐀𝐋𝐋 𝐑𝐄𝐆𝐈𝐒𝐓𝐄𝐑𝐄𝐃 𝐆𝐔𝐈𝐋𝐃𝐒", content), parse_mode=ParseMode.HTML)

@safe_reply
async def join_guild(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User command: Join a guild by name."""
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    if not context.args:
        await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐔𝐒𝐀𝐆𝐄", "❌ Usage: <code>/join_guild &lt;guild_name&gt;</code>"), parse_mode=ParseMode.HTML)
        return
    name = " ".join(context.args).strip()
    guild = await db.get_guild_by_name(name)
    if not guild:
        await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐄𝐑𝐑𝐎𝐑", f"❌ Guild <b>'{name}'</b> not found. Check <code>/guild_leaderboard</code> for active guilds!"), parse_mode=ParseMode.HTML)
        return
    success, msg = await db.add_user_to_guild(user_id, guild['guild_id'], username)
    if success:
        content = (
            f"✅ <b>You joined {guild['name']}!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Every message you send now generates XP for your new guild!"
        )
        await update.message.reply_text(border_text("𝐉𝐎𝐈𝐍𝐄𝐃 𝐆𝐔𝐈𝐋𝐃 • 𝐒𝐔𝐂𝐂𝐄𝐒𝐒", content), parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐉𝐎𝐈𝐍 𝐅𝐀𝐈𝐋𝐄𝐃", f"❌ {msg}"), parse_mode=ParseMode.HTML)

@safe_reply
async def leave_guild(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User command: Leave current guild."""
    user_id = update.effective_user.id
    guild = await db.get_user_guild(user_id)
    if not guild:
        await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐍𝐎𝐓𝐈𝐂𝐄", "❌ You are not in any guild."), parse_mode=ParseMode.HTML)
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ YES, Leave Guild", callback_data=f"leave_confirm_{guild['guild_id']}"),
         InlineKeyboardButton("❌ Cancel", callback_data="leave_cancel")]
    ])
    await update.message.reply_text(
        border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐂𝐎𝐍𝐅𝐈𝐑𝐌 𝐋𝐄𝐀𝐕𝐄", f"⚠️ Are you sure you want to leave guild <b>{guild['name']}</b>? You will enter a 24h cooldown before joining another."),
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )

async def leave_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    if data.startswith("leave_confirm_"):
        guild_id = int(data.split("_")[2])
        guild = await db.get_user_guild(user_id)
        if not guild or guild['guild_id'] != guild_id:
            await query.edit_message_text(border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐄𝐑𝐑𝐎𝐑", "❌ You are no longer in that guild."), parse_mode=ParseMode.HTML)
            return
        success, msg = await db.remove_user_from_guild(user_id)
        if success:
            await query.edit_message_text(border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐋𝐄𝐅𝐓", "✅ You have left the guild successfully."), parse_mode=ParseMode.HTML)
        else:
            await query.edit_message_text(border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐄𝐑𝐑𝐎𝐑", f"❌ {msg}"), parse_mode=ParseMode.HTML)
    elif data == "leave_cancel":
        await query.edit_message_text(border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐂𝐀𝐍𝐂𝐄𝐋𝐋𝐄𝐃", "❌ Action cancelled. You remain in your guild."), parse_mode=ParseMode.HTML)

@safe_reply
async def myguild(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User command: Show current guild info."""
    user_id = update.effective_user.id
    guild = await db.get_user_guild(user_id)
    if not guild:
        await update.message.reply_text(border_text("𝐘𝐎𝐔𝐑 𝐆𝐔𝐈𝐋𝐃", "❌ You are not currently enlisted in any guild. Use <code>/join_guild &lt;name&gt;</code> to enlist!"), parse_mode=ParseMode.HTML)
        return
    members = await db.get_guild_members(guild['guild_id'])
    user_contrib = next((m['contribution_xp'] for m in members if m['user_id'] == user_id), 0)
    level = db.calculate_guild_level(guild['total_xp'])
    content = (
        f"🏰 <b>{guild['name']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>Guild Level:</b> {level}\n"
        f"✨ <b>Total Guild XP:</b> {format_number(guild['total_xp'])}\n"
        f"👥 <b>Active Members:</b> {len(members)} / {MAX_GUILD_MEMBERS}\n"
        f"📈 <b>Your Contribution:</b> {format_number(user_contrib)} XP\n"
        f"📅 <b>Enlisted On:</b> {members[0]['joined_at'].strftime('%Y-%m-%d') if members and members[0].get('joined_at') else 'N/A'}"
    )
    await update.message.reply_text(border_text("𝐘𝐎𝐔𝐑 𝐆𝐔𝐈𝐋𝐃 𝐒𝐓𝐀𝐓𝐔𝐒", content), parse_mode=ParseMode.HTML)

@safe_reply
async def guild_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Global guild leaderboard."""
    guilds = await db.get_guild_leaderboard(limit=10)
    if not guilds:
        await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃 𝐋𝐄𝐀𝐃𝐄𝐑𝐁𝐎𝐀𝐑𝐃", "❌ No guilds registered yet."), parse_mode=ParseMode.HTML)
        return
    lines = []
    for i, g in enumerate(guilds):
        medal = MEDALS[i] if i < len(MEDALS) else f"{i+1}."
        lines.append(f"{medal} <b>{g['name']}</b>")
        lines.append(f"   📊 Lvl {g['level']} • {format_number(g['total_xp'])} XP • 👥 {g['members']} members")
    content = "\n".join(lines)
    await update.message.reply_text(border_text("𝐓𝐎𝐏 𝐆𝐔𝐈𝐋𝐃𝐒 𝐎𝐅 𝐋𝐔𝐌𝐈𝐑𝐀", content), parse_mode=ParseMode.HTML)

@safe_reply
async def guild_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show members of your guild."""
    user_id = update.effective_user.id
    guild = await db.get_user_guild(user_id)
    if not guild:
        await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃 𝐌𝐄𝐌𝐁𝐄𝐑𝐒", "❌ You are not in any guild."), parse_mode=ParseMode.HTML)
        return
    members = await db.get_guild_members(guild['guild_id'])
    if not members:
        await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃 𝐌𝐄𝐌𝐁𝐄𝐑𝐒", "❌ No members found."), parse_mode=ParseMode.HTML)
        return
    lines = [f"🏰 <b>{guild['name']} Roster ({len(members)} members):</b>", "━━━━━━━━━━━━━━━━━━━━━━"]
    for m in members[:30]:  # Cap display to 30 members to keep clean UI
        lines.append(f"👤 @{m['username']} — <b>{format_number(m['contribution_xp'])} XP</b>")
    if len(members) > 30:
        lines.append(f"\n<i>...and {len(members) - 30} more members.</i>")
    content = "\n".join(lines)
    await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃 𝐌𝐄𝐌𝐁𝐄𝐑 𝐑𝐎𝐒𝐓𝐄𝐑", content), parse_mode=ParseMode.HTML)

@safe_reply
async def guild_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View any guild's details by name."""
    if not context.args:
        await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐈𝐍𝐅𝐎", "❌ Usage: <code>/guild_info &lt;guild_name&gt;</code>"), parse_mode=ParseMode.HTML)
        return
    name = " ".join(context.args).strip()
    guild = await db.get_guild_by_name(name)
    if not guild:
        await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐈𝐍𝐅𝐎", f"❌ Guild <b>'{name}'</b> not found."), parse_mode=ParseMode.HTML)
        return
    members = await db.get_guild_members(guild['guild_id'])
    level = db.calculate_guild_level(guild['total_xp'])
    content = (
        f"🏰 <b>{guild['name']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>Guild Level:</b> {level}\n"
        f"✨ <b>Total XP:</b> {format_number(guild['total_xp'])}\n"
        f"👥 <b>Total Members:</b> {len(members)} / {MAX_GUILD_MEMBERS}\n"
        f"📅 <b>Created On:</b> {guild['created_at'].strftime('%Y-%m-%d') if guild.get('created_at') else 'N/A'}"
    )
    await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐈𝐍𝐒𝐏𝐄𝐂𝐓𝐈𝐎𝐍", content), parse_mode=ParseMode.HTML)

@safe_reply
async def transfer_guild(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner-only: Transfer guild ownership or leadership."""
    if update.effective_user.id != GLOBAL_OWNER_ID:
        await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐓𝐑𝐀𝐍𝐒𝐅𝐄𝐑", "❌ Only the Global Master can transfer guilds."), parse_mode=ParseMode.HTML)
        return
    if len(context.args) < 2:
        await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐓𝐑𝐀𝐍𝐒𝐅𝐄𝐑", "❌ Usage: <code>/transfer_guild &lt;old_name&gt; &lt;new_owner_username&gt;</code>"), parse_mode=ParseMode.HTML)
        return
    old_name = context.args[0]
    new_owner_username = context.args[1].lstrip('@')
    guild = await db.get_guild_by_name(old_name)
    if not guild:
        await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐓𝐑𝐀𝐍𝐒𝐅𝐄𝐑", f"❌ Guild <b>'{old_name}'</b> not found."), parse_mode=ParseMode.HTML)
        return
    chat_id = update.effective_chat.id if update.effective_chat else 0
    new_user_id = await db.find_user_by_username(chat_id, new_owner_username)
    if not new_user_id:
        await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐓𝐑𝐀𝐍𝐒𝐅𝐄𝐑", f"❌ User @{new_owner_username} not found in database records."), parse_mode=ParseMode.HTML)
        return
    try:
        async with db.transaction() as conn:
            await conn.execute("UPDATE guilds SET owner_id = $1 WHERE guild_id = $2", new_user_id, guild['guild_id'])
            existing = await conn.fetchval("SELECT 1 FROM guild_members WHERE user_id = $1", new_user_id)
            if not existing:
                await conn.execute("INSERT INTO guild_members (user_id, guild_id, contribution_xp) VALUES ($1, $2, 0)", new_user_id, guild['guild_id'])
                await conn.execute("UPDATE guilds SET member_count = member_count + 1 WHERE guild_id = $1", guild['guild_id'])
        await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐓𝐑𝐀𝐍𝐒𝐅𝐄𝐑", f"✅ Guild <b>'{guild['name']}'</b> ownership transferred to @{new_owner_username}!"), parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.exception("Error transferring guild")
        await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐓𝐑𝐀𝐍𝐒𝐅𝐄𝐑", "❌ Error occurred while transferring guild."), parse_mode=ParseMode.HTML)

@safe_reply
async def rename_guild(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner-only: Rename a guild."""
    if update.effective_user.id != GLOBAL_OWNER_ID:
        await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐑𝐄𝐍𝐀𝐌𝐄", "❌ Only the Global Master can rename guilds."), parse_mode=ParseMode.HTML)
        return
    if len(context.args) < 2:
        await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐑𝐄𝐍𝐀𝐌𝐄", "❌ Usage: <code>/rename_guild &lt;old_name&gt; &lt;new_name&gt;</code>"), parse_mode=ParseMode.HTML)
        return
    old_name = context.args[0]
    new_name = " ".join(context.args[1:]).strip()
    if len(new_name) > 30:
        await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐑𝐄𝐍𝐀𝐌𝐄", "❌ New name too long (max 30 chars)."), parse_mode=ParseMode.HTML)
        return
    if not re.match(r'^[a-zA-Z0-9 ]+$', new_name):
        await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐑𝐄𝐍𝐀𝐌𝐄", "❌ Guild name can only contain alphanumeric characters and spaces."), parse_mode=ParseMode.HTML)
        return
    guild = await db.get_guild_by_name(old_name)
    if not guild:
        await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐑𝐄𝐍𝐀𝐌𝐄", "❌ Guild not found."), parse_mode=ParseMode.HTML)
        return
    try:
        async with db.transaction() as conn:
            await conn.execute("UPDATE guilds SET name = $1 WHERE guild_id = $2", new_name, guild['guild_id'])
        await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐑𝐄𝐍𝐀𝐌𝐄", f"✅ Guild renamed to <b>'{new_name}'</b>."), parse_mode=ParseMode.HTML)
        logger.info(f"Guild {guild['guild_id']} renamed from '{old_name}' to '{new_name}' by owner {GLOBAL_OWNER_ID}")
    except asyncpg.UniqueViolationError:
        await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐑𝐄𝐍𝐀𝐌𝐄", "❌ A guild with that name already exists."), parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.exception("Error renaming guild")
        await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐑𝐄𝐍𝐀𝐌𝐄", "❌ An error occurred while renaming the guild."), parse_mode=ParseMode.HTML)

@safe_reply
async def guild_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner-only: Detailed guild statistics."""
    if update.effective_user.id != GLOBAL_OWNER_ID:
        await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐒𝐓𝐀𝐓𝐒", "❌ Only the Global Master can view guild deep stats."), parse_mode=ParseMode.HTML)
        return
    if not context.args:
        await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐒𝐓𝐀𝐓𝐒", "❌ Usage: <code>/guild_stats &lt;guild_name&gt;</code>"), parse_mode=ParseMode.HTML)
        return
    name = " ".join(context.args).strip()
    guild = await db.get_guild_by_name(name)
    if not guild:
        await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐒𝐓𝐀𝐓𝐒", "❌ Guild not found."), parse_mode=ParseMode.HTML)
        return
    members = await db.get_guild_members(guild['guild_id'])
    level = db.calculate_guild_level(guild['total_xp'])
    avg_xp = format_number(guild['total_xp'] // max(1, len(members)))
    content = (
        f"🏰 <b>{guild['name']} Deep Statistics</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>Level:</b> {level}\n"
        f"✨ <b>Total XP:</b> {format_number(guild['total_xp'])}\n"
        f"👥 <b>Members Count:</b> {len(members)}\n"
        f"📅 <b>Created On:</b> {guild['created_at'].strftime('%Y-%m-%d %H:%M') if guild.get('created_at') else 'N/A'}\n"
        f"📈 <b>Avg Member Contribution:</b> {avg_xp} XP"
    )
    await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃 𝐒𝐓𝐀𝐓𝐈𝐒𝐓𝐈𝐂𝐒", content), parse_mode=ParseMode.HTML)

# ==================== BROADCAST SYSTEM ====================

@safe_reply
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner-only: Start broadcast process (only in private)."""
    if update.effective_user.id != GLOBAL_OWNER_ID:
        await update.message.reply_text(border_text("𝐁𝐑𝐎𝐀𝐃𝐂𝐀𝐒𝐓", "❌ Only the Global Master can broadcast."), parse_mode=ParseMode.HTML)
        return
    if update.effective_chat.type != ChatType.PRIVATE:
        await update.message.reply_text(border_text("𝐁𝐑𝐎𝐀𝐃𝐂𝐀𝐒𝐓", "❌ Please use <code>/broadcast</code> in direct message with the bot for security."), parse_mode=ParseMode.HTML)
        return
    allowed, remaining = await broadcast_rate_limiter.check(update.effective_user.id, "broadcast")
    if not allowed:
        await update.message.reply_text(border_text("⏳ 𝐁𝐑𝐎𝐀𝐃𝐂𝐀𝐒𝐓 𝐂𝐎𝐎𝐋𝐃𝐎𝐖𝐍", f"Please wait {remaining}s before initiating another broadcast."), parse_mode=ParseMode.HTML)
        return
    success = await pending_manager.set(update.effective_chat.id, update.effective_user.id, {
        "action": "broadcast_waiting_content"
    })
    if not success:
        await update.message.reply_text(border_text("𝐁𝐑𝐎𝐀𝐃𝐂𝐀𝐒𝐓 • 𝐄𝐑𝐑𝐎𝐑", "❌ System busy. Try again later."), parse_mode=ParseMode.HTML)
        return
    await update.message.reply_text(
        border_text(
            "📢 𝐁𝐑𝐎𝐀𝐃𝐂𝐀𝐒𝐓 𝐈𝐍𝐈𝐓𝐈𝐀𝐓𝐄𝐃",
            "Please send the exact message or media you want to broadcast across all monitored groups and users.\n\n"
            "You will be prompted for final confirmation before dispatch."
        ),
        parse_mode=ParseMode.HTML
    )

async def handle_broadcast_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the content sent after /broadcast command."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if user_id != GLOBAL_OWNER_ID or chat_id != update.effective_user.id:
        return
    pending = await pending_manager.get(chat_id, user_id)
    if not pending or pending.get("action") != "broadcast_waiting_content":
        return
    await pending_manager.set(chat_id, user_id, {
        "action": "broadcast_confirm",
        "from_chat_id": chat_id,
        "message_id": update.message.message_id
    })
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ CONFIRM DISPATCH", callback_data="broadcast_confirm"),
         InlineKeyboardButton("❌ CANCEL", callback_data="broadcast_cancel")]
    ])
    await update.message.reply_text(
        border_text("📢 𝐂𝐎𝐍𝐅𝐈𝐑𝐌 𝐁𝐑𝐎𝐀𝐃𝐂𝐀𝐒𝐓", "Ready to copy and dispatch this message to all groups and users. Confirm action?"),
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )

async def broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    if user_id != GLOBAL_OWNER_ID:
        await query.edit_message_text(border_text("𝐁𝐑𝐎𝐀𝐃𝐂𝐀𝐒𝐓 • 𝐄𝐑𝐑𝐎𝐑", "❌ Unauthorized."), parse_mode=ParseMode.HTML)
        return
    data = query.data
    if data == "broadcast_confirm":
        pending = await pending_manager.get(chat_id, user_id)
        if not pending or pending.get("action") != "broadcast_confirm":
            await query.edit_message_text(border_text("𝐁𝐑𝐎𝐀𝐃𝐂𝐀𝐒𝐓 • 𝐄𝐗𝐏𝐈𝐑𝐄𝐃", "❌ No pending broadcast action found."), parse_mode=ParseMode.HTML)
            return
        from_chat = pending["from_chat_id"]
        msg_id = pending["message_id"]
        groups = await db.get_all_groups()
        all_user_ids = await db.get_all_user_ids()
        success_count = 0
        fail_count = 0
        for group in groups:
            try:
                await context.bot.copy_message(
                    chat_id=group['chat_id'],
                    from_chat_id=from_chat,
                    message_id=msg_id
                )
                success_count += 1
            except Exception as e:
                logger.warning(f"Broadcast to group {group['chat_id']} failed: {e}")
                fail_count += 1
        for uid in all_user_ids:
            try:
                await context.bot.copy_message(
                    chat_id=uid,
                    from_chat_id=from_chat,
                    message_id=msg_id
                )
                success_count += 1
            except Exception as e:
                logger.debug(f"Broadcast to user {uid} failed: {e}")
                fail_count += 1
        content = (
            f"📢 <b>Broadcast Complete!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ <b>Delivered Successfully:</b> {success_count}\n"
            f"❌ <b>Failed / Blocked:</b> {fail_count}"
        )
        await query.edit_message_text(border_text("𝐁𝐑𝐎𝐀𝐃𝐂𝐀𝐒𝐓 • 𝐒𝐔𝐌𝐌𝐀𝐑𝐘", content), parse_mode=ParseMode.HTML)
        await pending_manager.delete(chat_id, user_id)
    elif data == "broadcast_cancel":
        await pending_manager.delete(chat_id, user_id)
        await query.edit_message_text(border_text("𝐁𝐑𝐎𝐀𝐃𝐂𝐀𝐒𝐓 • 𝐂𝐀𝐍𝐂𝐄𝐋𝐋𝐄𝐃", "❌ Broadcast action aborted."), parse_mode=ParseMode.HTML)

# =============================================================================
# SECTION 15: OWNER COMMANDS
# =============================================================================

@safe_reply
@require_group
async def analytics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_owner(update, context):
        return
    
    chat_id = update.effective_chat.id
    stats = await db.get_group_stats(chat_id)
    
    top_name = stats['top_user']['username'] if stats['top_user'] else "N/A"
    top_xp = format_number(stats['top_user']['xp']) if stats['top_user'] else "0"
    
    content = (
        f"📊 <b>Group Insights & Metrics</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 <b>Tracked Users:</b> {format_number(stats['user_count'])}\n"
        f"💬 <b>Top Chatter:</b> @{top_name} ({top_xp} XP)\n"
        f"🏥 <b>System Status:</b> Active & Synchronized\n"
        f"🕒 <i>Updated: {datetime.now(IST).strftime('%I:%M %p IST')}</i>"
    )
    await update.message.reply_text(border_text("𝐆𝐑𝐎𝐔𝐏 𝐀𝐍𝐀𝐋𝐘𝐓𝐈𝐂𝐒", content), parse_mode=ParseMode.HTML)

@safe_reply
@require_group
async def members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_owner(update, context):
        return
    
    chat_id = update.effective_chat.id
    try:
        total = await context.bot.get_chat_member_count(chat_id)
        admins = await context.bot.get_chat_administrators(chat_id)
        creator = next((a.user.first_name for a in admins if a.status == "creator"), "Unknown")
    except Exception as e:
        logger.error(f"Members error: {e}")
        await update.message.reply_text(border_text("𝐌𝐄𝐌𝐁𝐄𝐑𝐒 • 𝐄𝐑𝐑𝐎𝐑", "❌ Could not fetch telegram group member telemetry."), parse_mode=ParseMode.HTML)
        return
    
    content = (
        f"👥 <b>Total Members:</b> {format_number(total)}\n"
        f"🛠️ <b>Administrators:</b> {len(admins)}\n"
        f"👑 <b>Group Founder:</b> {creator}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 <b>Title:</b> {update.effective_chat.title}\n"
        f"🆔 <b>Chat ID:</b> <code>{chat_id}</code>"
    )
    await update.message.reply_text(border_text("𝐌𝐄𝐌𝐁𝐄𝐑 𝐓𝐄𝐋𝐄𝐌𝐄𝐓𝐑𝐘", content), parse_mode=ParseMode.HTML)

@safe_reply
@require_group
async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_owner(update, context):
        return
    await grpleaderboard(update, context)

@safe_reply
@require_group
async def addcoins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_owner(update, context):
        return
    if not update.message.reply_to_message:
        await update.message.reply_text(border_text("𝐀𝐃𝐃𝐂𝐎𝐈𝐍𝐒 • 𝐔𝐒𝐀𝐆𝐄", "❌ Reply to a user's message with <code>/addcoins</code> to grant them wealth."), parse_mode=ParseMode.HTML)
        return
    
    target = update.message.reply_to_message.from_user
    chat_id = update.effective_chat.id
    owner_id = update.effective_user.id
    
    success = await pending_manager.set(chat_id, owner_id, {
        "action": "addcoins",
        "target_id": target.id,
        "target_name": target.username or target.first_name
    })
    if not success:
        await update.message.reply_text(border_text("𝐀𝐃𝐃𝐂𝐎𝐈𝐍𝐒 • 𝐄𝐑𝐑𝐎𝐑", "❌ Too many pending actions right now. Try again later."), parse_mode=ParseMode.HTML)
        return
    await update.message.reply_text(border_text("𝐀𝐃𝐃𝐂𝐎𝐈𝐍𝐒 • 𝐀𝐌𝐎𝐔𝐍𝐓", f"💰 Enter the exact amount of coins to add to <b>@{target.username or target.first_name}</b>:"), parse_mode=ParseMode.HTML)

@safe_reply
@require_group
async def removecoins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_owner(update, context):
        return
    if not update.message.reply_to_message:
        await update.message.reply_text(border_text("𝐑𝐄𝐌𝐎𝐕𝐄𝐂𝐎𝐈𝐍𝐒 • 𝐔𝐒𝐀𝐆𝐄", "❌ Reply to a user's message with <code>/removecoins</code> to deduct wealth."), parse_mode=ParseMode.HTML)
        return
    
    target = update.message.reply_to_message.from_user
    chat_id = update.effective_chat.id
    owner_id = update.effective_user.id
    
    success = await pending_manager.set(chat_id, owner_id, {
        "action": "removecoins",
        "target_id": target.id,
        "target_name": target.username or target.first_name
    })
    if not success:
        await update.message.reply_text(border_text("𝐑𝐄𝐌𝐎𝐕𝐄𝐂𝐎𝐈𝐍𝐒 • 𝐄𝐑𝐑𝐎𝐑", "❌ Too many pending actions right now. Try again later."), parse_mode=ParseMode.HTML)
        return
    await update.message.reply_text(border_text("𝐑𝐄𝐌𝐎𝐕𝐄𝐂𝐎𝐈𝐍𝐒 • 𝐀𝐌𝐎𝐔𝐍𝐓", f"💰 Enter the exact amount of coins to remove from <b>@{target.username or target.first_name}</b>:"), parse_mode=ParseMode.HTML)

@safe_reply
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != GLOBAL_OWNER_ID:
        await update.message.reply_text(border_text("𝐒𝐓𝐀𝐓𝐒 • 𝐀𝐂𝐂𝐄𝐒𝐒", "❌ Only the Global Master can view system-wide group stats."), parse_mode=ParseMode.HTML)
        return
    
    groups = await db.get_all_groups()
    if not groups:
        await update.message.reply_text(border_text("𝐒𝐓𝐀𝐓𝐒 • 𝐆𝐑𝐎𝐔𝐏𝐒", "❌ No groups found in the monitoring registry."), parse_mode=ParseMode.HTML)
        return
    
    lines = [f"📌 <b>Monitored Groups: {len(groups)}</b>", "━━━━━━━━━━━━━━━━━━━━━━"]
    for g in groups[:25]:  # Limit display to 25 to ensure clean message size
        title = g['title'] or "Unknown Group"
        chat_id = g['chat_id']
        username = g.get('username') or "private"
        added = g['added_on'].strftime('%Y-%m-%d') if g['added_on'] else "unknown"
        try:
            members = await context.bot.get_chat_member_count(chat_id)
        except Exception:
            members = "?"
        lines.append(f"🏰 <b>{title}</b> (<code>{chat_id}</code>)")
        lines.append(f"   👥 {members} members | 📅 {added} | 🔗 @{username}")
    if len(groups) > 25:
        lines.append(f"\n<i>...and {len(groups) - 25} more groups.</i>")
    
    content = "\n".join(lines)
    await update.message.reply_text(border_text("𝐒𝐘𝐒𝐓𝐄𝐌 𝐆𝐑𝐎𝐔𝐏 𝐑𝐄𝐆𝐈𝐒𝐓𝐑𝐘", content), parse_mode=ParseMode.HTML)

# =============================================================================
# SECTION 16: MESSAGE HANDLERS
# =============================================================================

async def log_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle message XP and pending actions."""
    if not update.message or not update.effective_chat:
        return
    
    if update.message.text and update.message.text.startswith('/'):
        return
    
    if update.effective_chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    username = update.effective_user.username or update.effective_user.first_name
    text = update.message.text or ""
    
    pending = await pending_manager.get(chat_id, user_id)
    if pending:
        await handle_pending(update, pending)
        return
    
    if text:
        await process_message_xp(user_id, username, chat_id, context)

async def handle_pending(update: Update, pending: Dict[str, Any]):
    """Handle pending actions from numeric/text replies."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    text = (update.message.text or "").strip()
    action = pending.get("action")
    target_id = pending.get("target_id")
    target_name = pending.get("target_name", "Unknown")
    
    if action in ("addcoins", "removecoins"):
        if not text.isdigit():
            await update.message.reply_text(border_text("𝐄𝐑𝐑𝐎𝐑", "❌ Please enter a valid positive numeric value."), parse_mode=ParseMode.HTML)
            return
        
        amount = int(text)
        if amount <= 0:
            await update.message.reply_text(border_text("𝐄𝐑𝐑𝐎𝐑", "❌ Amount must be greater than zero."), parse_mode=ParseMode.HTML)
            return
        if amount > 1000000:
            await update.message.reply_text(border_text("𝐄𝐑𝐑𝐎𝐑", "❌ Maximum transaction amount is 1,000,000 coins per command."), parse_mode=ParseMode.HTML)
            return
        
        if action == "addcoins":
            await db.update_user_per_group(target_id, chat_id, target_name, coins_delta=amount)
            await db.update_user_global(target_id, target_name, coins_delta=amount)
            verb = "granted to"
            logger.info(f"Owner {user_id} added {amount} coins to {target_id} in {chat_id}")
        else:
            target_per = await db.get_user_per_group(target_id, chat_id)
            if target_per and target_per['coins'] < amount:
                await update.message.reply_text(border_text("𝐈𝐍𝐒𝐔𝐅𝐅𝐈𝐂𝐈𝐄𝐍𝐓", f"❌ @{target_name} only has {format_number(target_per['coins'])} coins in this group."), parse_mode=ParseMode.HTML)
                await pending_manager.delete(chat_id, user_id)
                return
            await db.update_user_per_group(target_id, chat_id, target_name, coins_delta=-amount)
            await db.update_user_global(target_id, target_name, coins_delta=-amount)
            verb = "removed from"
            logger.info(f"Owner {user_id} removed {amount} coins from {target_id} in {chat_id}")
        
        new_global = await db.get_user_global(target_id)
        new_per = await db.get_user_per_group(target_id, chat_id)
        content = (
            f"✅ <b>{format_number(amount)} coins {verb} @{target_name}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💎 <b>Global Balance:</b> {format_number(new_global['total_coins'] if new_global else 0)}\n"
            f"📊 <b>Group Balance:</b> {format_number(new_per['coins'] if new_per else 0)}"
        )
        await update.message.reply_text(border_text("𝐂𝐎𝐈𝐍 𝐓𝐑𝐀𝐍𝐒𝐀𝐂𝐓𝐈𝐎𝐍 • 𝐒𝐔𝐂𝐂𝐄𝐒𝐒", content), parse_mode=ParseMode.HTML)
        await pending_manager.delete(chat_id, user_id)

# =============================================================================
# SECTION 17: CHAT MEMBER & WELCOME HANDLERS
# =============================================================================

async def welcome_new_chat_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Luxurious greeting when new human users join a monitored group."""
    if not update.message or not update.message.new_chat_members:
        return
    chat = update.effective_chat
    for new_user in update.message.new_chat_members:
        if new_user.id == context.bot.id:
            continue
        username = new_user.username or new_user.first_name
        await db.update_user_global(new_user.id, username)
        await db.update_user_per_group(new_user.id, chat.id, username, msg_inc=False)
        
        content = (
            f"✨ Welcome, <b>{new_user.first_name}</b>, to <b>{chat.title}</b>!\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎉 We are thrilled to have you join our community.\n"
            f"💬 Start chatting right now to earn <b>XP & Coins</b> automatically!\n"
            f"🆙 Level up, purchase shields, and join powerful guilds.\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎁 <i>Claim your starter reward by typing <code>/daily</code>!</i>"
        )
        keyboard = [
            [
                InlineKeyboardButton("👤 My Profile", callback_data="start_my_stats"),
                InlineKeyboardButton("📚 Help Dashboard", url=f"https://t.me/{context.bot.username}?start=help")
            ]
        ]
        try:
            await update.message.reply_text(
                border_text("🌟 𝐍𝐄𝐖 𝐌𝐄𝐌𝐁𝐄𝐑 𝐀𝐑𝐑𝐈𝐕𝐀𝐋 🌟", content),
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.warning(f"Failed to send welcome message: {e}")

async def track_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Track bot addition/removal from groups with a grand welcome announcement."""
    result = update.my_chat_member
    if not result:
        return
    
    chat = result.chat
    user = result.from_user
    new_status = result.new_chat_member.status if result.new_chat_member else None
    old_status = result.old_chat_member.status if result.old_chat_member else None
    
    if new_status == "member" and old_status == "left":
        await db.add_group(chat.id, chat.title, chat.username, chat.invite_link)
        await db.update_user_per_group(user.id, chat.id, user.username or user.first_name, is_verified_owner=1)
        
        content = (
            f"🌟 <b>𝓛𝓾𝓶𝓲𝓻𝓪 Has Arrived in {chat.title}!</b> 🌟\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👑 <b>Group Owner Registered:</b> {user.first_name} (<code>{user.id}</code>)\n"
            f"⚡ <b>Enabled Automation & Systems:</b>\n"
            f"  ┣ 📈 Automatic XP & Level Progression (+{XP_PER_MESSAGE} XP/msg)\n"
            f"  ┣ 💰 Daily Coin Rewards (<code>/daily</code>) & Scratch Cards (<code>/scratch</code>)\n"
            f"  ┣ 🛡️ Shop System, Shields & PVP Heist Mechanics\n"
            f"  ┗ 🏰 Guild System & AI Assistant (<code>/ai</code>, <code>/roast</code>)\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 <i>Promote me to Administrator for maximum speed and member protection!</i>"
        )
        keyboard = [
            [
                InlineKeyboardButton("📚 Commands Help", url=f"https://t.me/{context.bot.username}?start=help"),
                InlineKeyboardButton("🏆 Group Leaderboard", callback_data="help_grp_top")
            ]
        ]
        try:
            await context.bot.send_message(
                chat.id,
                text=border_text("𝓛𝓤𝓜𝓘𝓡𝓐 • 𝐆𝐑𝐎𝐔𝐏 𝐀𝐂𝐓𝐈𝐕𝐀𝐓𝐈𝐎𝐍", content),
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.warning(f"Could not send group activation welcome: {e}")
        logger.info(f"Bot added to group {chat.id} ({chat.title}) by {user.id}")
    
    elif new_status == "left" and old_status == "member":
        await db.remove_group(chat.id)
        logger.info(f"Bot removed from group {chat.id}")

# =============================================================================
# SECTION 18: BOT INITIALIZATION
# =============================================================================

async def post_init(application):
    """Initialize database on startup."""
    await db.initialize()
    await db.init_schema()
    asyncio.create_task(pending_manager._cleanup_loop())
    logger.info("Bot initialized and ready!")

async def post_shutdown(application):
    """Cleanup on shutdown."""
    await db.close()
    logger.info("Bot shutdown complete.")

# =============================================================================
# SECTION 19: MAIN ENTRY POINT
# =============================================================================

def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set!")
        sys.exit(1)
    if not DATABASE_URL:
        logger.error("DATABASE_URL not set!")
        sys.exit(1)
    
    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    
    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("rank", rank))
    application.add_handler(CommandHandler("leaderboard", leaderboard))
    application.add_handler(CommandHandler("riches", riches))
    application.add_handler(CommandHandler("grpleaderboard", grpleaderboard))
    application.add_handler(CommandHandler("grpriches", grpriches))
    application.add_handler(CommandHandler("daily", daily))
    application.add_handler(CommandHandler("scratch", scratch))
    application.add_handler(CommandHandler("shop", shop))
    application.add_handler(CommandHandler("roast", roast))
    application.add_handler(CommandHandler("kill", kill))
    application.add_handler(CommandHandler("rob", rob))
    application.add_handler(CommandHandler("revive", revive))
    application.add_handler(CommandHandler("gift", gift))
    application.add_handler(CommandHandler("mygifts", mygifts))
    application.add_handler(CommandHandler("ai", ai_cmd))
    
    # Owner commands
    application.add_handler(CommandHandler("analytics", analytics))
    application.add_handler(CommandHandler("members", members))
    application.add_handler(CommandHandler("top", top))
    application.add_handler(CommandHandler("addcoins", addcoins))
    application.add_handler(CommandHandler("removecoins", removecoins))
    application.add_handler(CommandHandler("stats", stats))
    
    # Guild commands
    application.add_handler(CommandHandler("newguild", newguild))
    application.add_handler(CommandHandler("delguild", delguild))
    application.add_handler(CommandHandler("guilds_list", guilds_list))
    application.add_handler(CommandHandler("join_guild", join_guild))
    application.add_handler(CommandHandler("leave_guild", leave_guild))
    application.add_handler(CommandHandler("myguild", myguild))
    application.add_handler(CommandHandler("guild_leaderboard", guild_leaderboard))
    application.add_handler(CommandHandler("guild_members", guild_members))
    application.add_handler(CommandHandler("guild_info", guild_info))
    application.add_handler(CommandHandler("transfer_guild", transfer_guild))
    application.add_handler(CommandHandler("rename_guild", rename_guild))
    application.add_handler(CommandHandler("guild_stats", guild_stats))
    
    # Broadcast
    application.add_handler(CommandHandler("broadcast", broadcast))
    
    # Callback handlers
    application.add_handler(CallbackQueryHandler(buy_callback, pattern="^buy_"))
    application.add_handler(CallbackQueryHandler(gift_callback, pattern="^gift_"))
    application.add_handler(CallbackQueryHandler(leave_callback, pattern="^leave_"))
    application.add_handler(CallbackQueryHandler(delguild_callback, pattern="^delguild_"))
    application.add_handler(CallbackQueryHandler(broadcast_callback, pattern="^broadcast_"))
    application.add_handler(CallbackQueryHandler(nav_callback, pattern="^(start_|help_)"))
    
    # Message handlers
    application.add_handler(
        MessageHandler(
            filters.TEXT & filters.ChatType.GROUPS & ~filters.COMMAND,
            log_messages
        )
    )
    application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & filters.User(user_id=GLOBAL_OWNER_ID) & ~filters.COMMAND,
            handle_broadcast_content
        )
    )
    
    # Chat member & Welcome handlers
    application.add_handler(ChatMemberHandler(track_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_chat_members))
    
    # Run in Webhook or Polling mode
    if RUN_MODE == "polling" or not WEBHOOK_URL:
        logger.info("Starting bot in POLLING mode...")
        application.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
    else:
        logger.info(f"Starting webhook on {WEBHOOK_LISTEN}:{PORT} with URL {WEBHOOK_URL}/{BOT_TOKEN}")
        application.run_webhook(
            listen=WEBHOOK_LISTEN,
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
            secret_token=None,
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES,
        )

if __name__ == "__main__":
    main()
