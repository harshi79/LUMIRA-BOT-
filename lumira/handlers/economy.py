"""Economy: /rank /leaderboard /riches /grp* /daily /scratch /shop /pay."""
from __future__ import annotations

import random
from datetime import timedelta
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from .. import keyboards, tgapi
from .. import config
from ..db import db
from ..engine import LiveView
from ..rich import Screen
from ..utils import (
    border_text,
    format_number,
    human_delta,
    localize,
    pending_manager,
    rate_limit_command,
    require_group,
    safe_reply,
    username_of,
    utcnow,
)
from . import screens


# --------------------------------------------------------------------- /rank
@safe_reply
@require_group
async def cmd_rank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    username = username_of(user)
    chat_id = update.effective_chat.id
    screen = await screens.profile_screen(user.id, username, chat_id=chat_id)

    # User-private render first (ephemeral, Bot API 10.2) — balance privacy.
    raw = await tgapi.send_ephemeral(
        context.bot,
        chat_id,
        user.id,
        screen.classic_html(),
        reply_to_message_id=update.message.message_id,
    )
    if raw:
        return
    view = LiveView.from_update(update)
    await view.open("Loading profile")
    await view.show(screen, markup=keyboards.profile_actions(context.bot.username))


# ------------------------------------------------------------- leaderboards
@safe_reply
async def cmd_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    view = LiveView.from_update(update)
    await view.open("Crunching ranks")
    await view.show(await screens.global_lb_screen(), effect="fire")


@safe_reply
async def cmd_riches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    view = LiveView.from_update(update)
    await view.open("Counting money")
    await view.show(await screens.global_riches_screen())


@safe_reply
@require_group
async def cmd_grpleaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    view = LiveView.from_update(update)
    await view.open("Ranking group")
    await view.show(await screens.group_lb_screen(update.effective_chat.id))


@safe_reply
@require_group
async def cmd_grpriches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    view = LiveView.from_update(update)
    await view.open("Counting coins")
    await view.show(await screens.group_riches_screen(update.effective_chat.id))


# ------------------------------------------------------------------- /daily
@safe_reply
@require_group
@rate_limit_command("daily")
async def cmd_daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id, chat_id = user.id, update.effective_chat.id
    username = username_of(user)
    now = utcnow()

    user_data = await db.get_user_per_group(user_id, chat_id)
    if user_data and user_data.get("last_daily"):
        last = localize(user_data["last_daily"])
        if (now - last) < timedelta(hours=config.DAILY_COOLDOWN_HOURS):
            remaining = timedelta(hours=config.DAILY_COOLDOWN_HOURS) - (now - last)
            s = Screen("𝐂𝐎𝐎𝐋𝐃𝐎𝐖𝐍 • 𝐃𝐀𝐈𝐋𝐘")
            s.kv(
                [
                    ("⏰ Next reward in", human_delta(remaining.total_seconds())),
                    ("🔥 Current streak", f"{user_data.get('daily_streak', 0)} days"),
                ]
            )
            s.p("💎 Try your luck with /scratch while you wait!")
            raw = await tgapi.send_ephemeral(
                context.bot, chat_id, user_id, s.classic_html(), reply_to_message_id=update.message.message_id
            )
            if not raw:
                await update.message.reply_text(s.classic_html(), parse_mode=ParseMode.HTML)
            return

    # streak math: within window → streak+1, else reset to 1
    old_streak = user_data.get("daily_streak", 0) if user_data else 0
    last = localize(user_data["last_daily"]) if user_data and user_data.get("last_daily") else None
    if last and (now - last) <= timedelta(hours=config.STREAK_WINDOW_HOURS):
        streak = old_streak + 1
    else:
        streak = 1
    bonus = 0
    milestone = streak > 0 and streak % config.STREAK_BONUS_EVERY == 0
    if milestone:
        bonus = config.STREAK_BONUS_COINS
    total_gain = config.DAILY_COINS + bonus

    await db.update_user_global(user_id, username, coins_delta=total_gain)
    await db.update_user_per_group(
        user_id, chat_id, username, coins_delta=total_gain, last_daily=True, streak=streak
    )
    await db.add_guild_xp_for_user(user_id, config.GUILD_XP_DAILY)

    global_data = await db.get_user_global(user_id)
    balance = global_data["total_coins"] if global_data else total_gain

    if milestone:
        frames = [_daily_frame(i) for i in (2, 5, 8)]
        frames.append(_daily_final(streak, bonus, balance))
        view = LiveView.from_update(update)
        await view.open("Claiming")
        await view.animate(frames, interval=0.35, effect="party")
    else:
        s = _daily_final(streak, bonus, balance)
        await update.message.reply_text(
            s.classic_html(), parse_mode=ParseMode.HTML, message_effect_id=tgapi.effect_or_none("thumbs_up")
        )
    await tgapi.react(context.bot, chat_id, update.message.message_id, "❤")


