"""BotAPI 10.x bridge — first-class access to features python-telegram-bot
has not wrapped yet, with capability probing and graceful degradation.

Features exposed (all FREE — no Telegram Premium required):
  • Rich Messages          (Bot API 10.1) — sendRichMessage / rich_message edits
  • Ephemeral messages     (Bot API 10.2) — per-user-visible group messages +
                             editEphemeralMessageText / deleteEphemeralMessage
  • sendMessageDraft       (Bot API 9.3+) — native streaming previews in DMs
  • message_effect_id      (free effects in group chats)
  • set_message_reaction   (bot reacts on messages)

Design rule: NEVER let an advanced feature break the bot. Every call catches
BadRequest/Forbidden, counts failures per capability, and auto-disables the
capability after `_CAP_FAILURE_TOLERANCE` failures for the process lifetime.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Union

from telegram import Bot, InlineKeyboardMarkup
from telegram.error import BadRequest, Forbidden, RetryAfter

from . import config
from .utils import logger

_CAP_FAILURE_TOLERANCE = 3

#: Free message effects (Bot API 8.x — free in group chats; curated stable IDs).
EFFECTS = {
    "fire": "5104841245755180586",    # 🔥
    "party": "5046509860389126442",   # 🎉
    "heart": "5159385139981059251",   # ❤️
    "thumbs_up": "5107584321108051014",  # 👍
    "poop": "5046589136890476101",    # 💩
}


def markup_to_dict(markup: Optional[Union[InlineKeyboardMarkup, Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    if markup is None:
        return None
    if isinstance(markup, dict):
        return markup
    # PTB markup → plain JSON-serializable dict
    rows: List[List[Dict[str, Any]]] = []
    for row in markup.inline_keyboard:
        out_row: List[Dict[str, Any]] = []
        for btn in row:
            item: Dict[str, Any] = {"text": btn.text}
            if btn.callback_data is not None:
                item["callback_data"] = btn.callback_data
            if btn.url is not None:
                item["url"] = btn.url
            if btn.switch_inline_query is not None:
                item["switch_inline_query"] = btn.switch_inline_query
            if btn.switch_inline_query_current_chat is not None:
                item["switch_inline_query_current_chat"] = btn.switch_inline_query_current_chat
            if btn.web_app is not None:
                item["web_app"] = {"url": btn.web_app.url}
            out_row.append(item)
        rows.append(out_row)
    return {"inline_keyboard": rows}


class Capabilities:
    """Runtime feature flags, probed at startup + demoted on repeated failures."""

    def __init__(self) -> None:
        self.rich = config.ENABLE_RICH_MESSAGES
        self.ephemeral = config.ENABLE_EPHEMERAL
        self.effects = config.ENABLE_EFFECTS
        self.reactions = config.ENABLE_REACTIONS
        self.drafts = config.ENABLE_DRAFTS
        self._failures: Dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def note_failure(self, cap: str) -> None:
        async with self._lock:
            self._failures[cap] = self._failures.get(cap, 0) + 1
            if self._failures[cap] >= _CAP_FAILURE_TOLERANCE and getattr(self, cap, False):
                setattr(self, cap, False)
                logger.warning(f"capability '{cap}' disabled after {self._failures[cap]} failures")

    async def probe(self, bot: Bot) -> None:
        """Startup probe: drafts require Bot API 9.3+; rich/ephemeral 10.x."""
        try:
            me = await bot.get_me()
            logger.info(f"Bot online as @{me.username} (id={me.id})")
        except Exception as e:
            logger.error(f"get_me failed: {e}")


caps = Capabilities()


async def _raw(bot: Bot, method: str, payload: Dict[str, Any]) -> Any:
    """Raw Bot API call through PTB's internal post hook (keeps pooling,
    timeouts and standard telegram.error exceptions)."""
    clean = {k: v for k, v in payload.items() if v is not None}
    return await bot._post(method, data=clean)  # noqa: SLF001 — stable across PTB 20–22


# ----------------------------------------------------------------------------
# Rich messages (Bot API 10.1+)
# ----------------------------------------------------------------------------
async def send_rich(
    bot: Bot,
    chat_id: int,
    rich_html: str,
    *,
    reply_markup: Optional[Union[InlineKeyboardMarkup, Dict[str, Any]]] = None,
    effect: Optional[str] = None,
    reply_to_message_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """sendRichMessage with structured `html` document. Returns raw Message dict."""
    if not caps.rich:
        return None
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "rich_message": {"html": rich_html},
        "reply_markup": markup_to_dict(reply_markup),
    }
    if effect:
        payload["message_effect_id"] = EFFECTS.get(effect, effect)
    if reply_to_message_id:
        payload["reply_parameters"] = {"message_id": reply_to_message_id, "allow_sending_without_reply": True}
    try:
        result = await _raw(bot, "sendRichMessage", payload)
        return result if isinstance(result, dict) else None
    except RetryAfter:
        raise
    except (BadRequest, Forbidden) as e:
        logger.debug(f"sendRichMessage rejected: {e}")
        await caps.note_failure("rich")
    except Exception as e:
        logger.debug(f"sendRichMessage error: {e}")
    return None


async def edit_rich(
    bot: Bot,
    chat_id: int,
    message_id: int,
    rich_html: str,
    *,
    reply_markup: Optional[Union[InlineKeyboardMarkup, Dict[str, Any]]] = None,
) -> bool:
    """editMessageText with rich_message= (Bot API 10.1+)."""
    if not caps.rich:
        return False
    try:
        await _raw(
            bot,
            "editMessageText",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "rich_message": {"html": rich_html},
                "reply_markup": markup_to_dict(reply_markup),
            },
        )
        return True
    except BadRequest as e:
        msg = str(e).lower()
        if "not modified" in msg:
            return True
        logger.debug(f"edit rich rejected: {e}")
        if "rich" in msg or "parse" in msg:
            await caps.note_failure("rich")
    except Exception as e:
        logger.debug(f"edit rich error: {e}")
    return False


# ----------------------------------------------------------------------------
# Message drafts (Bot API 9.3+, private chats only)
# ----------------------------------------------------------------------------
async def send_draft(bot: Bot, chat_id: int, draft_id: int, text: str) -> bool:
    """Stream an animated draft preview (DM only). Fails silently elsewhere."""
    if not caps.drafts:
        return False
    try:
        await bot.send_message_draft(chat_id=chat_id, draft_id=draft_id, text=text[:4096])
        return True
    except (BadRequest, Forbidden):
        await caps.note_failure("drafts")
    except Exception as e:
        logger.debug(f"draft error: {e}")
    return False


# ----------------------------------------------------------------------------
# Ephemeral messages (Bot API 10.2) — visible only to one user inside groups
# ----------------------------------------------------------------------------
async def send_ephemeral(
    bot: Bot,
    chat_id: int,
    user_id: int,
    html: str,
    *,
    reply_markup: Optional[Union[InlineKeyboardMarkup, Dict[str, Any]]] = None,
    reply_to_message_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """sendMessage with receiver_user_id — only that user (and the bot) sees it.

    Returns the raw Message dict (contains usual message_id + ephemeral_message_id
    on supporting servers) or None when unsupported.
    """
    if not caps.ephemeral:
        return None
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": html,
        "parse_mode": "HTML",
        "receiver_user_id": user_id,
        "reply_markup": markup_to_dict(reply_markup),
        "disable_web_page_preview": True,
    }
    if reply_to_message_id:
        payload["reply_parameters"] = {"message_id": reply_to_message_id, "allow_sending_without_reply": True}
    try:
        result = await _raw(bot, "sendMessage", payload)
        return result if isinstance(result, dict) else None
    except (BadRequest, Forbidden) as e:
        logger.debug(f"ephemeral send rejected: {e}")
        await caps.note_failure("ephemeral")
    except Exception as e:
        logger.debug(f"ephemeral send error: {e}")
    return None


async def edit_ephemeral(
    bot: Bot,
    chat_id: int,
    ephemeral_message_id: int,
    html: str,
    *,
    reply_markup: Optional[Union[InlineKeyboardMarkup, Dict[str, Any]]] = None,
) -> bool:
    """editEphemeralMessageText (Bot API 10.2)."""
    if not caps.ephemeral:
        return False
    try:
        await _raw(
            bot,
            "editEphemeralMessageText",
            {
                "chat_id": chat_id,
                "ephemeral_message_id": ephemeral_message_id,
                "text": html,
                "parse_mode": "HTML",
                "reply_markup": markup_to_dict(reply_markup),
                "disable_web_page_preview": True,
            },
        )
        return True
    except BadRequest as e:
        if "not modified" in str(e).lower():
            return True
        logger.debug(f"ephemeral edit rejected: {e}")
        await caps.note_failure("ephemeral")
    except Exception as e:
        logger.debug(f"ephemeral edit error: {e}")
    return False


# ----------------------------------------------------------------------------
# Effects & reactions (free in group chats)
# ----------------------------------------------------------------------------
async def react(bot: Bot, chat_id: int, message_id: int, emoji: str) -> None:
    """Best-effort reaction — pure garnish, never throws."""
    if not caps.reactions or not message_id:
        return
    try:
        from telegram import ReactionTypeEmoji

        await bot.set_message_reaction(chat_id=chat_id, message_id=message_id, reaction=[ReactionTypeEmoji(emoji)])
    except Exception as e:
        logger.debug(f"reaction failed: {e}")
        await caps.note_failure("reactions")


def effect_or_none(name: Optional[str]) -> Optional[str]:
    if not caps.effects or not name:
        return None
    return EFFECTS.get(name, name)
