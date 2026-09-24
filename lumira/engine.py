"""LiveView — the smooth message engine.

One message that *morphs* instead of spamming new ones:

  • open(label)         → placeholder with an animated braille spinner
  • show(screen, ...)   → edit in place (rich 10.1 first, classic fallback)
  • animate(frames)     → multi-frame transitions (scratch reveal, lottery…)
  • type_stream(gen)    → typewriter streaming for AI answers
                           (DM: native sendMessageDraft; groups: throttled edits)

Every edit path degrades gracefully: rich → classic → plain → resend.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import AsyncGenerator, Callable, Optional, Sequence, Union

from telegram import Bot, Chat, InlineKeyboardMarkup, Message, Update
from telegram.constants import ChatAction
from telegram.error import BadRequest, Forbidden

from . import config, tgapi
from .rich import Screen
from .utils import logger

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
LOADING_LINE = "⣿ Generating…"  # close enough visually in every client

FrameT = Union[Screen, str]


def _frame_screen(frame: FrameT) -> Screen:
    if isinstance(frame, Screen):
        return frame
    s = Screen("")
    s.p(frame)
    return s


class LiveView:
    """Attach to a bot message and keep editing it smoothly."""

    def __init__(
        self,
        bot: Bot,
        chat_id: int,
        *,
        message: Optional[Message] = None,
        reply_to_message_id: Optional[int] = None,
        ephemeral_user_id: Optional[int] = None,
    ) -> None:
        self.bot = bot
        self.chat_id = chat_id
        self.message = message
        self.reply_to_message_id = reply_to_message_id
        self.ephemeral_user_id = ephemeral_user_id
        self.ephemeral_id: Optional[int] = None
        self._last_edit = 0.0
        self._rich_hint: Optional[bool] = None  # last successful path

    # ------------------------------------------------------------------ ctors
    @classmethod
    def from_update(cls, update: Update) -> "LiveView":
        bot = update.get_bot()
        msg = update.effective_message
        chat = update.effective_chat
        return cls(
            bot,
            chat.id,
            reply_to_message_id=msg.message_id if msg else None,
        )

    @classmethod
    def from_query(cls, query) -> "LiveView":
        """LiveView bound to an inline-button callback — edits the message
        the button lives on (the classic 'tab switch' feel)."""
        return cls(
            query.get_bot(),
            chat_id=query.message.chat_id,
            message=query.message,
        )

    # --------------------------------------------------------------- helpers
    @property
    def has_target(self) -> bool:
        return bool(self.message or self.ephemeral_id)

    async def _throttle(self, min_gap: float = config.EDIT_MIN_INTERVAL) -> None:
        delta = time.monotonic() - self._last_edit
        if delta < min_gap:
            await asyncio.sleep(min_gap - delta)
        self._last_edit = time.monotonic()

    async def _safe_delete(self, msg: Optional[Message]) -> None:
        if not msg:
            return
        try:
            await msg.delete()
        except Exception as e:
            logger.debug(f"delete failed: {e}")

    # ------------------------------------------------------------------- open
    async def open(self, label: str = "Loading") -> "LiveView":
        """Send the animated placeholder we will keep editing."""
        if self.ephemeral_user_id:
            raw = await tgapi.send_ephemeral(
                self.bot,
                self.chat_id,
                self.ephemeral_user_id,
                f"⠋ <i>{label}…</i>",
                reply_to_message_id=self.reply_to_message_id,
            )
            if raw:
                self.ephemeral_id = raw.get("ephemeral_message_id") or raw.get("message_id")
                return self
            self.ephemeral_user_id = None  # fall through to public flow
        self.message = await self.bot.send_message(
            chat_id=self.chat_id,
            text=f"⠋ <i>{label}…</i>",
            parse_mode="HTML",
            reply_to_message_id=self.reply_to_message_id,
            allow_sending_without_reply=True,
        )
        return self

    # ------------------------------------------------------------------- show
    async def show(
        self,
        frame: FrameT,
        *,
        markup: Optional[InlineKeyboardMarkup] = None,
        prefer_rich: bool = True,
        effect: Optional[str] = None,
        force_new: bool = False,
    ) -> Optional[Message]:
        """Render *frame* onto this view's message (or send if none)."""
        screen = _frame_screen(frame)

        # Ephemeral path ------------------------------------------------------
        if self.ephemeral_id:
            ok = await tgapi.edit_ephemeral(
                self.bot, self.chat_id, self.ephemeral_id, screen.classic_html(), reply_markup=markup
            )
            if ok:
                return None
            self.ephemeral_id = None
            self.ephemeral_user_id = None  # degrade to public

        # Build payloads -------------------------------------------------------
        rich_html = screen.rich_html() if prefer_rich else None
        classic_html = screen.classic_html()

        try:
            if self.message and not force_new:
                await self._throttle()
                if rich_html:
                    try:
                        if await tgapi.edit_rich(self.bot, self.chat_id, self.message.message_id, rich_html, reply_markup=markup):
                            return self.message
                    except Exception as e:
                        logger.debug(f"rich edit failed: {e}")
                try:
                    result = await self.bot.edit_message_text(
                        chat_id=self.chat_id,
                        message_id=self.message.message_id,
                        text=classic_html,
                        parse_mode="HTML",
                        reply_markup=markup,
                        disable_web_page_preview=True,
                    )
                    if isinstance(result, Message):
                        self.message = result
                    return self.message
                except BadRequest as e:
                    low = str(e).lower()
                    if "not modified" in low:
                        return self.message
                    if "message to edit not found" in low or "message not found" in low:
                        pass  # fall through to send
                    else:
                        raise
            # Send path --------------------------------------------------------
            if rich_html:
                try:
                    raw = await tgapi.send_rich(
                        self.bot,
                        self.chat_id,
                        rich_html,
                        reply_markup=markup,
                        effect=effect,
                        reply_to_message_id=self.reply_to_message_id,
                    )
                    if raw and raw.get("message_id"):
                        chat = raw.get("chat") or {}
                        self.message = Message(
                            message_id=raw["message_id"],
                            date=datetime.fromtimestamp(raw.get("date", 0), tz=config.IST),
                            chat=Chat(chat.get("id", self.chat_id), chat.get("type", "private")),
                        )
                        self.message.set_bot(self.bot)
                        return self.message
                except Exception as e:
                    logger.debug(f"rich send failed: {e}")
            self.message = await self.bot.send_message(
                chat_id=self.chat_id,
                text=classic_html,
                parse_mode="HTML",
                reply_markup=markup,
                reply_to_message_id=self.reply_to_message_id,
                allow_sending_without_reply=True,
                message_effect_id=tgapi.effect_or_none(effect),
                disable_web_page_preview=True,
            )
            return self.message
        except Forbidden:
            return self.message

    # ---------------------------------------------------------------- animate
    async def animate(
        self,
        frames: Sequence[FrameT],
        *,
        interval: float = 0.55,
        markup: Optional[InlineKeyboardMarkup] = None,
        effect: Optional[str] = None,
        last_only_markup: bool = True,
    ) -> Optional[Message]:
        """Play a short animation (progressively-edited frames)."""
        result: Optional[Message] = None
        total = len(frames)
        for i, frame in enumerate(frames):
            last = i == total - 1
            result = await self.show(
                frame,
                markup=None if (last_only_markup and not last) else markup,
                effect=effect if last else None,
            )
            if not last:
                await asyncio.sleep(max(interval, config.EDIT_MIN_INTERVAL))
        return result

    # ------------------------------------------------- streaming / typewriter
    async def type_stream(
        self,
        chunk_iter: AsyncGenerator[str, None],
        *,
        title: str,
        header_html: str = "",
        footer_html: str = "",
        markup: Optional[InlineKeyboardMarkup] = None,
        effect: Optional[str] = None,
        draft: bool = False,
        interval: float = 1.15,
        chunk_size: int = 600,
        render: Optional[Callable[[str], str]] = None,
    ) -> str:
        """Stream a growing text into this view.

        draft=True → use native sendMessageDraft when in a private chat; the
        final body is then sent/edited as a real message.
        Returns the full final text.
        """
        from .utils import md_to_html

        render = render or md_to_html
        acc = ""
        cursor = " ▌"
        last_push = 0.0
        draft_id = int(time.time() * 1000) % 2000000000 or 1
        use_draft = draft and self.message is None

        async def push(text_html: str, final: bool = False) -> None:
            body = f"{header_html}\n{text_html}\n{footer_html}" if header_html or footer_html else text_html
            if self.message is None:
                msg = await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=f"{body}{'' if final else cursor}",
                    parse_mode="HTML",
                    reply_markup=markup if final else None,
                    reply_to_message_id=self.reply_to_message_id,
                    allow_sending_without_reply=True,
                    message_effect_id=tgapi.effect_or_none(effect) if final else None,
                    disable_web_page_preview=True,
                )
                self.message = msg  # always track — later pushes edit THIS message
            else:
                await self._throttle(0.9)
                cur = "" if final else cursor
                try:
                    res = await self.bot.edit_message_text(
                        chat_id=self.chat_id,
                        message_id=self.message.message_id,
                        text=f"{body}{cur}",
                        parse_mode="HTML",
                        reply_markup=markup if final else None,
                        disable_web_page_preview=True,
                    )
                    if isinstance(res, Message):
                        self.message = res
                except BadRequest as e:
                    if "not modified" not in str(e).lower():
                        raise

        async for piece in chunk_iter:
            acc += piece
            now = time.monotonic()
            if use_draft:
                if now - last_push >= 0.8 and acc.strip():
                    await tgapi.send_draft(self.bot, self.chat_id, draft_id, acc[-3900:] or "…")
                    last_push = now
            elif now - last_push >= interval and len(acc) > 0:
                tail = acc if len(acc) <= chunk_size else "…" + acc[-chunk_size:]
                try:
                    await push(render(tail))
                except Forbidden:
                    pass
                except Exception as e:
                    logger.debug(f"stream push failed: {e}")
                last_push = now

        await push(render(acc), final=True)
        return acc

    # ---------------------------------------------------------------- utility
    async def toast_reaction(self, emoji: str, message_id: Optional[int] = None) -> None:
        """React on a message — cheap dopamine. Auto-safe."""
        mid = message_id or (self.message.message_id if self.message else self.reply_to_message_id)
        if mid:
            await tgapi.react(self.bot, self.chat_id, mid, emoji)


async def typing(bot: Bot, chat_id: int, action: str = ChatAction.TYPING) -> None:
    try:
        await bot.send_chat_action(chat_id=chat_id, action=action)
    except Exception:
        pass
