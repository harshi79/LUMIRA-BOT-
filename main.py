#!/usr/bin/env python3
"""
Group Master Elite - Production-Grade Telegram Bot
Single-file architecture with internal service layers
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
GLOBAL_OWNER_ID = 7728424218

# Webhook configuration (for Render)
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", 8443))
WEBHOOK_LISTEN = os.getenv("WEBHOOK_LISTEN", "0.0.0.0")

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
MAX_GUILD_MEMBERS = 100              # Maximum members per guild
GUILD_CREATION_COST = 10000          # Coins required to create a guild (optional)
GUILD_XP_MESSAGE = 1                 # Guild XP per message
GUILD_XP_DAILY = 5                   # Guild XP for /daily
GUILD_XP_SCRATCH = 2                 # Guild XP for /scratch
GUILD_XP_KILL = 15                   # Guild XP for killing someone
GUILD_XP_ROB = 10                    # Guild XP for successful rob
GUILD_XP_REVIVE = 8                  # Guild XP for reviving someone
GUILD_XP_GIFT = 3                    # Guild XP for sending a gift
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
                return False, remaining
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
            # Check total size
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
            # Guild tables
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS guilds (
                    guild_id SERIAL PRIMARY KEY,
                    name TEXT UNIQUE NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    total_xp BIGINT NOT NULL DEFAULT 0,
                    member_count INT NOT NULL DEFAULT 0
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS guild_members (
                    user_id BIGINT PRIMARY KEY,
                    guild_id INT REFERENCES guilds(guild_id) ON DELETE CASCADE,
                    joined_at TIMESTAMPTZ DEFAULT NOW(),
                    contribution_xp BIGINT NOT NULL DEFAULT 0
                )
            """)
            # Guild leave cooldown table
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
            # Guild indexes
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_guilds_name ON guilds(name)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_guilds_created_at ON guilds(created_at)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_guild_members_guild_user ON guild_members(guild_id, user_id)")
            logger.info("Database schema initialized")
    
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
            set_clauses = []
            params = [user_id, chat_id, username]
            param_idx = 4
            
            if xp_delta != 0:
                set_clauses.append(f"xp = GREATEST(users_per_group.xp + ${param_idx}, 0)")
                params.append(xp_delta)
                param_idx += 1
            
            if coins_delta != 0:
                set_clauses.append(f"coins = GREATEST(users_per_group.coins + ${param_idx}, 0)")
                params.append(coins_delta)
                param_idx += 1
            
            if msg_inc:
                set_clauses.append("msg_count = users_per_group.msg_count + 1")
            
            if shield_expiry is not None:
                set_clauses.append(f"shield_expiry = ${param_idx}")
                params.append(shield_expiry)
                param_idx += 1
            
            if set_dead is not None:
                set_clauses.append(f"is_dead = ${param_idx}")
                params.append(set_dead)
                param_idx += 1
            
            if last_daily:
                set_clauses.append("last_daily = NOW()")
            
            if last_scratch:
                set_clauses.append("last_scratch = NOW()")
            
            if is_verified_owner is not None:
                set_clauses.append(f"is_verified_owner = ${param_idx}")
                params.append(is_verified_owner)
                param_idx += 1
            
            set_clause = ", ".join(set_clauses) if set_clauses else ""
            
            if set_clause:
                query = f"""
                    INSERT INTO users_per_group (user_id, chat_id, username)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (user_id, chat_id) DO UPDATE
                    SET username = EXCLUDED.username,
                        {set_clause}
                """
            else:
                query = """
                    INSERT INTO users_per_group (user_id, chat_id, username)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (user_id, chat_id) DO UPDATE
                    SET username = EXCLUDED.username
                """
            
            await conn.execute(query, *params)
    
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
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT user_id FROM users_per_group WHERE chat_id = $1 AND username = $2",
                chat_id, username.lstrip('@')
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
                return False, f"Insufficient coins. You have {sender['coins']}."
            
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
                VALUES ($1, $2, -$3)
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
            # Check if user has enough coins if cost is set (handled in command)
            guild_id = await conn.fetchval(
                "INSERT INTO guilds (name) VALUES ($1) RETURNING guild_id",
                name
            )
            logger.info(f"Guild created: {name} (ID: {guild_id}) by user {creator_id}")
            return guild_id
    
    async def delete_guild(self, guild_id: int, admin_id: Optional[int] = None) -> None:
        """Delete a guild. Members are automatically removed via CASCADE."""
        async with self.acquire() as conn:
            # Get name for logging
            guild = await self.get_guild_by_id(guild_id)
            name = guild['name'] if guild else 'Unknown'
            await conn.execute("DELETE FROM guilds WHERE guild_id = $1", guild_id)
            logger.info(f"Guild deleted: {name} (ID: {guild_id}) by admin {admin_id}")
    
    async def get_guild_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        async with self.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM guilds WHERE name = $1", name)
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
            # Check guild exists
            guild = await conn.fetchrow("SELECT * FROM guilds WHERE guild_id = $1", guild_id)
            if not guild:
                return False, "Guild does not exist."
            # Check member limit
            member_count = guild['member_count']
            if member_count >= MAX_GUILD_MEMBERS:
                return False, f"Guild is full (max {MAX_GUILD_MEMBERS} members)."
            # Check if user already in a guild
            existing = await conn.fetchval("SELECT 1 FROM guild_members WHERE user_id = $1", user_id)
            if existing:
                return False, "You are already in a guild."
            # Check cooldown
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
            # Add member
            await conn.execute("""
                INSERT INTO guild_members (user_id, guild_id, contribution_xp)
                VALUES ($1, $2, 0)
            """, user_id, guild_id)
            await conn.execute("UPDATE guilds SET member_count = member_count + 1 WHERE guild_id = $1", guild_id)
            # Remove cooldown if any (they are joining, so clear any previous record)
            await conn.execute("DELETE FROM guild_leave_cooldown WHERE user_id = $1", user_id)
            logger.info(f"User {user_id} joined guild {guild_id}")
            return True, "Successfully joined the guild."
    
    async def remove_user_from_guild(self, user_id: int) -> Tuple[bool, str]:
        """Remove user from their current guild. Returns (success, message)."""
        async with self.transaction() as conn:
            guild_id = await conn.fetchval("SELECT guild_id FROM guild_members WHERE user_id = $1", user_id)
            if not guild_id:
                return False, "You are not in any guild."
            # Delete member
            await conn.execute("DELETE FROM guild_members WHERE user_id = $1", user_id)
            await conn.execute("UPDATE guilds SET member_count = member_count - 1 WHERE guild_id = $1", guild_id)
            # Record leave time for cooldown
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
            return "AI is not configured."
        
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
            return "AI is sleeping. Try later!"
    
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
                        {"role": "system", "content": "You are a helpful AI assistant."},
                        {"role": "user", "content": question},
                    ],
                    max_tokens=500,
                )
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"AI error: {e}")
            return "AI is sleeping. Try later!"

ai_service = AIService()

# =============================================================================
# SECTION 9: UI FORMATTING UTILITIES
# =============================================================================
def get_level_symbol(level: int) -> str:
    for low, high, sym in LEVEL_SYMBOLS:
        if low <= level <= high:
            return sym
    return "⛧"

def format_number(num: int) -> str:
    return f"{num:,}"

