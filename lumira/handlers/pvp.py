"""PVP & AI: /roast (streamed savagery), /kill /rob /revive, /ai (streaming)."""
from __future__ import annotations

from telegram import Update
from telegram.constants import ChatType, ParseMode
from telegram.ext import CommandHandler, ContextTypes

from .. import config, tgapi
from ..ai import ai_service
from ..db import db
from ..engine import LiveView, typing
from ..rich import Screen
from ..utils import (
    border_text,
    format_number,
    md_to_html,
    rate_limit_command,
    require_group,
    safe_reply,
    username_of,
)
from .helpers import has_active_shield, resolve_target_user


def _roast_screen(name: str, toast: str, tag: str = "𝐑𝐎𝐀𝐒𝐓 • 𝐒𝐀𝐕𝐀𝐆𝐄") -> Screen:
    s = Screen(tag)
    s.p(f"🔥 <b>@{name}</b>, {toast}")
    s.p("💀 Destroyed!")
    return s


# ------------------------------------------------------------------- /roast
@safe_reply
@require_group
@rate_limit_command("roast")
async def cmd_roast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    attacker = update.effective_user
    chat_id = update.effective_chat.id
    target_user, target_name, target_id = await resolve_target_user(update, context)

    if not target_name:
        await update.message.reply_text(
            border_text(
                "𝐑𝐎𝐀𝐒𝐓 • 𝐔𝐒𝐀𝐆𝐄",
                "❌ Reply to someone or use <code>/roast @username</code> to unleash a savage roast!",
            ),
            parse_mode=ParseMode.HTML,
        )
        return

    if target_user and target_user.id == attacker.id:
        await update.message.reply_text(
            border_text("𝐑𝐎𝐀𝐒𝐓 • 𝐍𝐎𝐓𝐈𝐂𝐄", "🤡 Why roast yourself? Practice self-love!"),
            parse_mode=ParseMode.HTML,
        )
        return

    if target_user and target_user.id == context.bot.id:
        roast_text = await ai_service.roast(context.bot.first_name, "roasting myself")
        s = _roast_screen(context.bot.first_name, roast_text, "𝐑𝐎𝐀𝐒𝐓 • 𝐁𝐀𝐂𝐊𝐅𝐈𝐑𝐄")
        await update.message.reply_text(s.classic_html(), parse_mode=ParseMode.HTML)
        return

    if target_user:
        target_data = await db.get_user_per_group(target_user.id, chat_id)
        if target_data and target_data.get("is_verified_owner") == 1:
            roast_text = await ai_service.roast(attacker.first_name, "tried to roast the group owner")
            s = _roast_screen(username_of(attacker), roast_text, "𝐑𝐎𝐀𝐒𝐓 • 𝐁𝐀𝐂𝐊𝐅𝐈𝐑𝐄")
            await update.message.reply_text(s.classic_html(), parse_mode=ParseMode.HTML)
            return
        if has_active_shield(target_data):
            s = Screen("𝐒𝐇𝐈𝐄𝐋𝐃 • 𝐃𝐄𝐅𝐄𝐍𝐒𝐄")
            s.p(f"🛡️ <b>@{target_name}</b> is protected by an active shield! Your roast bounced back.")
            await update.message.reply_text(s.classic_html(), parse_mode=ParseMode.HTML)
            return

    # streamed roast — the savagery types itself live, then lands 🔥
    view = LiveView.from_update(update)
    stream = ai_service.stream(
        f"Write a savage, playful roast targeting @{target_name}. Under 25 words, emojis ok.",
        persona=(
            "You are a savage, witty roast generator. One short roast only — "
            "playful burns, modern slang, emojicedicted hard, no filler text."
        ),
        max_tokens=140,
    )
    await view.type_stream(
        stream,
        title="roast",
        header_html=f"🔥 <b>Roasting @{target_name}</b>",
        footer_html="\n💀 Destroyed!",
        effect="fire",
    )
    if update.message.reply_to_message:
        await tgapi.react(context.bot, chat_id, update.message.reply_to_message.message_id, "😆")


