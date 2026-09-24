"""Owner/admin: analytics, members, addcoins/removecoins, stats, broadcast
(with a live progress view while dispatching)."""
from __future__ import annotations

import asyncio

from telegram import Update
from telegram.constants import ChatType, ParseMode
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from .. import config, keyboards
from ..db import db
from ..engine import LiveView
from ..rich import Screen
from ..utils import (
    border_text,
    broadcast_rate_limiter,
    esc,
    format_number,
    logger,
    pending_manager,
    require_group,
    safe_reply,
    username_of,
    utcnow,
)
from .helpers import require_owner


# ---------------------------------------------------------------- /analytics
@safe_reply
@require_group
async def cmd_analytics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_owner(update, context):
        return
    chat_id = update.effective_chat.id
    stats = await db.get_group_stats(chat_id)
    top_name = stats["top_user"]["username"] if stats["top_user"] else "N/A"
    top_xp = format_number(stats["top_user"]["xp"]) if stats["top_user"] else "0"

    s = Screen("𝐆𝐑𝐎𝐔𝐏 𝐀𝐍𝐀𝐋𝐘𝐓𝐈𝐂𝐒", subtitle="Group insights & metrics")
    s.kv(
        [
            ("👥 Tracked users", format_number(stats["user_count"])),
            ("💬 Messages logged", format_number(stats.get("total_msgs", 0))),
            ("🏆 Top chatter", f"@{esc(top_name)} ({top_xp} XP)"),
            ("🏥 System", "Active & Synchronized"),
            ("🕒 Updated", utcnow().strftime("%I:%M %p IST")),
        ]
    )
    view = LiveView.from_update(update)
    await view.open("Crunching telemetry")
    await view.show(s)


# ------------------------------------------------------------------ /members
@safe_reply
@require_group
async def cmd_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_owner(update, context):
        return
    chat_id = update.effective_chat.id
    try:
        total = await context.bot.get_chat_member_count(chat_id)
        admins = await context.bot.get_chat_administrators(chat_id)
        creator = next((a.user.first_name for a in admins if a.status == "creator"), "Unknown")
    except Exception as e:
        logger.error(f"members error: {e}")
        await update.message.reply_text(
            border_text("𝐌𝐄𝐌𝐁𝐄𝐑𝐒 • 𝐄𝐑𝐑𝐎𝐑", "❌ Could not fetch Telegram telemetry."),
            parse_mode=ParseMode.HTML,
        )
        return
    s = Screen("𝐌𝐄𝐌𝐁𝐄𝐑 𝐓𝐄𝐋𝐄𝐌𝐄𝐓𝐑𝐘")
    s.kv(
        [
            ("👥 Total members", format_number(total)),
            ("🛠️ Administrators", str(len(admins))),
            ("👑 Founder", esc(creator)),
            ("📌 Title", esc(update.effective_chat.title or "?")),
            ("🆔 Chat ID", f"<code>{chat_id}</code>"),
        ]
    )
    view = LiveView.from_update(update)
    await view.open("Querying Telegram")
    await view.show(s)


# ---------------------------------------------------------------------- /top
@safe_reply
@require_group
async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_owner(update, context):
        return
    from .economy import cmd_grpleaderboard

    await cmd_grpleaderboard(update, context)


# --------------------------- coin admin flows (pending amount input in chat)
@safe_reply
@require_group
async def cmd_addcoins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_owner(update, context):
        return
    if not update.message.reply_to_message:
        await update.message.reply_text(
            border_text("𝐀𝐃𝐃𝐂𝐎𝐈𝐍𝐒 • 𝐔𝐒𝐀𝐆𝐄", "❌ Reply to a user with <code>/addcoins</code>."),
            parse_mode=ParseMode.HTML,
        )
        return
    target = update.message.reply_to_message.from_user
    chat_id = update.effective_chat.id
    success = await pending_manager.set(
        chat_id, update.effective_user.id, {"action": "addcoins", "target_id": target.id, "target_name": username_of(target)}
    )
    if not success:
        await update.message.reply_text(border_text("𝐀𝐃𝐃𝐂𝐎𝐈𝐍𝐒 • 𝐄𝐑𝐑𝐎𝐑", "❌ System busy."), parse_mode=ParseMode.HTML)
        return
    await update.message.reply_text(
        border_text("𝐀𝐃𝐃𝐂𝐎𝐈𝐍𝐒 • 𝐀𝐌𝐎𝐔𝐍𝐓", f"💰 Enter the amount to add to <b>@{username_of(target)}</b>:"),
        parse_mode=ParseMode.HTML,
    )


