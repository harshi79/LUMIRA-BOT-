"""Gifts: /gift (reply) + /mygifts — with animated unboxing."""
from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from .. import config, keyboards
from ..db import db
from ..engine import LiveView
from ..rich import Screen
from ..utils import border_text, format_number, pending_manager, require_group, safe_reply, username_of


@safe_reply
@require_group
async def cmd_gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text(
            border_text("𝐆𝐈𝐅𝐓 • 𝐔𝐒𝐀𝐆𝐄", "❌ Reply to a user's message with <code>/gift</code> to send them a gift!"),
            parse_mode=ParseMode.HTML,
        )
        return

    target = update.message.reply_to_message.from_user
    sender = update.effective_user
    chat_id = update.effective_chat.id

    if target.id == sender.id:
        await update.message.reply_text(
            border_text("𝐆𝐈𝐅𝐓 • 𝐍𝐎𝐓𝐈𝐂𝐄", "❌ You cannot gift yourself! Spread the love."),
            parse_mode=ParseMode.HTML,
        )
        return
    if target.is_bot:
        await update.message.reply_text(
            border_text("𝐆𝐈𝐅𝐓 • 𝐍𝐎𝐓𝐈𝐂𝐄", "🤖 Bots appreciate the thought, truly. Gift a human instead!"),
            parse_mode=ParseMode.HTML,
        )
        return

    success = await pending_manager.set(
        chat_id, sender.id, {"action": "gift", "target_id": target.id, "target_name": username_of(target)}
    )
    if not success:
        await update.message.reply_text(
            border_text("𝐆𝐈𝐅𝐓 • 𝐄𝐑𝐑𝐎𝐑", "❌ Too many pending actions. Try again later."),
            parse_mode=ParseMode.HTML,
        )
        return

    s = Screen("𝐆𝐈𝐅𝐓 𝐒𝐄𝐋𝐄𝐂𝐓𝐈𝐎𝐍")
    s.p(f"🎁 Choose a gift for <b>@{username_of(target)}</b>:")
    await update.message.reply_text(
        s.classic_html(), reply_markup=keyboards.gifts(), parse_mode=ParseMode.HTML
    )


@safe_reply
async def cb_gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    _, _, gift_type = (query.data or "").partition(":")

    if gift_type not in config.GIFT_TYPES:
        await query.answer()
        return

    pending = await pending_manager.get(chat_id, user_id)
    if not pending or pending.get("action") != "gift":
        await query.answer("This gift session expired — use /gift again.", show_alert=True)
        return

    target_id = pending["target_id"]
    target_name = pending["target_name"]
    price = config.GIFT_TYPES[gift_type]["price"]
    emoji = config.GIFT_TYPES[gift_type]["emoji"]

    sender_data = await db.get_user_per_group(user_id, chat_id)
    if not sender_data or sender_data["coins"] < price:
        await query.answer(f"Need {price} coins!", show_alert=True)
        view = LiveView.from_query(query)
        s = Screen("𝐆𝐈𝐅𝐓 • 𝐈𝐍𝐒𝐔𝐅𝐅𝐈𝐂𝐈𝐄𝐍𝐓")
        s.kv(
            [
                ("💰 Cost", format_number(price)),
                ("💎 Your balance", format_number(sender_data["coins"] if sender_data else 0)),
            ]
        )
        await view.show(s)
        await pending_manager.delete(chat_id, user_id)
        return

    await db.update_user_per_group(user_id, chat_id, username_of(query.from_user), coins_delta=-price)
    await db.update_user_global(user_id, username_of(query.from_user), coins_delta=-price)
    await db.add_gift(user_id, target_id, chat_id, gift_type, price)
    await db.add_guild_xp_for_user(user_id, config.GUILD_XP_GIFT)
    await pending_manager.delete(chat_id, user_id)

    await query.answer(f"{emoji} Delivered!")
    view = LiveView.from_query(query)
    frames = []
    for step in ("📦 Wrapping…", "🎀 Adding ribbon…", "✨ Delivering…"):
        f = Screen("𝐆𝐈𝐅𝐓 • 𝐔𝐍𝐁𝐎𝐗𝐈𝐍𝐆")
        f.p(step)
        frames.append(f)
    final = Screen("𝐆𝐈𝐅𝐓 • 𝐃𝐄𝐋𝐈𝐕𝐄𝐑𝐄𝐃")
    final.p(f"🎁 <b>@{username_of(query.from_user)}</b> sent {emoji} <b>{gift_type.capitalize()}</b> to <b>@{target_name}</b>!")
    final.kv([("💰 Spent", format_number(price))])
    frames.append(final)
    await view.animate(frames, interval=0.45)


@safe_reply
async def cmd_mygifts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    gift_rows = await db.get_gifts(user_id, limit=10)
    s = Screen("𝐘𝐎𝐔𝐑 𝐑𝐄𝐂𝐄𝐈𝐕𝐄𝐃 𝐆𝐈𝐅𝐓𝐒")
    if not gift_rows:
        s.p("❌ No gifts yet — be lovable, get gifts! 😄")
    else:
        entries = []
        for g in gift_rows:
            from_data = await db.get_user_global(g["from_user"])
            from_un = from_data["username"] if from_data else str(g["from_user"])
            emoji = config.GIFT_TYPES.get(g["gift_type"], {}).get("emoji", "🎁")
            date_str = g["created_at"].strftime("%Y-%m-%d") if g["created_at"] else "?"
            entries.append((emoji, f"from <b>@{from_un}</b> — {g['gift_type'].capitalize()} ({format_number(g['amount'])} 💰) <i>{date_str}</i>"))
        s.items(entries)
    view = LiveView.from_update(update)
    await view.open("Opening giftbox")
    await view.show(s)


def register(application) -> None:
    application.add_handler(CommandHandler("gift", cmd_gift))
    application.add_handler(CommandHandler("mygifts", cmd_mygifts))
    application.add_handler(CallbackQueryHandler(cb_gift, pattern=r"^gift:"))