def _daily_frame(i: int) -> Screen:
    s = Screen("𝐃𝐀𝐈𝐋𝐘 𝐑𝐄𝐖𝐀𝐑𝐃")
    s.p(f"⚡ Streak sync <code>{'▓' * i}{'░' * (10 - i)}</code>")
    return s


def _daily_final(streak: int, bonus: int, balance: int) -> Screen:
    s = Screen("𝐃𝐀𝐈𝐋𝐘 𝐑𝐄𝐖𝐀𝐑𝐃 • 𝐂𝐋𝐀𝐈𝐌𝐄𝐃")
    s.kv(
        [
            ("💰 Base reward", f"+{format_number(config.DAILY_COINS)}"),
            ("🔥 Streak", f"{streak} day{'s' if streak != 1 else ''}"),
            ("⚡ Streak bonus", f"+{format_number(bonus)}" if bonus else "—"),
            ("💎 Balance", format_number(balance)),
            ("⏭️ Next claim", f"{config.DAILY_COOLDOWN_HOURS}h"),
        ]
    )
    if bonus:
        s.quote(f"🔥 {config.STREAK_BONUS_EVERY}-day streak milestone — bonus paid instantly!")
    s.p("💡 <i>Visit /shop to buy active protection!</i>")
    return s


# ----------------------------------------------------------------- /scratch
@safe_reply
@require_group
@rate_limit_command("scratch")
async def cmd_scratch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id, chat_id = user.id, update.effective_chat.id
    username = username_of(user)
    now = utcnow()

    user_data = await db.get_user_per_group(user_id, chat_id)
    if user_data and user_data.get("last_scratch"):
        last = localize(user_data["last_scratch"])
        if (now - last) < timedelta(hours=config.SCRATCH_COOLDOWN_HOURS):
            remaining = timedelta(hours=config.SCRATCH_COOLDOWN_HOURS) - (now - last)
            s = Screen("𝐂𝐎𝐎𝐋𝐃𝐎𝐖𝐍 • 𝐒𝐂𝐑𝐀𝐓𝐂𝐇")
            s.kv([("⏰ Next card in", human_delta(remaining.total_seconds()))])
            s.p("💡 Try /daily if you haven't claimed it!")
            await update.message.reply_text(s.classic_html(), parse_mode=ParseMode.HTML)
            return

    win = random.randint(1, 1000)
    big_win = win >= 850
    jackpot = win >= 980

    view = LiveView.from_update(update)
    await view.open("🎫 Scratching")

    frames = []
    for step in range(1, 4):
        s = Screen("𝐒𝐂𝐑𝐀𝐓𝐂𝐇 𝐂𝐀𝐑𝐃")
        done = "▓" * (step * 2)
        left = "▒" * (8 - step * 2)
        s.p(f"🎫 <code>{done}{left}</code>")
        s.p("<i>Scraping the foil…</i>")
        frames.append(s)
    if jackpot:
        title, emoji = "𝐒𝐂𝐑𝐀𝐓𝐂𝐇 𝐂𝐀𝐑𝐃 • 🏆 𝐔𝐋𝐓𝐑𝐀 𝐉𝐀𝐂𝐊𝐏𝐎𝐓", "🏆"
    elif big_win:
        title, emoji = "𝐒𝐂𝐑𝐀𝐓𝐂𝐇 𝐂𝐀𝐑𝐃 • 𝐁𝐈𝐆 𝐖𝐈𝐍", "🎉"
    else:
        title, emoji = "𝐒𝐂𝐑𝐀𝐓𝐂𝐇 𝐂𝐀𝐑𝐃 • 𝐋𝐔𝐂𝐊", "✨"

    await db.update_user_global(user_id, username, coins_delta=win)
    await db.update_user_per_group(user_id, chat_id, username, coins_delta=win, last_scratch=True)
    await db.add_guild_xp_for_user(user_id, config.GUILD_XP_SCRATCH)
    global_data = await db.get_user_global(user_id)
    balance = global_data["total_coins"] if global_data else win

    final = Screen(title)
    final.p(f"{emoji} You revealed <b>{format_number(win)} coins</b>!")
    final.kv(
        [
            ("💰 Balance", format_number(balance)),
            ("🔄 Next card", f"{config.SCRATCH_COOLDOWN_HOURS}h"),
        ]
    )
    frames.append(final)
    await view.animate(frames, interval=0.42, effect="party" if big_win else None)
    if big_win:
        await tgapi.react(context.bot, chat_id, update.message.message_id, "🎉")