@safe_reply
@require_group
async def cmd_removecoins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_owner(update, context):
        return
    if not update.message.reply_to_message:
        await update.message.reply_text(
            border_text("𝐑𝐄𝐌𝐎𝐕𝐄𝐂𝐎𝐈𝐍𝐒 • 𝐔𝐒𝐀𝐆𝐄", "❌ Reply to a user with <code>/removecoins</code>."),
            parse_mode=ParseMode.HTML,
        )
        return
    target = update.message.reply_to_message.from_user
    chat_id = update.effective_chat.id
    success = await pending_manager.set(
        chat_id, update.effective_user.id, {"action": "removecoins", "target_id": target.id, "target_name": username_of(target)}
    )
    if not success:
        await update.message.reply_text(border_text("𝐑𝐄𝐌𝐎𝐕𝐄𝐂𝐎𝐈𝐍𝐒 • 𝐄𝐑𝐑𝐎𝐑", "❌ System busy."), parse_mode=ParseMode.HTML)
        return
    await update.message.reply_text(
        border_text("𝐑𝐄𝐌𝐎𝐕𝐄𝐂𝐎𝐈𝐍𝐒 • 𝐀𝐌𝐎𝐔𝐍𝐓", f"💰 Enter the amount to remove from <b>@{username_of(target)}</b>:"),
        parse_mode=ParseMode.HTML,
    )


