"""Shared utilities: formatting, rate limiting, pending states, decorators."""
from __future__ import annotations

import asyncio
import html
import logging
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from telegram import Update
from telegram.constants import ChatType, ParseMode
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

from . import config

# ----------------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("LUMIRA")


# ----------------------------------------------------------------------------
# Formatting helpers (classic look — kept from v3, still used as fallback UI)
# ----------------------------------------------------------------------------
def get_level_symbol(level: int) -> str:
    for low, high, sym in config.LEVEL_SYMBOLS:
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


def esc(text: Any) -> str:
    """HTML-escape for Telegram HTML parse mode."""
    return html.escape(str(text), quote=False)


def md_to_html(text: str) -> str:
    """Tiny markdown-ish → Telegram HTML converter for AI output.

    Escapes first, then re-opens a safe subset: **b**, *i*, `code`,
    ```code blocks```, ## headings. Everything else stays literal text.
    """
    if not text:
        return ""
    chunks: List[str] = []
    # fenced code blocks first
    fence_re = re.compile(r"```(?:\w+)?\n(.*?)```", re.S)
    fences: Dict[str, str] = {}
    def _stash(m: re.Match) -> str:
        key = f"\x00F{len(fences)}\x00"
        fences[key] = f"<pre><code>{html.escape(m.group(1))}</code></pre>"
        return key
    work = fence_re.sub(_stash, text)
    work = html.escape(work)
    work = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", work)
    work = re.sub(r"(?<!\*)\*(?!\*)([^*]+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", work)
    work = re.sub(r"`([^`]+?)`", r"<code>\1</code>", work)
    work = re.sub(r"^#{1,3}\s*(.+)$", r"<b>\1</b>", work, flags=re.M)
    for key, value in fences.items():
        escaped_key = html.escape(key)
        work = work.replace(escaped_key, value).replace(key, value)
    chunks.append(work)
    return "".join(chunks)


def human_delta(seconds: Union[int, float]) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if h:
        parts.append(f"{h}h")
    if m or h:
        parts.append(f"{m}m")
    if not h:
        parts.append(f"{s}s")
    return " ".join(parts)


def username_of(user) -> str:
    return getattr(user, "username", None) or getattr(user, "first_name", None) or "Unknown"


def mention_html(user_id: int, name: str) -> str:
    """Clickable mention that works even for users without @username (+free)."""
    return f'<a href="tg://user?id={user_id}">{esc(name)}</a>'


def utcnow() -> datetime:
    return datetime.now(config.IST)


def localize(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return config.IST.localize(dt)
    return dt


# ----------------------------------------------------------------------------
# Rate limiting (per user, per command)
# ----------------------------------------------------------------------------
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
        now = utcnow()
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


rate_limiter = RateLimiter(max_requests=config.RATE_LIMIT_MAX, window_seconds=config.RATE_LIMIT_WINDOW)
broadcast_rate_limiter = RateLimiter(
    max_requests=config.BROADCAST_RATE_LIMIT_MAX, window_seconds=config.BROADCAST_RATE_LIMIT_WINDOW
)


class Cooldown:
    """Simple per-user cooldown (seconds) for heavy game actions."""

    def __init__(self):
        self._store: Dict[Tuple[int, str], datetime] = {}
        self._lock = asyncio.Lock()

    async def check(self, user_id: int, action: str, seconds: int) -> Tuple[bool, int]:
        async with self._lock:
            now = utcnow()
            last = self._store.get((user_id, action))
            if last:
                elapsed = (now - last).total_seconds()
                if elapsed < seconds:
                    return False, int(seconds - elapsed) + 1
            self._store[(user_id, action)] = now
            return True, 0


cooldowns = Cooldown()


# ----------------------------------------------------------------------------
# Pending state manager (multi-step input flows)
# ----------------------------------------------------------------------------
class PendingStateManager:
    """Async-safe pending-action manager with expiry, cleanup & size limit."""

    def __init__(self, expiry_seconds: int = 300, max_size: int = config.PENDING_MAX_SIZE):
        self._storage: Dict[int, Dict[int, Dict[str, Any]]] = {}
        self._expiry: Dict[int, Dict[int, datetime]] = {}
        self._lock = asyncio.Lock()
        self._expiry_seconds = expiry_seconds
        self._max_size = max_size

    async def cleanup_pass(self) -> None:
        now = utcnow()
        async with self._lock:
            for chat_id in list(self._expiry):
                for user_id in list(self._expiry[chat_id]):
                    if now > self._expiry[chat_id][user_id]:
                        self._storage[chat_id].pop(user_id, None)
                        self._expiry[chat_id].pop(user_id, None)
                if not self._expiry.get(chat_id):
                    self._expiry.pop(chat_id, None)
                    self._storage.pop(chat_id, None)

    async def set(self, chat_id: int, user_id: int, data: Dict[str, Any]) -> bool:
        async with self._lock:
            total = sum(len(users) for users in self._storage.values())
            if total >= self._max_size:
                logger.warning("PendingStateManager full — rejecting entry")
                return False
            self._storage.setdefault(chat_id, {})
            self._expiry.setdefault(chat_id, {})
            self._storage[chat_id][user_id] = data
            self._expiry[chat_id][user_id] = utcnow() + timedelta(seconds=self._expiry_seconds)
            return True

    async def get(self, chat_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        async with self._lock:
            if chat_id not in self._storage:
                return None
            expiry = self._expiry.get(chat_id, {}).get(user_id)
            if expiry and utcnow() > expiry:
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


# ----------------------------------------------------------------------------
# Decorators
# ----------------------------------------------------------------------------
def require_group(func: Callable) -> Callable:
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if not update.effective_chat:
            return
        if update.effective_chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
            await update.message.reply_text(
                border_text("𝐍𝐎𝐓𝐈𝐂𝐄", "❌ This command can only be used inside Telegram Groups or Supergroups."),
                parse_mode=ParseMode.HTML,
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
                    border_text(
                        "⏳ 𝐑𝐀𝐓𝐄 𝐋𝐈𝐌𝐈𝐓",
                        f"Please wait <b>{remaining}s</b> before using <code>/{command_name}</code> again.",
                    ),
                    parse_mode=ParseMode.HTML,
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
        except (BadRequest, Forbidden) as e:
            if "not modified" in str(e).lower():
                return
            logger.debug(f"Telegram error in {func.__name__}: {e}")
        except Exception:
            logger.exception(f"Error in {func.__name__}")
            try:
                if update and update.effective_message:
                    await update.effective_message.reply_text(
                        border_text(
                            "❌ 𝐄𝐑𝐑𝐎𝐑",
                            "An internal error occurred while processing your request. Please try again soon.",
                        ),
                        parse_mode=ParseMode.HTML,
                    )
            except Exception:
                pass
    return wrapper
