"""Event pipeline: XP per message, level-up celebrations, welcomes,
bot added/removed tracking, and the pending-action message router."""
from __future__ import annotations

from telegram import Update
from telegram.constants import ChatType, ParseMode
from telegram.ext import ChatMemberHandler, ContextTypes, MessageHandler, filters

from .. import config, keyboards, tgapi
from ..db import db
from ..rich import Screen
from ..utils import get_level_symbol, logger, pending_manager, username_of


# ------------------------------------------------------------------ XP core
async def process_message_xp(user_id: int, username: str, chat_id: int, context: ContextTypes.DEFAULT_TYPE, msg_id: int = 0) -> None:
    old_global = await db.get_user_global(user_id)
    old_level = old_global["total_xp"] // config.XP_PER_LEVEL if old_global else 0

    await db.update_user_per_group(user_id, chat_id, username, xp_delta=config.XP_PER_MESSAGE, msg_inc=True)
    await db.update_user_global(user_id, username, xp_delta=config.XP_PER_MESSAGE)
    await db.add_guild_xp_for_user(user_id, config.GUILD_XP_MESSAGE)

    new_global = await db.get_user_global(user_id)
    new_level = new_global["total_xp"] // config.XP_PER_LEVEL if new_global else 0

    if new_level > old_level:
        await handle_level_up(user_id, username, old_level, new_level, chat_id, context, msg_id)


async def handle_level_up(user_id, username, old_level, new_level, chat_id, context, msg_id: int = 0) -> None:
    symbol = get_level_symbol(new_level)
    capped = min(new_level, config.MAX_LEVEL)
    s = Screen("🎉 𝐋𝐄𝐕𝐄𝐋 𝐔𝐏 !")
    s.p(f"⚡ <b>@{username}</b> has ascended to <b>𝐋𝐞𝐯𝐞𝐥 {capped}</b> (<code>{symbol}</code>)!")
    s.p("Keep chatting and conquering the ranks! 🔥")
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=s.classic_html(),
            parse_mode=ParseMode.HTML,
            message_effect_id=tgapi.effect_or_none("party"),
        )
    except Exception as e:
        logger.error(f"Level-up broadcast failed: {e}")
    if msg_id:
        await tgapi.react(context.bot, chat_id, msg_id, "🔥")

    if new_level >= config.MAX_LEVEL and old_level < config.MAX_LEVEL:
        await broadcast_elite(user_id, username, symbol, context)


async def broadcast_elite(user_id, username, symbol, context) -> None:
    chat_ids = await db.get_user_chat_ids(user_id)
    s = Screen("★ 𝐄𝐋𝐈𝐓𝐄 𝐀𝐂𝐇𝐈𝐄𝐕𝐄𝐃 ★")
    s.p(f"👑 <b>@{username}</b> reached the pinnacle of Lumira: <b>𝐄𝐋𝐈𝐓𝐄 {symbol}</b>!")
    s.p("A historic milestone — everyone pay respects! 🎊")
    for grp_id in chat_ids:
        try:
            await context.bot.send_message(
                chat_id=grp_id,
                text=s.classic_html(),
                parse_mode=ParseMode.HTML,
                message_effect_id=tgapi.effect_or_none("fire"),
            )
        except Exception:
            pass


# ------------------------------------------------------------ message router
async def on_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return
    if update.message.text and update.message.text.startswith("/"):
        return
    if update.effective_chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    if not update.effective_user:
        return

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    username = username_of(update.effective_user)

    pending = await pending_manager.get(chat_id, user_id)
    if pending and pending.get("action") in ("addcoins", "removecoins"):
        from .admin import handle_coin_pending

        await handle_coin_pending(update, pending)
        return

    if update.message.text:
        await process_message_xp(user_id, username, chat_id, context, update.message.message_id)


# ------------------------------------------------------------------ welcomes
async def welcome_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.new_chat_members:
        return
    chat = update.effective_chat
    for new_user in update.message.new_chat_members:
        if new_user.id == context.bot.id:
            continue
        username = username_of(new_user)
        await db.update_user_global(new_user.id, username)
        await db.update_user_per_group(new_user.id, chat.id, username, msg_inc=False)

        s = Screen("🌟 𝐍𝐄𝐖 𝐌𝐄𝐌𝐁𝐄𝐑 𝐀𝐑𝐑𝐈𝐕𝐀𝐋 🌟")
        s.p(f"✨ Welcome, <b>{new_user.first_name}</b>, to <b>{chat.title}</b>!")
        s.quote("Chat to earn XP & Coins automatically — level up, buy shields, join a guild, and don't forget your free /daily starter reward!", cite="𝓛𝓾𝓶𝓲𝓻𝓪")
        try:
            await update.message.reply_text(
                s.classic_html(),
                reply_markup=keyboards.welcome_group(context.bot.username),
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logger.warning(f"welcome send failed: {e}")


# ------------------------------------------------------------ membership log
async def track_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    result = update.my_chat_member
    if not result:
        return
    chat = result.chat
    user = result.from_user
    new_status = result.new_chat_member.status if result.new_chat_member else None
    old_status = result.old_chat_member.status if result.old_chat_member else None

    if new_status == "member" and old_status == "left":
        await db.add_group(chat.id, chat.title, chat.username, chat.invite_link)
        await db.update_user_per_group(user.id, chat.id, username_of(user), is_verified_owner=1)

        s = Screen("𝓛𝓤𝓜𝓘𝓡𝓐 • 𝐆𝐑𝐎𝐔𝐏 𝐀𝐂𝐓𝐈𝐕𝐀𝐓𝐈𝐎𝐍")
        s.p(f"🌟 <b>𝓛𝓾𝓶𝓲𝓻𝓪 v4 has arrived in {chat.title}!</b>")
        s.kv([("👑 Group owner registered", f"{user.first_name} (<code>{user.id}</code>)")])
        s.h("⚡ Enabled Systems", 2)
        s.items(
            [
                ("📈", f"Auto XP & Levels (+{config.XP_PER_MESSAGE} XP/msg)"),
                ("💰", "Daily rewards + streaks + scratch cards"),
                ("🎰", "Casino slots & shop & shields"),
                ("🏰", "Guild wars & global leaderboards"),
                ("🤖", "Streaming AI (<code>/ai</code>, <code>/roast</code>)"),
            ],
            checked=[True] * 5,
        )
        s.p("💡 <i>Promote me to Administrator for maximum speed & protection!</i>")
        try:
            await context.bot.send_message(
                chat.id,
                text=s.classic_html(),
                reply_markup=keyboards.activation(context.bot.username),
                parse_mode=ParseMode.HTML,
                message_effect_id=tgapi.effect_or_none("party"),
            )
        except Exception as e:
            logger.warning(f"activation message failed: {e}")
        logger.info(f"Bot added to group {chat.id} ({chat.title}) by {user.id}")

    elif new_status == "left" and old_status == "member":
        await db.remove_group(chat.id)
        logger.info(f"Bot removed from group {chat.id}")


def register(application) -> None:
    application.add_handler(
        MessageHandler(filters.TEXT & filters.ChatType.GROUPS & ~filters.COMMAND, on_group_message),
        group=2,
    )
    application.add_handler(ChatMemberHandler(track_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_members))