async def handle_coin_pending(update: Update, pending: dict) -> None:
    """Executed by events router when an owner types the amount."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    text = (update.message.text or "").strip()
    action = pending.get("action")
    target_id = pending.get("target_id")
    target_name = pending.get("target_name", "Unknown")

    if not text.isdigit():
        await update.message.reply_text(border_text("𝐄𝐑𝐑𝐎𝐑", "❌ Enter a positive number."), parse_mode=ParseMode.HTML)
        return
    amount = int(text)
    if amount <= 0 or amount > 1_000_000:
        await update.message.reply_text(
            border_text("𝐄𝐑𝐑𝐎𝐑", "❌ Amount must be 1–1,000,000."), parse_mode=ParseMode.HTML
        )
        return

    if action == "addcoins":
        await db.update_user_per_group(target_id, chat_id, target_name, coins_delta=amount)
        await db.update_user_global(target_id, target_name, coins_delta=amount)
        verb = "granted to"
        logger.info(f"Owner {user_id} +{amount} coins → {target_id} ({chat_id})")
    else:
        target_per = await db.get_user_per_group(target_id, chat_id)
        if target_per and target_per["coins"] < amount:
            await update.message.reply_text(
                border_text("𝐈𝐍𝐒𝐔𝐅𝐅𝐈𝐂𝐈𝐄𝐍𝐓", f"❌ @{target_name} only has {format_number(target_per['coins'])}."),
                parse_mode=ParseMode.HTML,
            )
            await pending_manager.delete(chat_id, user_id)
            return
        await db.update_user_per_group(target_id, chat_id, target_name, coins_delta=-amount)
        await db.update_user_global(target_id, target_name, coins_delta=-amount)
        verb = "removed from"
        logger.info(f"Owner {user_id} -{amount} coins → {target_id} ({chat_id})")

    new_global = await db.get_user_global(target_id)
    new_per = await db.get_user_per_group(target_id, chat_id)
    s = Screen("𝐂𝐎𝐈𝐍 𝐓𝐑𝐀𝐍𝐒𝐀𝐂𝐓𝐈𝐎𝐍 • 𝐒𝐔𝐂𝐂𝐄𝐒𝐒")
    s.p(f"✅ <b>{format_number(amount)} coins {verb} @{target_name}</b>")
    s.kv(
        [
            ("💎 Global balance", format_number(new_global["total_coins"] if new_global else 0)),
            ("📊 Group balance", format_number(new_per["coins"] if new_per else 0)),
        ]
    )
    view = LiveView.from_update(update)
    await view.show(s, effect="thumbs_up")
    await pending_manager.delete(chat_id, user_id)


# --------------------------------------------------------------------- /stats
@safe_reply
async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.GLOBAL_OWNER_ID:
        await update.message.reply_text(
            border_text("𝐒𝐓𝐀𝐓𝐒 • 𝐀𝐂𝐂𝐄𝐒𝐒", "❌ Global Master only."),
            parse_mode=ParseMode.HTML,
        )
        return
    groups = await db.get_all_groups()
    s = Screen("𝐒𝐘𝐒𝐓𝐄𝐌 𝐆𝐑𝐎𝐔𝐏 𝐑𝐄𝐆𝐈𝐒𝐓𝐑𝐘")
    if not groups:
        s.p("❌ No monitored groups.")
    else:
        s.p(f"📌 <b>Monitored groups: {len(groups)}</b>")
        rows = []
        for g in groups[:25]:
            title = g["title"] or "Unknown"
            added = g["added_on"].strftime("%Y-%m-%d") if g["added_on"] else "?"
            rows.append(("🏰", f"<b>{esc(title)}</b> <code>{g['chat_id']}</code> • {added}"))
        s.items(rows)
        if len(groups) > 25:
            s.p(f"\n<i>…and {len(groups) - 25} more.</i>")
    view = LiveView.from_update(update)
    await view.open("Loading registry")
    await view.show(s)


# ----------------------------------------------------------------- /broadcast
@safe_reply
async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.GLOBAL_OWNER_ID:
        await update.message.reply_text(
            border_text("𝐁𝐑𝐎𝐀𝐃𝐂𝐀𝐒𝐓", "❌ Global Master only."), parse_mode=ParseMode.HTML
        )
        return
    if update.effective_chat.type != ChatType.PRIVATE:
        await update.message.reply_text(
            border_text("𝐁𝐑𝐎𝐀𝐃𝐂𝐀𝐒𝐓", "❌ Use <code>/broadcast</code> in DM for security."),
            parse_mode=ParseMode.HTML,
        )
        return
    allowed, remaining = await broadcast_rate_limiter.check(update.effective_user.id, "broadcast")
    if not allowed:
        await update.message.reply_text(
            border_text("⏳ 𝐁𝐑𝐎𝐀𝐃𝐂𝐀𝐒𝐓 𝐂𝐎𝐎𝐋𝐃𝐎𝐖𝐍", f"Wait {remaining}s before another broadcast."),
            parse_mode=ParseMode.HTML,
        )
        return
    success = await pending_manager.set(
        update.effective_chat.id, update.effective_user.id, {"action": "broadcast_waiting_content"}
    )
    if not success:
        await update.message.reply_text(border_text("𝐁𝐑𝐎𝐀𝐃𝐂𝐀𝐒𝐓 • 𝐄𝐑𝐑𝐎𝐑", "❌ System busy."), parse_mode=ParseMode.HTML)
        return
    s = Screen("𝐁𝐑𝐎𝐀𝐃𝐂𝐀𝐒𝐓 • 𝐈𝐍𝐈𝐓𝐈𝐀𝐓𝐄𝐃")
    s.p("📢 Send the exact message or media to dispatch across <b>all monitored groups and users</b>.")
    s.p("You'll get a live confirmation + delivery dashboard.")
    await update.message.reply_text(s.classic_html(), parse_mode=ParseMode.HTML)


async def handle_broadcast_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """DM message router for the broadcast flow (owner only)."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    pending = await pending_manager.get(chat_id, user_id)
    if not pending or pending.get("action") != "broadcast_waiting_content":
        return
    await pending_manager.set(
        chat_id,
        user_id,
        {"action": "broadcast_confirm", "from_chat_id": chat_id, "message_id": update.message.message_id},
    )
    s = Screen("𝐂𝐎𝐍𝐅𝐈𝐑𝐌 𝐁𝐑𝐎𝐀𝐃𝐂𝐀𝐒𝐓")
    s.p("📢 Ready to copy & dispatch this message to all groups + users?")
    await update.message.reply_text(
        s.classic_html(),
        reply_markup=keyboards.confirm("broadcast:confirm", "broadcast:cancel", "✅ CONFIRM DISPATCH"),
        parse_mode=ParseMode.HTML,
    )


