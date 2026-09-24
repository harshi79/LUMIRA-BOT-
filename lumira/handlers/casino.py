"""Casino: /slots — native 🎰 slot machine with real payout logic.

Telegram slots values 1-64 encode 3 reels with 4 symbols each
(0=BAR, 1=grapes, 2=lemon, 3=seven):  value-1 => reel = v//16, (v//4)%4, v%4.
The bot knows the result the instant send_dice returns; clients show the
real animation (~3s) — so we reveal right after the reels stop.
"""
from __future__ import annotations

import asyncio

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import CommandHandler, ContextTypes

from .. import config, tgapi
from ..db import db
from ..engine import LiveView
from ..rich import Screen
from ..utils import border_text, cooldowns, format_number, require_group, safe_reply, username_of

SYMBOL = {0: "🍫BAR", 1: "🍇", 2: "🍋", 3: "7"}


def decode_slots(value: int) -> tuple:
    v = max(1, min(64, value)) - 1
    return v // 16, (v // 4) % 4, v % 4


def payout(reels: tuple, bet: int) -> tuple:
    """Returns (multiple, label). Lose = (0, ...)."""
    a, b, c = reels
    if a == b == c == 3:
        return 10, "𝟕𝟕𝟕 — ULTRA JACKPOT"
    if a == b == c:
        return 5, "TRIPLE MATCH"
    if 3 in reels and (a == 3 or b == 3 or c == 3):
        sevens = reels.count(3)
        if sevens == 2:
            return 3, "DOUBLE SEVEN"
        return 2, "LUCKY SEVEN"
    return 0, "no match"


@safe_reply
@require_group
async def cmd_slots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    username = username_of(user)

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(
            border_text(
                "𝐒𝐋𝐎𝐓𝐒 • 𝐔𝐒𝐀𝐆𝐄",
                f"🎰 <code>/slots &lt;bet&gt;</code> — bet {config.SLOTS_MIN_BET}–{format_number(config.SLOTS_MAX_BET)} coins\n"
                "777 pays <b>10×</b> • triple pays <b>5×</b> • any 7 pays <b>2×</b>",
            ),
            parse_mode=ParseMode.HTML,
        )
        return

    ok, remaining = await cooldowns.check(user.id, "slots", config.SLOTS_COOLDOWN_SEC)
    if not ok:
        await update.message.reply_text(
            border_text("𝐒𝐋𝐎𝐓𝐒 • 𝐂𝐎𝐎𝐋𝐃𝐎𝐖𝐍", f"⏳ Machine is reloading — wait <b>{remaining}s</b>."),
            parse_mode=ParseMode.HTML,
        )
        return

    bet = int(context.args[0])
    if bet < config.SLOTS_MIN_BET or bet > config.SLOTS_MAX_BET:
        await update.message.reply_text(
            border_text(
                "𝐒𝐋𝐎𝐓𝐒 • 𝐄𝐑𝐑𝐎𝐑",
                f"❌ Bet must be {config.SLOTS_MIN_BET}–{format_number(config.SLOTS_MAX_BET)} coins.",
            ),
            parse_mode=ParseMode.HTML,
        )
        return

    per = await db.get_user_per_group(user.id, chat_id)
    if not per or per["coins"] < bet:
        await update.message.reply_text(
            border_text("𝐒𝐋𝐎𝐓𝐒 • 𝐈𝐍𝐒𝐔𝐅𝐅𝐈𝐂𝐈𝐄𝐍𝐓", "❌ You don't have that many coins."),
            parse_mode=ParseMode.HTML,
        )
        return
    if per.get("is_dead"):
        await update.message.reply_text(
            border_text("𝐒𝐋𝐎𝐓𝐒 • 𝐍𝐎𝐓𝐈𝐂𝐄", "💀 Ghosts don't gamble. <code>/revive</code> first!"),
            parse_mode=ParseMode.HTML,
        )
        return

    # deduct up-front, then spin the REAL machine
    await db.update_user_per_group(user.id, chat_id, username, coins_delta=-bet)
    await db.update_user_global(user.id, username, coins_delta=-bet)

    msg = await context.bot.send_dice(chat_id=chat_id, emoji="🎰", reply_to_message_id=update.message.message_id)
    reels = decode_slots(msg.dice.value)
    mult, label = payout(reels, bet)
    win = bet * mult

    if win:
        await db.update_user_per_group(user.id, chat_id, username, coins_delta=win)
        await db.update_user_global(user.id, username, coins_delta=win)
        await db.add_guild_xp_for_user(user.id, config.GUILD_XP_SLOTS_WIN)

    per2 = await db.get_user_per_group(user.id, chat_id)
    balance = per2["coins"] if per2 else 0

    await asyncio.sleep(3.4)  # let the reels actually stop

    face = " ".join(SYMBOL[r] for r in reels)
    s = Screen(f"𝐒𝐋𝐎𝐓𝐒 • {'𝐖𝐈𝐍𝐍𝐄𝐑' if win else '𝐍𝐎 𝐋𝐔𝐂𝐊'}")
    s.p(f"🎰 <code>[ {face} ]</code>")
    if win:
        s.quote(f"{label} — payout <b>{format_number(win)}</b> coins ({mult}×)")
    else:
        s.p(f"💀 {label}. The machine keeps your {format_number(bet)} coins.")
    s.kv(
        [
            ("🎫 Bet", format_number(bet)),
            ("↔️ Result", f"+{format_number(win - bet)}" if win > bet else f"-{format_number(bet)}"),
            ("💰 Balance", format_number(balance)),
        ]
    )
    view = LiveView.from_update(update)
    await view.show(s, effect="party" if mult >= 5 else ("fire" if win else "poop"))
    if mult >= 10:
        await tgapi.react(context.bot, chat_id, update.message.message_id, "🎉")


def register(application) -> None:
    application.add_handler(CommandHandler("slots", cmd_slots))
    application.add_handler(CommandHandler("casino", cmd_slots))
