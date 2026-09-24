"""Shared handler helpers: owner verification, target resolution."""
from __future__ import annotations

from typing import Optional, Tuple

from telegram import Update, User
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from .. import config
from ..db import db
from ..utils import border_text, logger


async def is_owner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Global Master or a verified-in-group owner."""
    if not update.effective_user:
        return False
    user_id = update.effective_user.id
    if user_id == config.GLOBAL_OWNER_ID:
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
            parse_mode=ParseMode.HTML,
        )
        return False
    return True


async def resolve_target_user(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> Tuple[Optional[User], Optional[str], Optional[int]]:
    """Resolve a target from reply-to-message or @username arg.

    Returns (user_obj_or_None, display_name, user_id_or_None).
    """
    chat_id = update.effective_chat.id
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        tu = update.message.reply_to_message.from_user
        name = tu.username or tu.first_name
        return tu, name, tu.id
    if context.args:
        target_name = context.args[0].lstrip("@")
        target_id = await db.find_user_by_username(chat_id, target_name)
        if target_id:
            try:
                member = await context.bot.get_chat_member(chat_id, target_id)
                return member.user, target_name, target_id
            except Exception:
                pass
        return None, target_name, target_id
    return None, None, None


def has_active_shield(user_data) -> bool:
    from ..utils import localize, utcnow

    if not user_data:
        return False
    shield_expiry = localize(user_data.get("shield_expiry"))
    if not shield_expiry:
        return False
    return shield_expiry > utcnow()