@safe_reply
async def cb_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    view = LiveView.from_query(query)

    if user_id != config.GLOBAL_OWNER_ID:
        await query.answer("Unauthorized.", show_alert=True)
        return

    action = query.data.split(":")[1]
    if action == "cancel":
        await pending_manager.delete(chat_id, user_id)
        await query.answer("Cancelled")
        s = Screen("𝐁𝐑𝐎𝐀𝐃𝐂𝐀𝐒𝐓 • 𝐂𝐀𝐍𝐂𝐄𝐋𝐋𝐄𝐃")
        s.p("❌ Broadcast aborted.")
        await view.show(s)
        return

    pending = await pending_manager.get(chat_id, user_id)
    if not pending or pending.get("action") != "broadcast_confirm":
        await query.answer("No pending broadcast found.", show_alert=True)
        return
    await query.answer("Dispatching…")

    from_chat = pending["from_chat_id"]
    msg_id = pending["message_id"]
    groups = await db.get_all_groups()
    user_ids = await db.get_all_user_ids()
    targets = ([("g", g["chat_id"]) for g in groups] + [("u", uid) for uid in user_ids])
    total = len(targets)
    success_count = 0
    fail_count = 0

    # Live progress dashboard — one message, morphing as dispatch advances.
    for i, (_, target) in enumerate(targets, start=1):
        try:
            await context.bot.copy_message(chat_id=target, from_chat_id=from_chat, message_id=msg_id)
            success_count += 1
        except Exception as e:
            logger.debug(f"broadcast → {target} failed: {e}")
            fail_count += 1
        if i % 8 == 0 or i == total:
            pct = int(i / max(1, total) * 100)
            bar = "▓" * (pct // 10) + "░" * (10 - pct // 10)
            s = Screen("𝐁𝐑𝐎𝐀𝐃𝐂𝐀𝐒𝐓 • 𝐃𝐈𝐒𝐏𝐀𝐓𝐂𝐇𝐈𝐍𝐆")
            s.p(f"<code>{bar}</code> <b>{pct}%</b>")
            s.kv(
                [
                    ("✅ Delivered", format_number(success_count)),
                    ("❌ Failed", format_number(fail_count)),
                    ("📦 Progress", f"{i}/{total}"),
                ]
            )
            try:
                await view.show(s)
            except Exception:
                pass
            await asyncio.sleep(0.08)

    s = Screen("𝐁𝐑𝐎𝐀𝐃𝐂𝐀𝐒𝐓 • 𝐒𝐔𝐌𝐌𝐀𝐑𝐘")
    s.kv(
        [
            ("✅ Delivered", format_number(success_count)),
            ("❌ Failed / blocked", format_number(fail_count)),
            ("📦 Total targets", format_number(total)),
        ]
    )
    await view.show(s, effect="party")
    await pending_manager.delete(chat_id, user_id)


def register(application) -> None:
    application.add_handler(CommandHandler("analytics", cmd_analytics))
    application.add_handler(CommandHandler("members", cmd_members))
    application.add_handler(CommandHandler("top", cmd_top))
    application.add_handler(CommandHandler("addcoins", cmd_addcoins))
    application.add_handler(CommandHandler("removecoins", cmd_removecoins))
    application.add_handler(CommandHandler("stats", cmd_stats))
    application.add_handler(CommandHandler("broadcast", cmd_broadcast))
    application.add_handler(CallbackQueryHandler(cb_broadcast, pattern=r"^broadcast:"))
    # Owner DM capture for broadcast content (specific → low priority is fine)
    application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & filters.User(user_id=config.GLOBAL_OWNER_ID) & ~filters.COMMAND,
            handle_broadcast_content,
        ),
        group=1,
    )