# -------------------------------------------------------------------- /shop
@safe_reply
async def cmd_shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from telegram.constants import ChatType

    s = Screen("𝐋𝐔𝐌𝐈𝐑𝐀 𝐒𝐇𝐎𝐏 • 𝐈𝐓𝐄𝐌𝐒", subtitle="🛒 Welcome to the Lumira Marketplace")
    user = update.effective_user
    in_dm = update.effective_chat.type == ChatType.PRIVATE
    if in_dm:
        glob = await db.get_user_global(user.id)
        s.kv([("🌍 Global balance", format_number(glob["total_coins"]) if glob else "0")])
        s.p("🛍️ <i>Browse here — purchases happen inside your groups (balances are per-group).</i>")
    else:
        per = await db.get_user_per_group(user.id, update.effective_chat.id)
        s.kv([("💰 Your balance", format_number(per["coins"]) if per else "0")])
    s.h("🧾 Catalogue", 2)
    s.items(
        [
            ("🛡️", f"<b>Shield</b> — blocks /rob /kill /roast for {config.SHIELD_DURATION_HOURS}h"),
            ("✨", "<b>XP Boost</b> — instant +1–50 XP"),
            ("🎟️", "<b>Lottery</b> — win up to 500 coins"),
            ("💪", "<b>Revive</b> — rise from the grave"),
        ]
    )
    view = LiveView.from_update(update)
    await view.open("Opening shop")
    await view.show(s, markup=None if in_dm else keyboards.shop())


