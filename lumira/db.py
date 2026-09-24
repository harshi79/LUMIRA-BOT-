"""Database service layer — asyncpg pool + schema + economy/guild queries.

v4 schema additions (all backward-compatible, auto-migrated):
  • users_per_group.daily_streak  — consecutive-day /daily streak counter
  • helper rank-position queries for richer profile cards
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import asyncpg

from . import config
from .utils import format_number, localize, logger, utcnow


class DatabaseService:
    """Singleton database service with connection pooling."""

    _instance: Optional["DatabaseService"] = None
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
                    config.DATABASE_URL,
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

    # ==================== SCHEMA ====================
    async def init_schema(self) -> None:
        async with self.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users_global (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT NOT NULL DEFAULT 'Unknown',
                    total_xp BIGINT NOT NULL DEFAULT 0,
                    total_coins BIGINT NOT NULL DEFAULT 0,
                    level INT NOT NULL DEFAULT 0,
                    last_updated TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS groups (
                    chat_id BIGINT PRIMARY KEY,
                    title TEXT,
                    username TEXT,
                    invite_link TEXT,
                    added_on TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            await conn.execute(
                """
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
                    daily_streak INT NOT NULL DEFAULT 0,
                    PRIMARY KEY (user_id, chat_id)
                )
                """
            )
            # v4 migration for pre-existing deployments
            await conn.execute("ALTER TABLE users_per_group ADD COLUMN IF NOT EXISTS daily_streak INT NOT NULL DEFAULT 0")
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS gifts (
                    id SERIAL PRIMARY KEY,
                    from_user BIGINT NOT NULL,
                    to_user BIGINT NOT NULL,
                    chat_id BIGINT NOT NULL,
                    gift_type TEXT NOT NULL,
                    amount INT NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS guilds (
                    guild_id SERIAL PRIMARY KEY,
                    name TEXT UNIQUE NOT NULL,
                    owner_id BIGINT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    total_xp BIGINT NOT NULL DEFAULT 0,
                    member_count INT NOT NULL DEFAULT 0
                )
                """
            )
            await conn.execute("ALTER TABLE guilds ADD COLUMN IF NOT EXISTS owner_id BIGINT")
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS guild_members (
                    user_id BIGINT PRIMARY KEY,
                    guild_id INT REFERENCES guilds(guild_id) ON DELETE CASCADE,
                    joined_at TIMESTAMPTZ DEFAULT NOW(),
                    contribution_xp BIGINT NOT NULL DEFAULT 0
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS guild_leave_cooldown (
                    user_id BIGINT PRIMARY KEY,
                    left_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
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

    # ==================== USERS GLOBAL ====================
    async def get_user_global(self, user_id: int) -> Optional[Dict[str, Any]]:
        async with self.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM users_global WHERE user_id = $1", user_id)
            return dict(row) if row else None

    async def update_user_global(self, user_id: int, username: str, xp_delta: int = 0, coins_delta: int = 0) -> None:
        async with self.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO users_global (user_id, username, total_xp, total_coins, last_updated)
                VALUES ($1, $2, GREATEST($3, 0), GREATEST($4, 0), NOW())
                ON CONFLICT (user_id) DO UPDATE
                SET username = EXCLUDED.username,
                    total_xp = GREATEST(users_global.total_xp + EXCLUDED.total_xp, 0),
                    total_coins = GREATEST(users_global.total_coins + EXCLUDED.total_coins, 0),
                    last_updated = NOW()
                """,
                user_id, username, xp_delta, coins_delta,
            )

    async def get_global_leaderboard(self, limit: int = 10) -> List[Dict[str, Any]]:
        async with self.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT user_id, username, total_xp, total_coins, (total_xp / $1)::int as level
                FROM users_global
                ORDER BY total_xp DESC
                LIMIT $2
                """,
                config.XP_PER_LEVEL, limit,
            )
            return [dict(r) for r in rows]

    async def get_riches_leaderboard(self, limit: int = 10) -> List[Dict[str, Any]]:
        async with self.acquire() as conn:
            rows = await conn.fetch(
                "SELECT user_id, username, total_coins FROM users_global ORDER BY total_coins DESC LIMIT $1",
                limit,
            )
            return [dict(r) for r in rows]

    async def get_user_total_messages(self, user_id: int) -> int:
        async with self.acquire() as conn:
            result = await conn.fetchval(
                "SELECT COALESCE(SUM(msg_count), 0) FROM users_per_group WHERE user_id = $1", user_id
            )
            return result or 0

    async def get_all_user_ids(self) -> List[int]:
        async with self.acquire() as conn:
            rows = await conn.fetch("SELECT user_id FROM users_global")
            return [r["user_id"] for r in rows]

    async def get_global_rank_position(self, user_id: int, by: str = "xp") -> Dict[str, int]:
        """{pos, total} in the global leaderboard — {"pos": 0} when unranked."""
        col = "total_xp" if by == "xp" else "total_coins"
        async with self.acquire() as conn:
            me = await conn.fetchval(f"SELECT {col} FROM users_global WHERE user_id = $1", user_id)
            if me is None:
                return {"pos": 0, "total": 0}
            ahead = await conn.fetchval(f"SELECT COUNT(*) FROM users_global WHERE {col} > $1", me)
            total = await conn.fetchval("SELECT COUNT(*) FROM users_global")
            return {"pos": ahead + 1, "total": total}

    # ==================== USERS PER GROUP ====================
    async def get_user_per_group(self, user_id: int, chat_id: int) -> Optional[Dict[str, Any]]:
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM users_per_group WHERE user_id = $1 AND chat_id = $2", user_id, chat_id
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
        streak: Optional[int] = None,
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
            if streak is not None:
                set_clauses.append("daily_streak = $12")

            query = f"""
                INSERT INTO users_per_group (
                    user_id, chat_id, username,
                    xp, coins, msg_count,
                    shield_expiry, is_dead, is_verified_owner,
                    last_daily, last_scratch, daily_streak
                )
                VALUES (
                    $1, $2, $3,
                    GREATEST($4, 0), GREATEST($5, 0), CASE WHEN $9::bool THEN 1 ELSE 0 END,
                    $6, COALESCE($7, FALSE), COALESCE($8, 0),
                    CASE WHEN $10::bool THEN NOW() ELSE NULL END,
                    CASE WHEN $11::bool THEN NOW() ELSE NULL END,
                    COALESCE($12, 0)
                )
                ON CONFLICT (user_id, chat_id) DO UPDATE
                SET {", ".join(set_clauses)}
            """
            await conn.execute(
                query,
                user_id, chat_id, username,
                xp_delta, coins_delta, shield_expiry, set_dead, is_verified_owner,
                msg_inc, last_daily, last_scratch, streak,
            )

    async def get_group_leaderboard(self, chat_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        async with self.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT user_id, username, xp, (xp / $1)::int as level
                FROM users_per_group
                WHERE chat_id = $2
                ORDER BY xp DESC
                LIMIT $3
                """,
                config.XP_PER_LEVEL, chat_id, limit,
            )
            return [dict(r) for r in rows]

    async def get_group_riches(self, chat_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        async with self.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT user_id, username, coins FROM users_per_group
                WHERE chat_id = $1 ORDER BY coins DESC LIMIT $2
                """,
                chat_id, limit,
            )
            return [dict(r) for r in rows]

    async def get_group_rank_position(self, user_id: int, chat_id: int) -> Dict[str, int]:
        async with self.acquire() as conn:
            me = await conn.fetchval(
                "SELECT xp FROM users_per_group WHERE user_id = $1 AND chat_id = $2", user_id, chat_id
            )
            if me is None:
                return {"pos": 0, "total": 0}
            ahead = await conn.fetchval(
                "SELECT COUNT(*) FROM users_per_group WHERE chat_id = $1 AND xp > $2", chat_id, me
            )
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM users_per_group WHERE chat_id = $1", chat_id
            )
            return {"pos": ahead + 1, "total": total}

    async def find_user_by_username(self, chat_id: int, username: str) -> Optional[int]:
        clean_name = username.lstrip("@").strip()
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT user_id FROM users_per_group
                WHERE chat_id = $1 AND (LOWER(username) = LOWER($2) OR LOWER(username) = LOWER($3)) LIMIT 1
                """,
                chat_id, clean_name, f"@{clean_name}",
            )
            if not row:
                row = await conn.fetchrow(
                    """
                    SELECT user_id FROM users_global
                    WHERE LOWER(username) = LOWER($1) OR LOWER(username) = LOWER($2) LIMIT 1
                    """,
                    clean_name, f"@{clean_name}",
                )
            return row["user_id"] if row else None

    async def get_user_chat_ids(self, user_id: int) -> List[int]:
        async with self.acquire() as conn:
            rows = await conn.fetch(
                "SELECT DISTINCT chat_id FROM users_per_group WHERE user_id = $1", user_id
            )
            return [r["chat_id"] for r in rows]

    # ==================== ATOMIC TRANSFERS ====================
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
                from_user_id, chat_id,
            )
            if not sender:
                return False, "Sender not found in this group."
            if sender["coins"] < amount:
                return False, f"Insufficient coins. You have {format_number(sender['coins'])}."

            await conn.execute(
                "UPDATE users_per_group SET coins = coins - $1 WHERE user_id = $2 AND chat_id = $3",
                amount, from_user_id, chat_id,
            )
            await conn.execute(
                """
                INSERT INTO users_per_group (user_id, chat_id, username, coins)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (user_id, chat_id) DO UPDATE
                SET coins = users_per_group.coins + EXCLUDED.coins,
                    username = EXCLUDED.username
                """,
                to_user_id, chat_id, to_username, amount,
            )
            await conn.execute(
                """
                INSERT INTO users_global (user_id, username, total_coins)
                VALUES ($1, $2, 0)
                ON CONFLICT (user_id) DO UPDATE
                SET total_coins = GREATEST(users_global.total_coins - $3, 0),
                    username = EXCLUDED.username
                """,
                from_user_id, from_username, amount,
            )
            await conn.execute(
                """
                INSERT INTO users_global (user_id, username, total_coins)
                VALUES ($1, $2, $3)
                ON CONFLICT (user_id) DO UPDATE
                SET total_coins = users_global.total_coins + EXCLUDED.total_coins,
                    username = EXCLUDED.username
                """,
                to_user_id, to_username, amount,
            )
            return True, "Transfer successful"

    # ==================== GIFTS ====================
    async def add_gift(self, from_user: int, to_user: int, chat_id: int, gift_type: str, amount: int) -> None:
        async with self.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO gifts (from_user, to_user, chat_id, gift_type, amount, created_at)
                VALUES ($1, $2, $3, $4, $5, NOW())
                """,
                from_user, to_user, chat_id, gift_type, amount,
            )

    async def get_gifts(self, user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        async with self.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM gifts WHERE to_user = $1 ORDER BY created_at DESC LIMIT $2", user_id, limit
            )
            return [dict(r) for r in rows]

    # ==================== GROUPS ====================
    async def add_group(self, chat_id: int, title: str, username: Optional[str], invite_link: Optional[str]) -> None:
        async with self.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO groups (chat_id, title, username, invite_link, added_on)
                VALUES ($1, $2, $3, $4, NOW())
                ON CONFLICT (chat_id) DO UPDATE
                SET title = EXCLUDED.title,
                    username = EXCLUDED.username,
                    invite_link = EXCLUDED.invite_link
                """,
                chat_id, title, username, invite_link,
            )

    async def remove_group(self, chat_id: int) -> None:
        async with self.acquire() as conn:
            await conn.execute("DELETE FROM groups WHERE chat_id = $1", chat_id)

    async def get_all_groups(self) -> List[Dict[str, Any]]:
        async with self.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM groups ORDER BY added_on DESC")
            return [dict(r) for r in rows]

    async def get_group_stats(self, chat_id: int) -> Dict[str, Any]:
        async with self.acquire() as conn:
            top_user = await conn.fetchrow(
                "SELECT username, xp FROM users_per_group WHERE chat_id = $1 ORDER BY xp DESC LIMIT 1", chat_id
            )
            user_count = await conn.fetchval(
                "SELECT COUNT(*) FROM users_per_group WHERE chat_id = $1", chat_id
            )
            total_msgs = await conn.fetchval(
                "SELECT COALESCE(SUM(msg_count),0) FROM users_per_group WHERE chat_id = $1", chat_id
            )
            return {
                "top_user": dict(top_user) if top_user else None,
                "user_count": user_count or 0,
                "total_msgs": total_msgs or 0,
            }

    # ==================== GUILDS ====================
    async def create_guild(self, name: str, creator_id: Optional[int] = None) -> int:
        async with self.transaction() as conn:
            count = await conn.fetchval("SELECT COUNT(*) FROM guilds")
            if count >= config.MAX_GUILDS:
                raise ValueError(f"Maximum guilds ({config.MAX_GUILDS}) reached.")
            try:
                guild_id = await conn.fetchval(
                    "INSERT INTO guilds (name, owner_id) VALUES ($1, $2) RETURNING guild_id",
                    name, creator_id,
                )
            except asyncpg.UniqueViolationError:
                raise ValueError("A guild with that name already exists.") from None
            logger.info(f"Guild created: {name} (ID: {guild_id}) by user {creator_id}")
            return guild_id

    async def delete_guild(self, guild_id: int, admin_id: Optional[int] = None) -> None:
        async with self.acquire() as conn:
            guild = await self.get_guild_by_id(guild_id)
            name = guild["name"] if guild else "Unknown"
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
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT g.* FROM guilds g
                JOIN guild_members gm ON g.guild_id = gm.guild_id
                WHERE gm.user_id = $1
                """,
                user_id,
            )
            return dict(row) if row else None

    async def add_user_to_guild(self, user_id: int, guild_id: int, username: str) -> Tuple[bool, str]:
        async with self.transaction() as conn:
            guild = await conn.fetchrow("SELECT * FROM guilds WHERE guild_id = $1 FOR UPDATE", guild_id)
            if not guild:
                return False, "Guild does not exist."
            if guild["member_count"] >= config.MAX_GUILD_MEMBERS:
                return False, f"Guild is full (max {config.MAX_GUILD_MEMBERS} members)."
            existing = await conn.fetchval("SELECT 1 FROM guild_members WHERE user_id = $1", user_id)
            if existing:
                return False, "You are already in a guild."
            cooldown_row = await conn.fetchrow(
                "SELECT left_at FROM guild_leave_cooldown WHERE user_id = $1", user_id
            )
            if cooldown_row:
                left_at = localize(cooldown_row["left_at"])
                now = utcnow()
                if (now - left_at).total_seconds() < config.GUILD_REJOIN_COOLDOWN:
                    remaining = config.GUILD_REJOIN_COOLDOWN - int((now - left_at).total_seconds())
                    hours = remaining // 3600
                    minutes = (remaining % 3600) // 60
                    return False, f"You must wait {hours}h {minutes}m before joining another guild."
            await conn.execute(
                "INSERT INTO guild_members (user_id, guild_id, contribution_xp) VALUES ($1, $2, 0)",
                user_id, guild_id,
            )
            await conn.execute(
                "UPDATE guilds SET member_count = member_count + 1 WHERE guild_id = $1", guild_id
            )
            await conn.execute("DELETE FROM guild_leave_cooldown WHERE user_id = $1", user_id)
            logger.info(f"User {user_id} joined guild {guild_id}")
            return True, "Successfully joined the guild."

    async def remove_user_from_guild(self, user_id: int) -> Tuple[bool, str]:
        async with self.transaction() as conn:
            guild_id = await conn.fetchval("SELECT guild_id FROM guild_members WHERE user_id = $1", user_id)
            if not guild_id:
                return False, "You are not in any guild."
            await conn.execute("DELETE FROM guild_members WHERE user_id = $1", user_id)
            await conn.execute(
                "UPDATE guilds SET member_count = GREATEST(member_count - 1, 0) WHERE guild_id = $1", guild_id
            )
            await conn.execute(
                """
                INSERT INTO guild_leave_cooldown (user_id, left_at)
                VALUES ($1, NOW())
                ON CONFLICT (user_id) DO UPDATE SET left_at = NOW()
                """,
                user_id,
            )
            logger.info(f"User {user_id} left guild {guild_id}")
            return True, "You have left the guild."

    async def add_guild_xp(self, guild_id: int, xp: int, user_id: Optional[int] = None) -> None:
        async with self.transaction() as conn:
            await conn.execute("UPDATE guilds SET total_xp = total_xp + $1 WHERE guild_id = $2", xp, guild_id)
            if user_id:
                await conn.execute(
                    "UPDATE guild_members SET contribution_xp = contribution_xp + $1 WHERE user_id = $2 AND guild_id = $3",
                    xp, user_id, guild_id,
                )

    async def add_guild_xp_for_user(self, user_id: int, xp: int) -> None:
        guild = await self.get_user_guild(user_id)
        if guild:
            await self.add_guild_xp(guild["guild_id"], xp, user_id)

    async def get_guild_leaderboard(self, limit: int = 10) -> List[Dict[str, Any]]:
        async with self.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT name, total_xp, member_count,
                       (SELECT COUNT(*) FROM guild_members gm WHERE gm.guild_id = g.guild_id) as members
                FROM guilds g
                ORDER BY total_xp DESC
                LIMIT $1
                """,
                limit,
            )
            result = []
            for r in rows:
                d = dict(r)
                d["level"] = self.calculate_guild_level(d["total_xp"])
                result.append(d)
            return result

    async def get_guild_members(self, guild_id: int) -> List[Dict[str, Any]]:
        async with self.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT gm.user_id, gm.joined_at, gm.contribution_xp,
                       COALESCE(ug.username, 'Unknown') as username
                FROM guild_members gm
                LEFT JOIN users_global ug ON gm.user_id = ug.user_id
                WHERE gm.guild_id = $1
                ORDER BY gm.contribution_xp DESC
                """,
                guild_id,
            )
            return [dict(r) for r in rows]

    @staticmethod
    def calculate_guild_level(total_xp: int) -> int:
        level = 1
        for i, thresh in enumerate(config.GUILD_LEVEL_THRESHOLDS[1:], start=2):
            if total_xp >= thresh:
                level = i
            else:
                break
        return level

    @staticmethod
    def guild_next_level(total_xp: int) -> Tuple[int, int]:
        """(current level, xp needed for next threshold) — 0 when maxed."""
        level = DatabaseService.calculate_guild_level(total_xp)
        for thresh in config.GUILD_LEVEL_THRESHOLDS[1:]:
            if total_xp < thresh:
                return level, thresh - total_xp
        return level, 0


db = DatabaseService()