def create_progress_bar(current: int, total: int, length: int = 10) -> str:
    filled = int((current / total) * length) if total > 0 else 0
    bar = "█" * filled + "░" * (length - filled)
    percentage = int((current / total) * 100) if total > 0 else 0
    return f"[{bar}] {percentage}%"

def border_text(title: str, content: str) -> str:
    separator = "─" * 20
    return f"┏━━━ {title} ━━━┓\n{content}\n┗{separator}┛"

def styled_box(title: str, lines: List[str], emoji: str = "✨") -> str:
    content = "\n".join(f"{emoji} {line}" for line in lines)
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
            await update.message.reply_text("❌ This command only works in groups.")
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
                    f"⏳ Rate limit hit! Try again in {remaining}s."
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
            logger.exception(f"Error in {func.__name__}")
            try:
                if update and update.effective_message:
                    await update.effective_message.reply_text(
                        "❌ An error occurred. Please try again later."
                    )
            except:
                pass
    return wrapper

# =============================================================================
# SECTION 11: OWNER VERIFICATION
# =============================================================================
async def is_owner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check if user is global owner or verified group owner."""
    user_id = update.effective_user.id
    if user_id == GLOBAL_OWNER_ID:
        return True
    
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
        await update.message.reply_text("❌ Only the group owner can use this command.")
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
    # Get current state
    old_global = await db.get_user_global(user_id)
    old_level = old_global['total_xp'] // XP_PER_LEVEL if old_global else 0
    
    # Update per-group and global
    await db.update_user_per_group(user_id, chat_id, username, xp_delta=XP_PER_MESSAGE, msg_inc=True)
    await db.update_user_global(user_id, username, xp_delta=XP_PER_MESSAGE)
    
    # Add guild XP if user is in a guild
    await db.add_guild_xp_for_user(user_id, GUILD_XP_MESSAGE)
    
    # Check level up
    new_global = await db.get_user_global(user_id)
    new_level = new_global['total_xp'] // XP_PER_LEVEL
    
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
        "𝐋𝐄𝐕𝐄𝐋 𝐔𝐏 !",
        f"🎉 @{username} just advanced to 𝐋𝐞𝐯𝐞𝐥 {new_level} ({symbol})!\nKeep grinding! 🔥"
    )
    try:
        await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Level up broadcast failed: {e}")
    
    # Elite achievement
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
        f"👑 @{username} has reached the ultimate rank: 𝐄𝐋𝐈𝐓𝐄 {symbol}!\nThis is a historic moment! Everyone cheer! 🎊"
    )
    for grp_id in chat_ids:
        try:
            await context.bot.send_message(chat_id=grp_id, text=elite_msg, parse_mode=ParseMode.HTML)
        except Exception:
            pass  # Bot might not be in group anymore

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
# SECTION 14: COMMAND HANDLERS
# =============================================================================

@safe_reply
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user.first_name or "User"
        msg = f"✨ Welcome {user} to 𝓛𝓾𝓶𝓲𝓻𝓪!\n\nUse /help for commands."
        await update.message.reply_text(msg)
    except:
        await update.message.reply_text("✨ 𝓛𝓾𝓶𝓲𝓻𝓪 - Use /help")

@safe_reply
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user.first_name or "User"
        
        help_text = (
            f"✨ <b>𝓛𝓾𝓶𝓲𝓻𝓪 - Help Menu</b> ✨\n\n"
            f"👋 Hey {user}! Here are all commands:\n\n"
            f"━━━━━━━━━━━━━━━━━━━\n\n"
            f"<b>👤 USER COMMANDS</b>\n"
            f"┣ /rank - Your global stats\n"
            f"┣ /leaderboard - Top 10 global XP\n"
            f"┣ /riches - Top 10 global coins\n"
            f"┣ /grpleaderboard - Top 10 group XP\n"
            f"┣ /grpriches - Top 10 group coins\n"
            f"┣ /daily - Claim 100 coins\n"
            f"┣ /scratch - Try your luck\n"
            f"┣ /shop - Buy items\n"
            f"┣ /roast @user - Roast someone\n"
            f"┣ /kill (reply) - Kill someone\n"
            f"┣ /rob (reply) - Steal coins\n"
            f"┣ /revive - Revive yourself\n"
            f"┣ /gift (reply) - Send gift\n"
            f"┣ /mygifts - View your gifts\n"
            f"┗ /ai - Ask AI anything\n\n"
            f"<b>🏰 GUILD COMMANDS</b>\n"
            f"┣ /join_guild &lt;name&gt; - Join a guild\n"
            f"┣ /leave_guild - Leave your guild\n"
            f"┣ /myguild - Your guild info\n"
            f"┣ /guild_leaderboard - Top guilds\n"
            f"┣ /guild_members - Guild members\n"
            f"┗ /guild_info &lt;name&gt; - Guild details\n\n"
            f"<b>👑 OWNER COMMANDS</b>\n"
            f"┣ /analytics - Group insights\n"
            f"┣ /members - Member stats\n"
            f"┣ /addcoins - Add coins (reply)\n"
            f"┣ /removecoins - Remove coins (reply)\n"
            f"┣ /stats - Bot groups list\n"
            f"┣ /newguild - Create guild\n"
            f"┗ /broadcast - Send message (DM)\n\n"
            f"━━━━━━━━━━━━━━━━━━━\n\n"
            f"⚡ Level up: {XP_PER_LEVEL} XP per level\n"
            f"🛡️ Shield: {SHIELD_COST} coins for {SHIELD_DURATION_HOURS}h\n"
            f"💰 Daily: {DAILY_COINS} coins\n\n"
            f"💫 <b>Enjoy with 𝓛𝓾𝓶𝓲𝓻𝓪!</b>"
        )
        
        await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        print(f"Help error: {e}")
        # Simple fallback
        await update.message.reply_text(
            "✨ <b>𝓛𝓾𝓶𝓲𝓻𝓪 Commands</b> ✨\n\n"
            "/rank, /daily, /shop, /roast, /kill, /gift, /join_guild\n\n"
            "Use /start for welcome message",
            parse_mode=ParseMode.HTML
        )

@safe_reply
@require_group
async def rank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    
    global_data = await db.get_user_global(user_id)
    if not global_data:
        await update.message.reply_text("❌ No stats yet. Start chatting!")
        return
    
    total_xp = global_data['total_xp']
    total_coins = global_data['total_coins']
    level = min(total_xp // XP_PER_LEVEL, MAX_LEVEL)
    symbol = get_level_symbol(level)
    xp_to_next = XP_PER_LEVEL - (total_xp % XP_PER_LEVEL) if level < MAX_LEVEL else 0
    total_msgs = await db.get_user_total_messages(user_id)
    
    progress = create_progress_bar(XP_PER_LEVEL - xp_to_next, XP_PER_LEVEL)
    
    content = (
        f"👤 @{username}\n"
        f"{'─' * 20}\n"
        f"✨ 𝐓𝐨𝐭𝐚𝐥 𝐗𝐏    : {format_number(total_xp)}\n"
        f"🆙 𝐋𝐞𝐯𝐞𝐥       : {level} {symbol}\n"
        f"📊 𝐏𝐫𝐨𝐠𝐫𝐞𝐬𝐬    : {progress}\n"
        f"💰 𝐓𝐨𝐭𝐚𝐥 𝐂𝐨𝐢𝐧𝐬 : {format_number(total_coins)}\n"
        f"📨 𝐌𝐞𝐬𝐬𝐚𝐠𝐞𝐬    : {format_number(total_msgs)}\n"
        f"{'─' * 20}\n"
        f"🕒 Last updated: just now"
    )
    await update.message.reply_text(border_text("𝐘𝐎𝐔𝐑 𝐆𝐋𝐎𝐁𝐀𝐋 𝐏𝐑𝐎𝐅𝐈𝐋𝐄", content), parse_mode=ParseMode.HTML)

@safe_reply
async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = await db.get_global_leaderboard(limit=10)
    if not rows:
        await update.message.reply_text("❌ No data yet.")
        return
    
    lines = []
    for i, row in enumerate(rows):
        name = row['username'] or "Unknown"
        level = min(row['level'], MAX_LEVEL)
        symbol = get_level_symbol(level)
        xp = format_number(row['total_xp'])
        lines.append(f"{MEDALS[i]} @{name} • L{level}{symbol} • {xp} XP")
    
    content = "\n".join(lines) + "\n\n🔥 Keep climbing the ranks!"
    await update.message.reply_text(border_text("𝐆𝐋𝐎𝐁𝐀𝐋 𝐗𝐏 𝐋𝐄𝐀𝐃𝐄𝐑𝐁𝐎𝐀𝐑𝐃", content), parse_mode=ParseMode.HTML)

@safe_reply
async def riches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = await db.get_riches_leaderboard(limit=10)
    if not rows:
        await update.message.reply_text("❌ No data yet.")
        return
    
    lines = []
    for i, row in enumerate(rows):
        title = RICHES_TITLES[i] if i < len(RICHES_TITLES) else f"{i+1}."
        name = row['username'] or "Unknown"
        coins = format_number(row['total_coins'])
        lines.append(f"{title} @{name} • {coins} 💰")
    
    content = "\n".join(lines) + "\n\n💎 The richer, the better!"
    await update.message.reply_text(border_text("𝐆𝐋𝐎𝐁𝐀𝐋 𝐂𝐎𝐈𝐍 𝐇𝐎𝐀𝐑𝐃𝐄𝐑𝐒", content), parse_mode=ParseMode.HTML)

@safe_reply
@require_group
async def grpleaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    rows = await db.get_group_leaderboard(chat_id, limit=10)
    if not rows:
        await update.message.reply_text("❌ No group stats yet.")
        return
    
    lines = []
    for i, row in enumerate(rows):
        name = row['username'] or "Unknown"
        level = min(row['level'], MAX_LEVEL)
        symbol = get_level_symbol(level)
        xp = format_number(row['xp'])
        lines.append(f"{MEDALS[i]} @{name} • L{level}{symbol} • {xp} XP")
    
    content = "\n".join(lines) + "\n\n🚀 Most active in this group!"
    await update.message.reply_text(border_text("𝐓𝐇𝐈𝐒 𝐆𝐑𝐎𝐔𝐏'𝐒 𝐗𝐏 𝐄𝐋𝐈𝐓𝐄", content), parse_mode=ParseMode.HTML)

@safe_reply
@require_group
async def grpriches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    rows = await db.get_group_riches(chat_id, limit=10)
    if not rows:
        await update.message.reply_text("❌ No group stats yet.")
        return
    
    lines = []
    for i, row in enumerate(rows):
        name = row['username'] or "Unknown"
        coins = format_number(row['coins'])
        lines.append(f"{MEDALS[i]} @{name} • {coins} 💰")
    
    content = "\n".join(lines) + "\n\n💸 Spend wisely!"
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
            content = f"⏳ Already claimed!\n{'─' * 20}\n⏰ Next in: {hours}h {minutes}m\n💎 Check back soon!"
            await update.message.reply_text(border_text("𝐂𝐎𝐎𝐋𝐃𝐎𝐖𝐍", content), parse_mode=ParseMode.HTML)
            return
    
    await db.update_user_global(user_id, username, coins_delta=DAILY_COINS)
    await db.update_user_per_group(user_id, chat_id, username, coins_delta=DAILY_COINS, last_daily=True)
    await db.add_guild_xp_for_user(user_id, GUILD_XP_DAILY)
    
    global_data = await db.get_user_global(user_id)
    new_balance = global_data['total_coins'] if global_data else DAILY_COINS
    
    content = (
        f"✨ +{DAILY_COINS} coins added!\n"
        f"{'─' * 20}\n"
        f"💰 Balance: {format_number(new_balance)}\n"
        f"📅 Next claim: in {DAILY_COOLDOWN_HOURS}h\n"
        f"💡 Tip: Try /scratch!"
    )
    await update.message.reply_text(border_text("𝐃𝐀𝐈𝐋𝐘 𝐑𝐄𝐖𝐀𝐑𝐃", content), parse_mode=ParseMode.HTML)

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
            content = f"⏳ Already scratched!\n{'─' * 20}\n⏰ Next in: {minutes}m\n💡 Try /daily!"
            await update.message.reply_text(border_text("𝐂𝐎𝐎𝐋𝐃𝐎𝐖𝐍", content), parse_mode=ParseMode.HTML)
            return
    
    win = random.randint(1, 1000)
    await db.update_user_global(user_id, username, coins_delta=win)
    await db.update_user_per_group(user_id, chat_id, username, coins_delta=win, last_scratch=True)
    await db.add_guild_xp_for_user(user_id, GUILD_XP_SCRATCH)
    
    global_data = await db.get_user_global(user_id)
    new_balance = global_data['total_coins'] if global_data else win
    
    if win > 0:
        content = (
            f"🎉 You won {format_number(win)} coins!\n"
            f"{'─' * 20}\n"
            f"💰 Balance: {format_number(new_balance)}\n"
            f"✨ Lucky streak!"
        )
    else:
        content = (
            f"😬 No win this time!\n"
            f"{'─' * 20}\n"
            f"💰 Balance: {format_number(new_balance)}\n"
            f"🔄 Try again in 1h!"
        )
    await update.message.reply_text(border_text("𝐒𝐂𝐑𝐀𝐓𝐂𝐇 𝐂𝐀𝐑𝐃", content), parse_mode=ParseMode.HTML)

@safe_reply
@require_group
async def shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton(f"🛡️ Shield ({SHIELD_COST} coins)", callback_data="buy_shield")],
        [InlineKeyboardButton("✨ Random XP (100 coins)", callback_data="buy_xp")],
        [InlineKeyboardButton("🎟️ Lottery Ticket (50 coins)", callback_data="buy_lottery")],
        [InlineKeyboardButton(f"💪 Revive Self ({REVIVE_SELF_COST} coins)", callback_data="buy_revive_self")],
        [InlineKeyboardButton(f"👥 Revive Other ({REVIVE_OTHER_COST} coins)", callback_data="buy_revive_other")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    content = "🛒 Select an item:"
    await update.message.reply_text(border_text("𝐒𝐇𝐎𝐏", content), reply_markup=reply_markup, parse_mode=ParseMode.HTML)

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
        await query.edit_message_text("❌ You need to chat first!")
        return
    
    coins = user_per_group['coins']
    
    if data == "buy_shield":
        if coins >= SHIELD_COST:
            expiry = datetime.now(IST) + timedelta(hours=SHIELD_DURATION_HOURS)
            await db.update_user_per_group(user_id, chat_id, username, coins_delta=-SHIELD_COST, shield_expiry=expiry)
            await db.update_user_global(user_id, username, coins_delta=-SHIELD_COST)
            content = f"🛡️ Shield active!\nProtected for {SHIELD_DURATION_HOURS}h.\n{'─' * 20}\n💰 Balance: {format_number(coins - SHIELD_COST)}"
            await query.edit_message_text(border_text("𝐏𝐔𝐑𝐂𝐇𝐀𝐒𝐄𝐃", content), parse_mode=ParseMode.HTML)
        else:
            content = f"❌ Need {SHIELD_COST} coins!\nYou have {format_number(coins)}.\n{'─' * 20}\n💰 Use /daily or /scratch!"
            await query.edit_message_text(border_text("𝐈𝐍𝐒𝐔𝐅𝐅𝐈𝐂𝐈𝐄𝐍𝐓", content), parse_mode=ParseMode.HTML)
    
    elif data == "buy_xp":
        price = 100
        if coins >= price:
            gain = random.randint(1, 50)
            await db.update_user_per_group(user_id, chat_id, username, coins_delta=-price, xp_delta=gain)
            await db.update_user_global(user_id, username, coins_delta=-price, xp_delta=gain)
            await db.add_guild_xp_for_user(user_id, 1)  # small contribution
            content = f"✨ +{gain} XP gained!\n{'─' * 20}\n💰 Balance: {format_number(coins - price)}"
            await query.edit_message_text(border_text("𝐏𝐔𝐑𝐂𝐇𝐀𝐒𝐄𝐃", content), parse_mode=ParseMode.HTML)
        else:
            content = f"❌ Need {price} coins!\nYou have {format_number(coins)}."
            await query.edit_message_text(border_text("𝐈𝐍𝐒𝐔𝐅𝐅𝐈𝐂𝐈𝐄𝐍𝐓", content), parse_mode=ParseMode.HTML)
    
    elif data == "buy_lottery":
        price = 50
        if coins >= price:
            win = random.choice([0, 100, 200, 500])
            await db.update_user_per_group(user_id, chat_id, username, coins_delta=-price + win)
            await db.update_user_global(user_id, username, coins_delta=-price + win)
            await db.add_guild_xp_for_user(user_id, 1)
            if win > 0:
                content = f"🎟️ Won {win} coins!\n{'─' * 20}\n💰 Balance: {format_number(coins - price + win)}"
            else:
                content = f"🎟️ No win!\n{'─' * 20}\n💰 Balance: {format_number(coins - price)}"
            await query.edit_message_text(border_text("𝐋𝐎𝐓𝐓𝐄𝐑𝐘", content), parse_mode=ParseMode.HTML)
        else:
            content = f"❌ Need {price} coins!\nYou have {format_number(coins)}."
            await query.edit_message_text(border_text("𝐈𝐍𝐒𝐔𝐅𝐅𝐈𝐂𝐈𝐄𝐍𝐓", content), parse_mode=ParseMode.HTML)
    
    elif data == "buy_revive_self":
        if not user_per_group.get('is_dead'):
            await query.edit_message_text("❌ You're already alive!")
            return
        if coins >= REVIVE_SELF_COST:
            await db.update_user_per_group(user_id, chat_id, username, coins_delta=-REVIVE_SELF_COST, set_dead=False)
            await db.update_user_global(user_id, username, coins_delta=-REVIVE_SELF_COST)
            await db.add_guild_xp_for_user(user_id, GUILD_XP_REVIVE)
            content = f"💪 Revived!\n{'─' * 20}\n💰 Balance: {format_number(coins - REVIVE_SELF_COST)}"
            await query.edit_message_text(border_text("𝐑𝐄𝐕𝐈𝐕𝐄𝐃", content), parse_mode=ParseMode.HTML)
        else:
            content = f"❌ Need {REVIVE_SELF_COST} coins!\nYou have {format_number(coins)}."
            await query.edit_message_text(border_text("𝐈𝐍𝐒𝐔𝐅𝐅𝐈𝐂𝐈𝐄𝐍𝐓", content), parse_mode=ParseMode.HTML)
    
    elif data == "buy_revive_other":
        await query.edit_message_text("📝 Use /revive @username to revive someone else!")

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
            except:
                pass
    else:
        await update.message.reply_text("❌ Reply to someone or use /roast @username")
        return
    
    if target_user and target_user.id == attacker.id:
        await update.message.reply_text("🤡 Why roast yourself? Get help.")
        return
    
    if target_user and target_user.id == context.bot.id:
        roast_text = await ai_service.roast(context.bot.first_name, "roasting myself")
        content = f"🔥 {roast_text}\n{'─' * 20}\n💀 Self-aware!"
        await update.message.reply_text(border_text("𝐑𝐎𝐀𝐒𝐓", content), parse_mode=ParseMode.HTML)
        return
    
    if target_user:
        target_data = await db.get_user_per_group(target_user.id, chat_id)
        if target_data and target_data.get('is_verified_owner') == 1:
            roast_text = await ai_service.roast(attacker.first_name, "tried to roast owner")
            content = f"🔥 @{attacker.username or attacker.first_name}, {roast_text}\n{'─' * 20}\n💀 Backfire!"
            await update.message.reply_text(border_text("𝐑𝐎𝐀𝐒𝐓", content), parse_mode=ParseMode.HTML)
            return
        
        if has_active_shield(target_data):
            content = f"🛡️ @{target_user.username or target_user.first_name} is shielded!"
            await update.message.reply_text(border_text("𝐒𝐇𝐈𝐄𝐋𝐃", content), parse_mode=ParseMode.HTML)
            return
    
    roast_text = await ai_service.roast(target_name)
    content = f"🔥 @{target_name}, {roast_text}\n{'─' * 20}\n💀 Destroyed!"
    await update.message.reply_text(border_text("𝐑𝐎𝐀𝐒𝐓", content), parse_mode=ParseMode.HTML)

@safe_reply
@require_group
@rate_limit_command("kill")
async def kill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Reply to someone to kill them!")
        return
    
    target = update.message.reply_to_message.from_user
    attacker = update.effective_user
    chat_id = update.effective_chat.id
    
    if target.id == context.bot.id:
        await update.message.reply_text("😵 I'm immortal!")
        return
    if target.id == attacker.id:
        await update.message.reply_text("🤡 Can't kill yourself.")
        return
    
    target_data = await db.get_user_per_group(target.id, chat_id)
    
    if target_data and target_data.get('is_verified_owner') == 1:
        await db.update_user_per_group(attacker.id, chat_id, attacker.username or attacker.first_name, set_dead=True)
        await update.message.reply_text(f"⚰️ @{attacker.username or attacker.first_name} tried to kill the owner and died!")
        return
    
    if has_active_shield(target_data):
        content = f"🛡️ @{target.username or target.first_name} is shielded!"
        await update.message.reply_text(border_text("𝐒𝐇𝐈𝐄𝐋𝐃", content), parse_mode=ParseMode.HTML)
        return
    
    if target_data and target_data.get('is_dead'):
        await update.message.reply_text(f"💀 @{target.username or target.first_name} is already dead!")
        return
    
    await db.update_user_per_group(target.id, chat_id, target.username or target.first_name, set_dead=True)
    await db.add_guild_xp_for_user(attacker.id, GUILD_XP_KILL)
    content = f"🔪 @{attacker.username or attacker.first_name} killed @{target.username or target.first_name}!\n💀 RIP"
    await update.message.reply_text(border_text("𝐊𝐈𝐋𝐋", content), parse_mode=ParseMode.HTML)

@safe_reply
@require_group
@rate_limit_command("rob")
async def rob(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Reply to someone to rob them!")
        return
    if not context.args:
        await update.message.reply_text("❌ Usage: /rob <amount> (reply to user)")
        return
    
    try:
        amount = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Amount must be a number.")
        return
    
    if amount <= 0:
        await update.message.reply_text("❌ Amount must be positive.")
        return
    if amount > 10000:
        await update.message.reply_text("❌ Max rob amount is 10,000 coins.")
        return
    
    target = update.message.reply_to_message.from_user
    thief = update.effective_user
    chat_id = update.effective_chat.id
    
    if target.id == thief.id:
        await update.message.reply_text("🤡 Can't rob yourself.")
        return
    if target.id == context.bot.id:
        await update.message.reply_text("😤 I have no coins.")
        return
    
    target_data = await db.get_user_per_group(target.id, chat_id)
    thief_data = await db.get_user_per_group(thief.id, chat_id)
    
    if not thief_data:
        await update.message.reply_text("❌ Chat first to earn coins.")
        return
    
    if target_data and target_data.get('is_verified_owner') == 1:
        fine = min(amount * 2, thief_data['coins'])
        await db.update_user_per_group(thief.id, chat_id, thief.username or thief.first_name, coins_delta=-fine)
        await db.update_user_global(thief.id, thief.username or thief.first_name, coins_delta=-fine)
        content = f"👑 Owner protection! Fined {format_number(fine)} coins.\n💰 New balance: {format_number(thief_data['coins'] - fine)}"
        await update.message.reply_text(border_text("𝐑𝐎𝐁 𝐅𝐀𝐈𝐋𝐄𝐃", content), parse_mode=ParseMode.HTML)
        return
    
    if has_active_shield(target_data):
        content = f"🛡️ @{target.username or target.first_name} is shielded!"
        await update.message.reply_text(border_text("𝐒𝐇𝐈𝐄𝐋𝐃", content), parse_mode=ParseMode.HTML)
        return
    
    if target_data and target_data.get('is_dead'):
        await update.message.reply_text(f"💀 @{target.username or target.first_name} is dead. No coins to steal.")
        return
    
    if not target_data or target_data['coins'] < amount:
        await update.message.reply_text(f"❌ @{target.username or target.first_name} doesn't have that many coins.")
        return
    
    success, msg = await db.transfer_coins(
        target.id, thief.id, chat_id, amount,
        target.username or target.first_name,
        thief.username or thief.first_name
    )
    
    if success:
        await db.add_guild_xp_for_user(thief.id, GUILD_XP_ROB)
        thief_new = thief_data['coins'] + amount
        content = f"💰 Robbed {format_number(amount)} coins from @{target.username or target.first_name}!\n💰 Your balance: {format_number(thief_new)}"
        await update.message.reply_text(border_text("𝐑𝐎𝐁", content), parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(f"❌ {msg}")

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
            await update.message.reply_text("❌ User not found in this group.")
            return
        
        target_data = await db.get_user_per_group(target_id, chat_id)
        if not target_data or not target_data.get('is_dead'):
            await update.message.reply_text(f"❌ @{target_name} is already alive.")
            return
        
        self_data = await db.get_user_per_group(user_id, chat_id)
        if not self_data or self_data['coins'] < REVIVE_OTHER_COST:
            await update.message.reply_text(f"❌ Need {REVIVE_OTHER_COST} coins to revive someone else.")
            return
        
        await db.update_user_per_group(target_id, chat_id, target_name, set_dead=False)
        await db.update_user_per_group(user_id, chat_id, username, coins_delta=-REVIVE_OTHER_COST)
        await db.update_user_global(user_id, username, coins_delta=-REVIVE_OTHER_COST)
        await db.add_guild_xp_for_user(user_id, GUILD_XP_REVIVE)
        
        content = f"💪 @{username} revived @{target_name}!\n💰 Spent {REVIVE_OTHER_COST} coins."
        await update.message.reply_text(border_text("𝐑𝐄𝐕𝐈𝐕𝐄", content), parse_mode=ParseMode.HTML)
    else:
        user_data = await db.get_user_per_group(user_id, chat_id)
        if not user_data:
            await update.message.reply_text("❌ Chat first to earn coins.")
            return
        if not user_data.get('is_dead'):
            await update.message.reply_text("❌ You're already alive.")
            return
        if user_data['coins'] < REVIVE_SELF_COST:
            await update.message.reply_text(f"❌ Need {REVIVE_SELF_COST} coins to revive yourself.")
            return
        
        await db.update_user_per_group(user_id, chat_id, username, coins_delta=-REVIVE_SELF_COST, set_dead=False)
        await db.update_user_global(user_id, username, coins_delta=-REVIVE_SELF_COST)
        await db.add_guild_xp_for_user(user_id, GUILD_XP_REVIVE)
        
        content = f"💪 Revived!\n💰 Balance: {format_number(user_data['coins'] - REVIVE_SELF_COST)}"
        await update.message.reply_text(border_text("𝐑𝐄𝐕𝐈𝐕𝐄", content), parse_mode=ParseMode.HTML)

@safe_reply
@require_group
async def gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Reply to someone to send a gift!")
        return
    
    target = update.message.reply_to_message.from_user
    sender = update.effective_user
    chat_id = update.effective_chat.id
    
    if target.id == sender.id:
        await update.message.reply_text("❌ Can't gift yourself.")
        return
    
    success = await pending_manager.set(chat_id, sender.id, {
        "action": "gift",
        "target_id": target.id,
        "target_name": target.username or target.first_name
    })
    if not success:
        await update.message.reply_text("❌ Too many pending actions. Try again later.")
        return
    
    keyboard = [
        [InlineKeyboardButton(f"{info['emoji']} {gtype.capitalize()} ({info['price']})", callback_data=f"gift_{gtype}")]
        for gtype, info in GIFT_TYPES.items()
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🎁 Choose a gift:", reply_markup=reply_markup)

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
        await query.edit_message_text("❌ No pending gift. Use /gift again.")
        return
    
    target_id = pending["target_id"]
    target_name = pending["target_name"]
    price = GIFT_TYPES[gift_type]["price"]
    emoji = GIFT_TYPES[gift_type]["emoji"]
    
    sender_data = await db.get_user_per_group(user_id, chat_id)
    if not sender_data or sender_data['coins'] < price:
        await query.edit_message_text(f"❌ Need {price} coins for this gift.")
        await pending_manager.delete(chat_id, user_id)
        return
    
    await db.update_user_per_group(user_id, chat_id, query.from_user.username or query.from_user.first_name, coins_delta=-price)
    await db.update_user_global(user_id, query.from_user.username or query.from_user.first_name, coins_delta=-price)
    await db.add_gift(user_id, target_id, chat_id, gift_type, price)
    await db.add_guild_xp_for_user(user_id, GUILD_XP_GIFT)
    
    content = f"🎁 Sent {emoji} {gift_type} to @{target_name}!"
    await query.edit_message_text(border_text("𝐆𝐈𝐅𝐓 𝐒𝐄𝐍𝐓", content), parse_mode=ParseMode.HTML)
    await context.bot.send_message(chat_id, f"@{target_name} check your gifts! 🎁")
    
    await pending_manager.delete(chat_id, user_id)

@safe_reply
async def mygifts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    gifts = await db.get_gifts(user_id, limit=10)
    
    if not gifts:
        await update.message.reply_text("❌ No gifts received yet.")
        return
    
    lines = []
    for g in gifts:
        from_data = await db.get_user_global(g['from_user'])
        from_un = from_data['username'] if from_data else str(g['from_user'])
        emoji = GIFT_TYPES.get(g['gift_type'], {}).get('emoji', '🎁')
        date_str = g['created_at'].strftime('%Y-%m-%d') if g['created_at'] else 'Unknown'
        lines.append(f"{emoji} From @{from_un} • {g['gift_type'].capitalize()} • {format_number(g['amount'])} • {date_str}")
    
    content = "\n".join(lines)
    await update.message.reply_text(border_text("𝐘𝐎𝐔𝐑 𝐆𝐈𝐅𝐓𝐒", content), parse_mode=ParseMode.HTML)

@safe_reply
@rate_limit_command("ai")
async def ai_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(context.args)
    if not prompt:
        await update.message.reply_text("❌ Usage: /ai <question>")
        return
    
    await update.message.reply_chat_action("typing")
    response = await ai_service.ask(prompt)
    await update.message.reply_text(border_text("𝐀𝐈 𝐀𝐒𝐒𝐈𝐒𝐓𝐀𝐍𝐓", response), parse_mode=ParseMode.HTML)

# ==================== NEW GUILD COMMANDS ====================

@safe_reply
async def newguild(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner-only: Create a new guild (max 10). Optionally deduct coins if cost set."""
    if update.effective_user.id != GLOBAL_OWNER_ID:
        await update.message.reply_text("❌ Only the global owner can create guilds.")
        return
    if not context.args:
        await update.message.reply_text("❌ Usage: /newguild <name>")
        return
    name = " ".join(context.args).strip()
    if len(name) > 30:
        await update.message.reply_text("❌ Guild name too long (max 30 chars).")
        return
    # Validate name characters (alphanumeric and spaces)
    if not re.match(r'^[a-zA-Z0-9 ]+$', name):
        await update.message.reply_text("❌ Guild name can only contain letters, numbers, and spaces.")
        return
    try:
        # Optional coin deduction
        if GUILD_CREATION_COST > 0:
            user_data = await db.get_user_global(GLOBAL_OWNER_ID)
            if not user_data or user_data['total_coins'] < GUILD_CREATION_COST:
                await update.message.reply_text(f"❌ You need {GUILD_CREATION_COST} coins to create a guild.")
                return
            await db.update_user_global(GLOBAL_OWNER_ID, update.effective_user.username or "Owner", coins_delta=-GUILD_CREATION_COST)
        
        guild_id = await db.create_guild(name, creator_id=GLOBAL_OWNER_ID)
        await update.message.reply_text(
            border_text("𝐆𝐔𝐈𝐋𝐃 𝐂𝐑𝐄𝐀𝐓𝐄𝐃", f"✅ Guild '{name}' created with ID {guild_id}."),
            parse_mode=ParseMode.HTML
        )
    except ValueError as e:
        await update.message.reply_text(f"❌ {e}")
    except Exception as e:
        logger.exception("Error creating guild")
        await update.message.reply_text("❌ An error occurred.")