@safe_reply
async def cb_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, _, item = (query.data or "").partition(":")
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    username = username_of(query.from_user)

    user_per_group = await db.get_user_per_group(user_id, chat_id)
    if not user_per_group:
        await query.answer("You need to chat first before shopping!", show_alert=True)
        return
    coins = user_per_group["coins"]
    view = LiveView.from_query(query)

    def fail(cost: int) -> Screen:
        s = Screen("𝐏𝐔𝐑𝐂𝐇𝐀𝐒𝐄 • 𝐅𝐀𝐈𝐋𝐄𝐃")
        s.p(f"❌ <b>Insufficient coins!</b> Need {format_number(cost)}, you have {format_number(coins)}.")
        s.p("💡 Claim /daily and /scratch to earn more!")
        return s

    if item == "shield":
        if coins < config.SHIELD_COST:
            await view.show(fail(config.SHIELD_COST))
            return
        expiry = utcnow() + timedelta(hours=config.SHIELD_DURATION_HOURS)
        await db.update_user_per_group(user_id, chat_id, username, coins_delta=-config.SHIELD_COST, shield_expiry=expiry)
        await db.update_user_global(user_id, username, coins_delta=-config.SHIELD_COST)
        s = Screen("𝐏𝐔𝐑𝐂𝐇𝐀𝐒𝐄 • 𝐒𝐔𝐂𝐂𝐄𝐒𝐒")
        s.p(f"🛡️ <b>Shield Activated!</b> PVP protection for {config.SHIELD_DURATION_HOURS}h.")
        s.kv([("💰 Remaining", format_number(coins - config.SHIELD_COST))])
        await query.answer("🛡️ Shield equipped!")
        await view.show(s)

    elif item == "xp":
        price = 100
        if coins < price:
            await view.show(fail(price))
            return
        gain = random.randint(1, 50)
        await db.update_user_per_group(user_id, chat_id, username, coins_delta=-price, xp_delta=gain)
        await db.update_user_global(user_id, username, coins_delta=-price, xp_delta=gain)
        await db.add_guild_xp_for_user(user_id, 1)
        s = Screen("𝐏𝐔𝐑𝐂𝐇𝐀𝐒𝐄 • 𝐒𝐔𝐂𝐂𝐄𝐒𝐒")
        s.p(f"✨ <b>XP Boost!</b> +{gain} XP instantly.")
        s.kv([("💰 Remaining", format_number(coins - price))])
        await query.answer(f"✨ +{gain} XP!")
        await view.show(s)

    elif item == "lottery":
        price = 50
        if coins < price:
            await view.show(fail(price))
            return
        await query.answer("🎟️ Revealing ticket…")
        win = random.choice([0, 0, 100, 100, 200, 500])
        await db.update_user_per_group(user_id, chat_id, username, coins_delta=-price + win)
        await db.update_user_global(user_id, username, coins_delta=-price + win)
        await db.add_guild_xp_for_user(user_id, 1)
        frames = []
        symbols = ["🍒", "🍋", "💎", "⭐", "7️⃣"]
        for _ in range(3):
            f = Screen("𝐋𝐎𝐓𝐓𝐄𝐑𝐘 • 𝐑𝐄𝐕𝐄𝐀𝐋𝐈𝐍𝐆")
            f.p("<code>" + " ".join(random.choices(symbols, k=3)) + "</code>")
            frames.append(f)
        if win:
            final = Screen("𝐋𝐎𝐓𝐓𝐄𝐑𝐘 • 🎟️ 𝐖𝐈𝐍𝐍𝐄𝐑")
            final.p(f"Your ticket matched jackpot numbers — <b>{format_number(win)} coins</b> awarded!")
            final.kv([("💰 Balance", format_number(coins - price + win))])
        else:
            final = Screen("𝐋𝐎𝐓𝐓𝐄𝐑𝐘 • 𝐍𝐎𝐓 𝐓𝐇𝐈𝐒 𝐓𝐈𝐌𝐄")
            final.p("🎟️ No win this time. The machine owes you one.")
            final.kv([("💰 Balance", format_number(coins - price))])
        frames.append(final)
        await view.animate(frames, interval=0.5, effect="party" if win >= 200 else None)

    elif item == "revive_self":
        if not user_per_group.get("is_dead"):
            await query.answer("You are already alive and well!", show_alert=True)
            return
        if coins < config.REVIVE_SELF_COST:
            await view.show(fail(config.REVIVE_SELF_COST))
            return
        await db.update_user_per_group(user_id, chat_id, username, coins_delta=-config.REVIVE_SELF_COST, set_dead=False)
        await db.update_user_global(user_id, username, coins_delta=-config.REVIVE_SELF_COST)
        await db.add_guild_xp_for_user(user_id, config.GUILD_XP_REVIVE)
        s = Screen("𝐑𝐄𝐕𝐈𝐕𝐄𝐃 • 𝐒𝐔𝐂𝐂𝐄𝐒𝐒")
        s.p("💪 <b>You rose from the grave!</b> Ready for combat.")
        s.kv([("💰 Remaining", format_number(coins - config.REVIVE_SELF_COST))])
        await query.answer("💪 Alive again!")
        await view.show(s)

    elif item == "revive_other":
        await query.answer("Type /revive @username in the group!", show_alert=True)