# -------------------------------------------------------------------- /kill
@safe_reply
@require_group
@rate_limit_command("kill")
async def cmd_kill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text(
            border_text("𝐊𝐈𝐋𝐋 • 𝐔𝐒𝐀𝐆𝐄", "❌ Reply to someone's message with <code>/kill</code> to assassinate them!"),
            parse_mode=ParseMode.HTML,
        )
        return

    target = update.message.reply_to_message.from_user
    attacker = update.effective_user
    chat_id = update.effective_chat.id

    if target.id == context.bot.id:
        await update.message.reply_text(
            border_text("𝐊𝐈𝐋𝐋 • 𝐍𝐎𝐓𝐈𝐂𝐄", "😵 I am an immortal digital entity. You cannot harm me!"),
            parse_mode=ParseMode.HTML,
        )
        return
    if target.id == attacker.id:
        await update.message.reply_text(
            border_text("𝐊𝐈𝐋𝐋 • 𝐍𝐎𝐓𝐈𝐂𝐄", "🤡 You cannot assassinate yourself."),
            parse_mode=ParseMode.HTML,
        )
        return

    target_data = await db.get_user_per_group(target.id, chat_id)

    if target_data and target_data.get("is_verified_owner") == 1:
        await db.update_user_per_group(attacker.id, chat_id, username_of(attacker), set_dead=True)
        s = Screen("𝐀𝐒𝐒𝐀𝐒𝐒𝐈𝐍𝐀𝐓𝐈𝐎𝐍 • 𝐁𝐀𝐂𝐊𝐅𝐈𝐑𝐄")
        s.p(f"⚰️ <b>@{username_of(attacker)}</b> attempted to kill the Group Owner and was <b>instantly executed</b>!")
        await update.message.reply_text(
            s.classic_html(), parse_mode=ParseMode.HTML, message_effect_id=tgapi.effect_or_none("poop")
        )
        return

    if has_active_shield(target_data):
        s = Screen("𝐒𝐇𝐈𝐄𝐋𝐃 • 𝐏𝐑𝐎𝐓𝐄𝐂𝐓𝐈𝐎𝐍")
        s.p(f"🛡️ <b>@{username_of(target)}</b> is shielded! The assassination attempt was deflected.")
        await update.message.reply_text(s.classic_html(), parse_mode=ParseMode.HTML)
        return

    if target_data and target_data.get("is_dead"):
        await update.message.reply_text(
            border_text("𝐊𝐈𝐋𝐋 • 𝐍𝐎𝐓𝐈𝐂𝐄", f"💀 <b>@{username_of(target)}</b> is already dead!"),
            parse_mode=ParseMode.HTML,
        )
        return

    await db.update_user_per_group(target.id, chat_id, username_of(target), set_dead=True)
    await db.add_guild_xp_for_user(attacker.id, config.GUILD_XP_KILL)

    # cinematic kill — 3 frames then the obituary
    view = LiveView.from_update(update)
    await view.open("🎯 Target acquired")
    frames = []
    for step in ("🎯 Locking target…", "🔪 Approaching…", "⚔️ Strike!"):
        s = Screen("𝐀𝐒𝐒𝐀𝐒𝐒𝐈𝐍𝐀𝐓𝐈𝐎𝐍")
        s.p(step)
        frames.append(s)
    final = Screen("𝐀𝐒𝐒𝐀𝐒𝐒𝐈𝐍𝐀𝐓𝐈𝐎𝐍 • 𝐒𝐔𝐂𝐂𝐄𝐒𝐒")
    final.p(f"🔪 <b>@{username_of(attacker)}</b> assassinated <b>@{username_of(target)}</b>!")
    final.p("💀 Rest in peace. <code>/revive</code> or visit <code>/shop</code> to return.")
    frames.append(final)
    await view.animate(frames, interval=0.5)
    await tgapi.react(context.bot, chat_id, update.message.reply_to_message.message_id, "💀")