@safe_reply
async def delguild(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner-only: Delete a guild by name."""
    if update.effective_user.id != GLOBAL_OWNER_ID:
        await update.message.reply_text("❌ Only the global owner can delete guilds.")
        return
    if not context.args:
        await update.message.reply_text("❌ Usage: /delguild <name>")
        return
    name = " ".join(context.args).strip()
    guild = await db.get_guild_by_name(name)
    if not guild:
        await update.message.reply_text("❌ Guild not found.")
        return
    # Confirm? We'll add inline confirmation to be safe
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ YES, delete", callback_data=f"delguild_confirm_{guild['guild_id']}"),
         InlineKeyboardButton("❌ Cancel", callback_data="delguild_cancel")]
    ])
    await update.message.reply_text(
        f"⚠️ Are you sure you want to delete guild '{name}'? This cannot be undone.",
        reply_markup=keyboard
    )

async def delguild_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("delguild_confirm_"):
        guild_id = int(data.split("_")[2])
        await db.delete_guild(guild_id, admin_id=query.from_user.id)
        await query.edit_message_text("✅ Guild has been deleted.")
    elif data == "delguild_cancel":
        await query.edit_message_text("❌ Cancelled.")

@safe_reply
async def guilds_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner-only: List all guilds."""
    if update.effective_user.id != GLOBAL_OWNER_ID:
        await update.message.reply_text("❌ Only the global owner can view all guilds.")
        return
    guilds = await db.list_guilds()
    if not guilds:
        await update.message.reply_text("No guilds exist yet.")
        return
    lines = [f"📋 Total Guilds: {len(guilds)}", ""]
    for g in guilds:
        lines.append(f"🏰 {g['name']} (ID: {g['guild_id']})")
        lines.append(f"   👥 Members: {g['member_count']} | 📊 XP: {format_number(g['total_xp'])}")
    content = "\n".join(lines)
    await update.message.reply_text(border_text("𝐀𝐋𝐋 𝐆𝐔𝐈𝐋𝐃𝐒", content), parse_mode=ParseMode.HTML)

@safe_reply
async def join_guild(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User command: Join a guild by name."""
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    if not context.args:
        await update.message.reply_text("❌ Usage: /join_guild <guild_name>")
        return
    name = " ".join(context.args).strip()
    guild = await db.get_guild_by_name(name)
    if not guild:
        await update.message.reply_text("❌ Guild not found.")
        return
    success, msg = await db.add_user_to_guild(user_id, guild['guild_id'], username)
    if success:
        await update.message.reply_text(
            border_text("𝐉𝐎𝐈𝐍𝐄𝐃 𝐆𝐔𝐈𝐋𝐃", f"✅ You joined '{guild['name']}'!"),
            parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text(f"❌ {msg}")

@safe_reply
async def leave_guild(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User command: Leave current guild."""
    user_id = update.effective_user.id
    guild = await db.get_user_guild(user_id)
    if not guild:
        await update.message.reply_text("❌ You are not in any guild.")
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ YES, leave", callback_data=f"leave_confirm_{guild['guild_id']}"),
         InlineKeyboardButton("❌ Cancel", callback_data="leave_cancel")]
    ])
    await update.message.reply_text(
        f"⚠️ Are you sure you want to leave guild '{guild['name']}'?",
        reply_markup=keyboard
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
            await query.edit_message_text("❌ You are no longer in that guild.")
            return
        success, msg = await db.remove_user_from_guild(user_id)
        if success:
            await query.edit_message_text("✅ You have left the guild.")
        else:
            await query.edit_message_text(f"❌ {msg}")
    elif data == "leave_cancel":
        await query.edit_message_text("❌ Cancelled.")

@safe_reply
async def myguild(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User command: Show current guild info."""
    user_id = update.effective_user.id
    guild = await db.get_user_guild(user_id)
    if not guild:
        await update.message.reply_text("❌ You are not in any guild.")
        return
    members = await db.get_guild_members(guild['guild_id'])
    user_contrib = next((m['contribution_xp'] for m in members if m['user_id'] == user_id), 0)
    level = db.calculate_guild_level(guild['total_xp'])
    content = (
        f"🏰 {guild['name']}\n"
        f"{'─' * 20}\n"
        f"📊 Level: {level}\n"
        f"✨ Total XP: {format_number(guild['total_xp'])}\n"
        f"👥 Members: {len(members)}\n"
        f"📈 Your contribution: {format_number(user_contrib)} XP\n"
        f"📅 Joined: {members[0]['joined_at'].strftime('%Y-%m-%d') if members else 'N/A'}"
    )
    await update.message.reply_text(border_text("𝐘𝐎𝐔𝐑 𝐆𝐔𝐈𝐋𝐃", content), parse_mode=ParseMode.HTML)

@safe_reply
async def guild_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Global guild leaderboard."""
    guilds = await db.get_guild_leaderboard(limit=10)
    if not guilds:
        await update.message.reply_text("❌ No guilds yet.")
        return
    lines = []
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    for i, g in enumerate(guilds):
        medal = medals[i] if i < len(medals) else f"{i+1}."
        lines.append(f"{medal} {g['name']}")
        lines.append(f"   📊 Level {g['level']} • XP: {format_number(g['total_xp'])} • 👥 {g['members']} members")
    content = "\n".join(lines)
    await update.message.reply_text(border_text("𝐓𝐎𝐏 𝐆𝐔𝐈𝐋𝐃𝐒", content), parse_mode=ParseMode.HTML)

@safe_reply
async def guild_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show members of your guild."""
    user_id = update.effective_user.id
    guild = await db.get_user_guild(user_id)
    if not guild:
        await update.message.reply_text("❌ You are not in any guild.")
        return
    members = await db.get_guild_members(guild['guild_id'])
    if not members:
        await update.message.reply_text("❌ No members found.")
        return
    lines = [f"🏰 {guild['name']} Members:", ""]
    for m in members:
        lines.append(f"👤 @{m['username']} – {format_number(m['contribution_xp'])} XP")
    content = "\n".join(lines)
    await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃 𝐌𝐄𝐌𝐁𝐄𝐑𝐒", content), parse_mode=ParseMode.HTML)

@safe_reply
async def guild_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View any guild's details by name."""
    if not context.args:
        await update.message.reply_text("❌ Usage: /guild_info <guild_name>")
        return
    name = " ".join(context.args).strip()
    guild = await db.get_guild_by_name(name)
    if not guild:
        await update.message.reply_text("❌ Guild not found.")
        return
    members = await db.get_guild_members(guild['guild_id'])
    level = db.calculate_guild_level(guild['total_xp'])
    content = (
        f"🏰 {guild['name']}\n"
        f"{'─' * 20}\n"
        f"📊 Level: {level}\n"
        f"✨ Total XP: {format_number(guild['total_xp'])}\n"
        f"👥 Members: {len(members)}\n"
        f"📅 Created: {guild['created_at'].strftime('%Y-%m-%d')}"
    )
    await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃 𝐈𝐍𝐅𝐎", content), parse_mode=ParseMode.HTML)

@safe_reply
async def transfer_guild(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner-only: Transfer guild ownership (rename guild or change owner)."""
    if update.effective_user.id != GLOBAL_OWNER_ID:
        await update.message.reply_text("❌ Only the global owner can transfer guilds.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("❌ Usage: /transfer_guild <old_name> <new_owner_username>")
        return
    old_name = context.args[0]
    new_owner_username = context.args[1].lstrip('@')
    # Not implemented fully; just a placeholder for now
    await update.message.reply_text("❌ Transfer not yet implemented.")

@safe_reply
async def rename_guild(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner-only: Rename a guild."""
    if update.effective_user.id != GLOBAL_OWNER_ID:
        await update.message.reply_text("❌ Only the global owner can rename guilds.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("❌ Usage: /rename_guild <old_name> <new_name>")
        return
    old_name = context.args[0]
    new_name = " ".join(context.args[1:]).strip()
    if len(new_name) > 30:
        await update.message.reply_text("❌ New name too long (max 30 chars).")
        return
    if not re.match(r'^[a-zA-Z0-9 ]+$', new_name):
        await update.message.reply_text("❌ Guild name can only contain letters, numbers, and spaces.")
        return
    guild = await db.get_guild_by_name(old_name)
    if not guild:
        await update.message.reply_text("❌ Guild not found.")
        return
    try:
        async with db.transaction() as conn:
            await conn.execute("UPDATE guilds SET name = $1 WHERE guild_id = $2", new_name, guild['guild_id'])
        await update.message.reply_text(f"✅ Guild renamed to '{new_name}'.")
        logger.info(f"Guild {guild['guild_id']} renamed from '{old_name}' to '{new_name}' by owner {GLOBAL_OWNER_ID}")
    except asyncpg.UniqueViolationError:
        await update.message.reply_text("❌ A guild with that name already exists.")
    except Exception as e:
        logger.exception("Error renaming guild")
        await update.message.reply_text("❌ An error occurred.")

@safe_reply
async def guild_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner-only: Detailed guild statistics."""
    if update.effective_user.id != GLOBAL_OWNER_ID:
        await update.message.reply_text("❌ Only the global owner can view guild stats.")
        return
    if not context.args:
        await update.message.reply_text("❌ Usage: /guild_stats <guild_name>")
        return
    name = " ".join(context.args).strip()
    guild = await db.get_guild_by_name(name)
    if not guild:
        await update.message.reply_text("❌ Guild not found.")
        return
    members = await db.get_guild_members(guild['guild_id'])
    level = db.calculate_guild_level(guild['total_xp'])
    # Additional stats could include growth over time if we had history
    content = (
        f"🏰 {guild['name']} Statistics\n"
        f"{'─' * 20}\n"
        f"📊 Level: {level}\n"
        f"✨ Total XP: {format_number(guild['total_xp'])}\n"
        f"👥 Members: {len(members)}\n"
        f"📅 Created: {guild['created_at'].strftime('%Y-%m-%d %H:%M')}\n"
        f"📈 Average contribution: {format_number(guild['total_xp'] // max(1, len(members)))} XP per member"
    )
    await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃 𝐒𝐓𝐀𝐓𝐒", content), parse_mode=ParseMode.HTML)

# ==================== BROADCAST SYSTEM ====================

@safe_reply
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner-only: Start broadcast process (only in private)."""
    if update.effective_user.id != GLOBAL_OWNER_ID:
        await update.message.reply_text("❌ Only the global owner can broadcast.")
        return
    if update.effective_chat.type != ChatType.PRIVATE:
        await update.message.reply_text("❌ Please use this command in private chat with the bot.")
        return
    # Rate limit broadcast
    allowed, remaining = await broadcast_rate_limiter.check(update.effective_user.id, "broadcast")
    if not allowed:
        await update.message.reply_text(f"⏳ Broadcast rate limit hit! Try again in {remaining}s.")
        return
    success = await pending_manager.set(update.effective_chat.id, update.effective_user.id, {
        "action": "broadcast_waiting_content"
    })
    if not success:
        await update.message.reply_text("❌ Too many pending actions. Try again later.")
        return
    await update.message.reply_text(
        "📢 Please send the message you want to broadcast.\n"
        "You can send text, photo, video, document, etc.\n"
        "I will then ask for confirmation."
    )

async def handle_broadcast_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the content sent after /broadcast command."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if user_id != GLOBAL_OWNER_ID or chat_id != update.effective_user.id:  # only private
        return
    pending = await pending_manager.get(chat_id, user_id)
    if not pending or pending.get("action") != "broadcast_waiting_content":
        return
    # Store the message to broadcast (we'll copy it later)
    await pending_manager.set(chat_id, user_id, {
        "action": "broadcast_confirm",
        "from_chat_id": chat_id,
        "message_id": update.message.message_id
    })
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ CONFIRM", callback_data="broadcast_confirm"),
         InlineKeyboardButton("❌ CANCEL", callback_data="broadcast_cancel")]
    ])
    await update.message.reply_text(
        "📢 Ready to broadcast. Please confirm:",
        reply_markup=keyboard
    )

async def broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    if user_id != GLOBAL_OWNER_ID:
        await query.edit_message_text("❌ Unauthorized.")
        return
    data = query.data
    if data == "broadcast_confirm":
        pending = await pending_manager.get(chat_id, user_id)
        if not pending or pending.get("action") != "broadcast_confirm":
            await query.edit_message_text("❌ No pending broadcast.")
            return
        from_chat = pending["from_chat_id"]
        msg_id = pending["message_id"]
        groups = await db.get_all_groups()
        all_user_ids = await db.get_all_user_ids()
        success_count = 0
        fail_count = 0
        # Send to groups
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
        # Send to users (private)
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
        await query.edit_message_text(
            f"📢 Broadcast completed!\n"
            f"✅ Success: {success_count}\n"
            f"❌ Failed: {fail_count}"
        )
        await pending_manager.delete(chat_id, user_id)
    elif data == "broadcast_cancel":
        await pending_manager.delete(chat_id, user_id)
        await query.edit_message_text("❌ Broadcast cancelled.")

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
    top_xp = stats['top_user']['xp'] if stats['top_user'] else 0
    
    content = (
        f"📊 Group Insights\n"
        f"{'─' * 20}\n"
        f"👥 Tracked users: {stats['user_count']}\n"
        f"💬 Top chatter: @{top_name} ({format_number(top_xp)} XP)\n"
        f"🏥 Status: Active\n"
        f"🕒 {datetime.now(IST).strftime('%I:%M %p IST')}"
    )
    await update.message.reply_text(border_text("𝐀𝐍𝐀𝐋𝐘𝐓𝐈𝐂𝐒", content), parse_mode=ParseMode.HTML)

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
        await update.message.reply_text("❌ Could not fetch members.")
        return
    
    content = (
        f"👥 Total: {total}\n"
        f"🛠️ Admins: {len(admins)}\n"
        f"👑 Founder: {creator}\n"
        f"{'─' * 20}\n"
        f"📌 {update.effective_chat.title}\n"
        f"🆔 {chat_id}"
    )
    await update.message.reply_text(border_text("𝐌𝐄𝐌𝐁𝐄𝐑𝐒", content), parse_mode=ParseMode.HTML)

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
        await update.message.reply_text("❌ Reply to a user with /addcoins")
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
        await update.message.reply_text("❌ Too many pending actions. Try again later.")
        return
    await update.message.reply_text("💰 How many coins to add?")

@safe_reply
@require_group
async def removecoins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_owner(update, context):
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Reply to a user with /removecoins")
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
        await update.message.reply_text("❌ Too many pending actions. Try again later.")
        return
    await update.message.reply_text("💰 How many coins to remove?")

@safe_reply
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != GLOBAL_OWNER_ID:
        await update.message.reply_text("❌ Only global owner can use this.")
        return
    
    groups = await db.get_all_groups()
    if not groups:
        await update.message.reply_text("❌ No groups found.")
        return
    
    lines = [f"📌 Total Groups: {len(groups)}", ""]
    for g in groups:
        title = g['title'] or "Unknown"
        chat_id = g['chat_id']
        username = g.get('username') or "private"
        added = g['added_on'].strftime('%Y-%m-%d') if g['added_on'] else "unknown"
        try:
            members = await context.bot.get_chat_member_count(chat_id)
        except:
            members = "?"
        lines.append(f"{title} (ID: {chat_id})")
        lines.append(f"   👥 {members} members | 📅 {added} | 🔗 @{username}")
    
    content = "\n".join(lines)
    await update.message.reply_text(border_text("𝐁𝐎𝐓 𝐆𝐑𝐎𝐔𝐏𝐒", content), parse_mode=ParseMode.HTML)

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
            await update.message.reply_text("❌ Enter a valid number.")
            return
        
        amount = int(text)
        if amount <= 0:
            await update.message.reply_text("❌ Amount must be positive.")
            return
        if amount > 1000000:
            await update.message.reply_text("❌ Max amount is 1,000,000.")
            return
        
        if action == "addcoins":
            await db.update_user_per_group(target_id, chat_id, target_name, coins_delta=amount)
            await db.update_user_global(target_id, target_name, coins_delta=amount)
            verb = "added to"
            logger.info(f"Owner {user_id} added {amount} coins to {target_id} in {chat_id}")
        else:
            target_per = await db.get_user_per_group(target_id, chat_id)
            if target_per and target_per['coins'] < amount:
                await update.message.reply_text(f"❌ @{target_name} only has {target_per['coins']} coins.")
                await pending_manager.delete(chat_id, user_id)
                return
            await db.update_user_per_group(target_id, chat_id, target_name, coins_delta=-amount)
            await db.update_user_global(target_id, target_name, coins_delta=-amount)
            verb = "removed from"
            logger.info(f"Owner {user_id} removed {amount} coins from {target_id} in {chat_id}")
        
        new_global = await db.get_user_global(target_id)
        new_per = await db.get_user_per_group(target_id, chat_id)
        content = (
            f"✅ {format_number(amount)} coins {verb} @{target_name}.\n"
            f"{'─' * 20}\n"
            f"💎 Global: {format_number(new_global['total_coins'])}\n"
            f"📊 Group: {format_number(new_per['coins'])}"
        )
        await update.message.reply_text(border_text("𝐂𝐎𝐈𝐍𝐒 𝐔𝐏𝐃𝐀𝐓𝐄𝐃", content), parse_mode=ParseMode.HTML)
        await pending_manager.delete(chat_id, user_id)

# =============================================================================
# SECTION 17: CHAT MEMBER HANDLERS
# =============================================================================

async def track_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Track bot addition/removal from groups."""
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
        try:
            await context.bot.send_message(chat.id, f"✅ Bot added! {user.first_name} is now the group owner.")
        except:
            pass
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
    # Start pending cleanup task
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
    
  # Chat member handler
    application.add_handler(ChatMemberHandler(track_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    
    # Start webhook
    logger.info(f"Starting webhook on {WEBHOOK_LISTEN}:{PORT} with URL {WEBHOOK_URL}/{BOT_TOKEN}")
    application.run_webhook(
        listen=WEBHOOK_LISTEN,
        port=PORT,
        url_path=BOT_TOKEN,               # secret path using bot token
        webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
        secret_token=None,                 # optional: add a secret for extra security
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )

if __name__ == "__main__":
    main()