# --------------------------------------------------------------------- /pay
@safe_reply
@require_group
async def cmd_pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Consent-based coin transfer — reply to a user: /pay 500"""
    if not update.message.reply_to_message:
        await update.message.reply_text(
            border_text("𝐏𝐀𝐘 • 𝐔𝐒𝐀𝐆𝐄", "❌ Reply to a user's message with <code>/pay &lt;amount&gt;</code>."),
            parse_mode=ParseMode.HTML,
        )
        return
    target = update.message.reply_to_message.from_user
    sender = update.effective_user
    if target.id == sender.id or target.is_bot:
        await update.message.reply_text(
            border_text("𝐏𝐀𝐘 • 𝐍𝐎𝐓𝐈𝐂𝐄", "🤡 Invalid recipient." if target.is_bot else "🤡 Paying yourself? Bold strategy."),
            parse_mode=ParseMode.HTML,
        )
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(
            border_text("𝐏𝐀𝐘 • 𝐔𝐒𝐀𝐆𝐄", "❌ Usage: <code>/pay &lt;amount&gt;</code> (as a reply)"),
            parse_mode=ParseMode.HTML,
        )
        return
    amount = int(context.args[0])
    if amount <= 0 or amount > config.PAY_MAX:
        await update.message.reply_text(
            border_text("𝐏𝐀𝐘 • 𝐄𝐑𝐑𝐎𝐑", f"❌ Amount must be 1–{format_number(config.PAY_MAX)}."),
            parse_mode=ParseMode.HTML,
        )
        return

    chat_id = update.effective_chat.id
    sender_data = await db.get_user_per_group(sender.id, chat_id)
    if not sender_data or sender_data["coins"] < amount:
        await update.message.reply_text(
            border_text("𝐏𝐀𝐘 • 𝐈𝐍𝐒𝐔𝐅𝐅𝐈𝐂𝐈𝐄𝐍𝐓", "❌ You don't have that many coins in this group."),
            parse_mode=ParseMode.HTML,
        )
        return

    success = await pending_manager.set(
        chat_id, sender.id, {"action": "pay", "target_id": target.id, "amount": amount}
    )
    if not success:
        await update.message.reply_text(border_text("𝐏𝐀𝐘 • 𝐄𝐑𝐑𝐎𝐑", "❌ System busy. Try again later."), parse_mode=ParseMode.HTML)
        return

    s = Screen("𝐏𝐀𝐘 • 𝐂𝐎𝐍𝐅𝐈𝐑𝐌")
    s.kv(
        [
            ("💸 Amount", format_number(amount)),
            ("👤 To", f"@{username_of(target)}"),
            ("💰 Balance after", format_number(sender_data["coins"] - amount)),
        ]
    )
    await update.message.reply_text(
        s.classic_html(),
        reply_markup=keyboards.pay_confirm(amount, target.id),
        parse_mode=ParseMode.HTML,
    )


@safe_reply
async def cb_pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id
    user_id = query.from_user.id
    view = LiveView.from_query(query)

    if query.data == "paycancel":
        from ..utils import pending_manager

        await pending_manager.delete(chat_id, user_id)
        await query.answer("Cancelled")
        s = Screen("𝐏𝐀𝐘 • 𝐂𝐀𝐍𝐂𝐄𝐋𝐋𝐄𝐃")
        s.p("❌ Transfer aborted — coins stay with you.")
        await view.show(s)
        return

    _, amount_s, target_s = query.data.split(":")
    amount, target_id = int(amount_s), int(target_s)
    from ..utils import pending_manager

    pending = await pending_manager.get(chat_id, user_id)
    if not pending or pending.get("action") != "pay" or pending.get("amount") != amount:
        await query.answer("This payment has expired.", show_alert=True)
        return

    target_name = "Unknown"
    trow = await db.get_user_global(target_id)
    if trow:
        target_name = trow["username"]

    ok, msg = await db.transfer_coins(
        user_id, target_id, chat_id, amount, username_of(query.from_user), target_name
    )
    await pending_manager.delete(chat_id, user_id)
    if not ok:
        await query.answer(msg, show_alert=True)
        s = Screen("𝐏𝐀𝐘 • 𝐅𝐀𝐈𝐋𝐄𝐃")
        s.p(f"❌ {msg}")
        await view.show(s)
        return

    await db.add_guild_xp_for_user(user_id, config.GUILD_XP_PAY)
    await query.answer(f"✅ Sent {format_number(amount)} coins!")
    s = Screen("𝐏𝐀𝐘 • 𝐒𝐔𝐂𝐂𝐄𝐒𝐒")
    s.p(f"💸 <b>@{username_of(query.from_user)}</b> sent <b>{format_number(amount)} coins</b> to <b>@{target_name}</b>!")
    await view.show(s, effect="party")


def register(application) -> None:
    application.add_handler(CommandHandler("rank", cmd_rank))
    application.add_handler(CommandHandler("leaderboard", cmd_leaderboard))
    application.add_handler(CommandHandler("riches", cmd_riches))
    application.add_handler(CommandHandler("grpleaderboard", cmd_grpleaderboard))
    application.add_handler(CommandHandler("grpriches", cmd_grpriches))
    application.add_handler(CommandHandler("daily", cmd_daily))
    application.add_handler(CommandHandler("scratch", cmd_scratch))
    application.add_handler(CommandHandler("shop", cmd_shop))
    application.add_handler(CommandHandler("pay", cmd_pay))
    application.add_handler(CallbackQueryHandler(cb_buy, pattern=r"^buy:"))
    application.add_handler(CallbackQueryHandler(cb_pay, pattern=r"^pay(:|cancel)"))