# --------------------------------------------------------------------- /rob
@safe_reply
@require_group
@rate_limit_command("rob")
async def cmd_rob(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text(
            border_text("𝐑𝐎𝐁 • 𝐔𝐒𝐀𝐆𝐄", "❌ Reply to someone's message with <code>/rob &lt;amount&gt;</code>!"),
            parse_mode=ParseMode.HTML,
        )
        return
    if not context.args or not context.args[0].lstrip("-").isdigit():
        await update.message.reply_text(
            border_text("𝐑𝐎𝐁 • 𝐔𝐒𝐀𝐆𝐄", "❌ Specify an amount: <code>/rob 500</code> (replying to a user)"),
            parse_mode=ParseMode.HTML,
        )
        return
    amount = int(context.args[0])
    if amount <= 0 or amount > 10000:
        await update.message.reply_text(
            border_text("𝐑𝐎𝐁 • 𝐄𝐑𝐑𝐎𝐑", "❌ Amount must be 1–10,000 coins."),
            parse_mode=ParseMode.HTML,
        )
        return

    target = update.message.reply_to_message.from_user
    thief = update.effective_user
    chat_id = update.effective_chat.id

    if target.id == thief.id:
        await update.message.reply_text(
            border_text("𝐑𝐎𝐁 • 𝐍𝐎𝐓𝐈𝐂𝐄", "🤡 You cannot rob yourself."), parse_mode=ParseMode.HTML
        )
        return
    if target.id == context.bot.id:
        await update.message.reply_text(
            border_text("𝐑𝐎𝐁 • 𝐍𝐎𝐓𝐈𝐂𝐄", "😤 I have no physical coins to steal!"), parse_mode=ParseMode.HTML
        )
        return

    target_data = await db.get_user_per_group(target.id, chat_id)
    thief_data = await db.get_user_per_group(thief.id, chat_id)
    if not thief_data:
        await update.message.reply_text(
            border_text("𝐑𝐎𝐁 • 𝐄𝐑𝐑𝐎𝐑", "❌ Chat first to earn your own balance!"), parse_mode=ParseMode.HTML
        )
        return

    if target_data and target_data.get("is_verified_owner") == 1:
        fine = min(amount * 2, thief_data["coins"])
        await db.update_user_per_group(thief.id, chat_id, username_of(thief), coins_delta=-fine)
        await db.update_user_global(thief.id, username_of(thief), coins_delta=-fine)
        s = Screen("𝐇𝐄𝐈𝐒𝐓 • 𝐁𝐀𝐂𝐊𝐅𝐈𝐑𝐄")
        s.p(f"👑 You tried robbing the <b>Group Owner</b> — fined <b>{format_number(fine)} coins</b>.")
        s.kv([("💰 New balance", format_number(max(0, thief_data["coins"] - fine)))])
        await update.message.reply_text(s.classic_html(), parse_mode=ParseMode.HTML)
        return

    if has_active_shield(target_data):
        s = Screen("𝐒𝐇𝐈𝐄𝐋𝐃 • 𝐃𝐄𝐅𝐄𝐍𝐒𝐄")
        s.p(f"🛡️ <b>@{username_of(target)}</b> is protected by a shield! Your heist failed.")
        await update.message.reply_text(s.classic_html(), parse_mode=ParseMode.HTML)
        return

    if target_data and target_data.get("is_dead"):
        await update.message.reply_text(
            border_text("𝐑𝐎𝐁 • 𝐍𝐎𝐓𝐈𝐂𝐄", f"💀 <b>@{username_of(target)}</b> is dead. You cannot rob a ghost."),
            parse_mode=ParseMode.HTML,
        )
        return

    if not target_data or target_data["coins"] < amount:
        await update.message.reply_text(
            border_text("𝐑𝐎𝐁 • 𝐅𝐀𝐈𝐋𝐄𝐃", f"❌ <b>@{username_of(target)}</b> doesn't have {format_number(amount)} coins."),
            parse_mode=ParseMode.HTML,
        )
        return

    success, msg = await db.transfer_coins(
        target.id, thief.id, chat_id, amount, username_of(target), username_of(thief)
    )
    if success:
        await db.add_guild_xp_for_user(thief.id, config.GUILD_XP_ROB)
        s = Screen("𝐇𝐄𝐈𝐒𝐓 • 𝐒𝐔𝐂𝐂𝐄𝐒𝐒")
        s.p(f"💰 You robbed <b>{format_number(amount)} coins</b> from @{username_of(target)}!")
        s.kv([("💰 Your balance", format_number(thief_data["coins"] + amount))])
        await update.message.reply_text(s.classic_html(), parse_mode=ParseMode.HTML)
        await tgapi.react(context.bot, chat_id, update.message.reply_to_message.message_id, "👌")
    else:
        await update.message.reply_text(
            border_text("𝐑𝐎𝐁 • 𝐅𝐀𝐈𝐋𝐄𝐃", f"❌ {msg}"), parse_mode=ParseMode.HTML
        )


# ------------------------------------------------------------------ /revive
@safe_reply
@require_group
async def cmd_revive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id, chat_id = user.id, update.effective_chat.id
    username = username_of(user)

    if context.args:
        target_name = context.args[0].lstrip("@")
        target_id = await db.find_user_by_username(chat_id, target_name)
        if not target_id:
            await update.message.reply_text(
                border_text("𝐑𝐄𝐕𝐈𝐕𝐄 • 𝐄𝐑𝐑𝐎𝐑", f"❌ User @{target_name} not found in this group."),
                parse_mode=ParseMode.HTML,
            )
            return
        target_data = await db.get_user_per_group(target_id, chat_id)
        if not target_data or not target_data.get("is_dead"):
            await update.message.reply_text(
                border_text("𝐑𝐄𝐕𝐈𝐕𝐄 • 𝐍𝐎𝐓𝐈𝐂𝐄", f"❌ @{target_name} is already alive and well."),
                parse_mode=ParseMode.HTML,
            )
            return
        self_data = await db.get_user_per_group(user_id, chat_id)
        if not self_data or self_data["coins"] < config.REVIVE_OTHER_COST:
            await update.message.reply_text(
                border_text(
                    "𝐑𝐄𝐕𝐈𝐕𝐄 • 𝐈𝐍𝐒𝐔𝐅𝐅𝐈𝐂𝐈𝐄𝐍𝐓",
                    f"❌ You need {format_number(config.REVIVE_OTHER_COST)} coins to revive another member.",
                ),
                parse_mode=ParseMode.HTML,
            )
            return
        await db.update_user_per_group(target_id, chat_id, target_name, set_dead=False)
        await db.update_user_per_group(user_id, chat_id, username, coins_delta=-config.REVIVE_OTHER_COST)
        await db.update_user_global(user_id, username, coins_delta=-config.REVIVE_OTHER_COST)
        await db.add_guild_xp_for_user(user_id, config.GUILD_XP_REVIVE)
        s = Screen("𝐑𝐄𝐒𝐔𝐑𝐑𝐄𝐂𝐓𝐈𝐎𝐍 • 𝐒𝐔𝐂𝐂𝐄𝐒𝐒")
        s.p(f"💪 <b>@{username}</b> revived <b>@{target_name}</b> from the dead!")
        s.kv([("💰 Cost", format_number(config.REVIVE_OTHER_COST))])
        view = LiveView.from_update(update)
        await view.show(s, effect="party")
    else:
        user_data = await db.get_user_per_group(user_id, chat_id)
        if not user_data:
            await update.message.reply_text(
                border_text("𝐑𝐄𝐕𝐈𝐕𝐄 • 𝐄𝐑𝐑𝐎𝐑", "❌ Chat first to earn coins."), parse_mode=ParseMode.HTML
            )
            return
        if not user_data.get("is_dead"):
            await update.message.reply_text(
                border_text("𝐑𝐄𝐕𝐈𝐕𝐄 • 𝐍𝐎𝐓𝐈𝐂𝐄", "❌ You are already alive!"), parse_mode=ParseMode.HTML
            )
            return
        if user_data["coins"] < config.REVIVE_SELF_COST:
            await update.message.reply_text(
                border_text(
                    "𝐑𝐄𝐕𝐈𝐕𝐄 • 𝐈𝐍𝐒𝐔𝐅𝐅𝐈𝐂𝐈𝐄𝐍𝐓",
                    f"❌ You need {format_number(config.REVIVE_SELF_COST)} coins to revive yourself.",
                ),
                parse_mode=ParseMode.HTML,
            )
            return
        await db.update_user_per_group(user_id, chat_id, username, coins_delta=-config.REVIVE_SELF_COST, set_dead=False)
        await db.update_user_global(user_id, username, coins_delta=-config.REVIVE_SELF_COST)
        await db.add_guild_xp_for_user(user_id, config.GUILD_XP_REVIVE)
        s = Screen("𝐑𝐄𝐒𝐔𝐑𝐑𝐄𝐂𝐓𝐈𝐎𝐍 • 𝐒𝐔𝐂𝐂𝐄𝐒𝐒")
        s.p("💪 <b>Self Resurrection Complete!</b> Back to action.")
        s.kv([("💰 Remaining", format_number(user_data["coins"] - config.REVIVE_SELF_COST))])
        view = LiveView.from_update(update)
        await view.show(s, effect="party")


# ---------------------------------------------------------------------- /ai
@safe_reply
@rate_limit_command("ai")
async def cmd_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(context.args)
    if not prompt and update.message.reply_to_message and update.message.reply_to_message.text:
        # replying to a message with bare /ai → comment on it
        prompt = update.message.reply_to_message.text[:1000]
        context_text = ""
    else:
        context_text = ""
        if update.message.reply_to_message and update.message.reply_to_message.text:
            context_text = update.message.reply_to_message.text[:600]
    if not prompt:
        await update.message.reply_text(
            border_text("𝐀𝐈 • 𝐔𝐒𝐀𝐆𝐄", "❌ Usage: <code>/ai &lt;question&gt;</code> — or reply to any message with <code>/ai</code>!"),
            parse_mode=ParseMode.HTML,
        )
        return

    chat = update.effective_chat
    await typing(context.bot, chat.id)
    view = LiveView.from_update(update)
    stream = ai_service.stream(prompt, context=context_text)
    try:
        await view.type_stream(
            stream,
            title="ai",
            header_html="🤖 <b>𝓛𝓾𝓶𝓲𝓻𝓪 AI</b>",
            draft=(chat.type == ChatType.PRIVATE),
            interval=1.15,
        )
    except Exception as e:
        from ..utils import logger

        logger.debug(f"stream fallback: {e}")
        response = await ai_service.ask(prompt, context_text)
        await update.message.reply_text(
            border_text("𝐋𝐔𝐌𝐈𝐑𝐀 • 𝐀𝐈 𝐀𝐒𝐒𝐈𝐒𝐓𝐀𝐍𝐓", md_to_html(response)),
            parse_mode=ParseMode.HTML,
        )


def register(application) -> None:
    application.add_handler(CommandHandler("roast", cmd_roast))
    application.add_handler(CommandHandler("kill", cmd_kill))
    application.add_handler(CommandHandler("rob", cmd_rob))
    application.add_handler(CommandHandler("revive", cmd_revive))
    application.add_handler(CommandHandler("ai", cmd_ai))
