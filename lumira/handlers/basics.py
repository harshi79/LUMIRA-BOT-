"""Basics: /start (+ deep links), /help, navigation dashboard callbacks."""
from __future__ import annotations

from telegram import Update
from telegram.constants import ChatType, ParseMode
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from .. import config, keyboards
from ..db import db
from ..engine import LiveView
from ..rich import Screen
from ..utils import format_number, safe_reply, username_of
from . import screens


def home_screen(bot_username: str, first_name: str) -> Screen:
    s = Screen("𝓛𝓾𝓶𝓲𝓻𝓪 • 𝐂𝐎𝐌𝐌𝐀𝐍𝐃 𝐂𝐄𝐍𝐓𝐄𝐑", subtitle=f"Welcome back, {first_name}")
    s.quote("The smoothest group experience on Telegram — levels, economy, guild wars & an AI that never sleeps.", cite="𝓛𝓾𝓶𝓲𝓻𝓪 v4 NEBULA")
    s.h("⚡ Core Loop", 2)
    s.items(
        [
            ("", "<b>Chat</b> — every message is +10 XP (auto)"),
            ("", "<b>Daily</b> — /daily keeps your streak alive 🔥"),
            ("", "<b>Fight</b> — /roast /kill /rob your rivals"),
            ("", "<b>Enlist</b> — /join_guild & conquer leaderboards"),
        ]
    )
    s.h("🎛 Quick Facts", 2)
    s.kv(
        [
            ("⚡ Level up", f"{format_number(config.XP_PER_LEVEL)} XP"),
            ("🛡️ Shield", f"{format_number(config.SHIELD_COST)} coins • {config.SHIELD_DURATION_HOURS}h"),
            ("💰 Daily", f"{format_number(config.DAILY_COINS)} coins • {config.DAILY_COOLDOWN_HOURS}h"),
            ("🎰 Slots", f"bet {config.SLOTS_MIN_BET}–{format_number(config.SLOTS_MAX_BET)}"),
        ]
    )
    return s


def help_screen() -> Screen:
    s = Screen("𝓛𝓾𝓶𝓲𝓻𝓪 • 𝐇𝐄𝐋𝐏 𝐂𝐄𝐍𝐓𝐄𝐑")
    s.p("👋 Select a category below — everything is one tap away and <b>this message morphs</b> as you browse.")
    s.h("⚙️ Mechanics", 2)
    s.kv(
        [
            ("⚡ Level Up", f"{format_number(config.XP_PER_LEVEL)} XP per level"),
            ("🛡️ Shield", f"{format_number(config.SHIELD_COST)} coins ({config.SHIELD_DURATION_HOURS}h)"),
            ("💰 Daily Reward", f"{format_number(config.DAILY_COINS)} coins every {config.DAILY_COOLDOWN_HOURS}h"),
            ("🔥 Streaks", f"+{format_number(config.STREAK_BONUS_COINS)} every {config.STREAK_BONUS_EVERY} days"),
        ]
    )
    return s


def help_user_page() -> Screen:
    s = Screen("𝐇𝐄𝐋𝐏 • 𝐔𝐒𝐄𝐑 & 𝐄𝐂𝐎𝐍𝐎𝐌𝐘")
    s.h("👤 Commands", 2)
    s.kv(
        [
            ("/rank", "profile & XP progress"),
            ("/daily", "claim daily coins + streak"),
            ("/scratch", "animated scratch card"),
            ("/shop", "shields, XP, lottery, revive"),
            ("/slots &lt;bet&gt;", "native slot machine 🎰"),
            ("/gift (reply)", "send luxury gifts"),
            ("/mygifts", "view gifts received"),
            ("/pay (reply) &lt;amt&gt;", "transfer coins safely"),
            ("/ai &lt;question&gt;", "streaming AI assistant"),
        ]
    )
    return s


def help_pvp_page() -> Screen:
    s = Screen("𝐇𝐄𝐋𝐏 • 𝐏𝐕𝐏 & 𝐅𝐔𝐍")
    s.h("⚔️ Combat", 2)
    s.kv(
        [
            ("/roast @user", "AI-powered savage roast"),
            ("/kill (reply)", "assassinate a member"),
            ("/rob &lt;amt&gt; (reply)", "steal coins"),
            ("/revive [@user]", "back from the dead"),
        ]
    )
    s.p("\n💡 <i>Tip: Buy a shield (/shop) to block roasts, robs and kills!</i>")
    return s


def help_guild_page() -> Screen:
    s = Screen("𝐇𝐄𝐋𝐏 • 𝐆𝐔𝐈𝐋𝐃 𝐒𝐘𝐒𝐓𝐄𝐌")
    s.kv(
        [
            ("/join_guild &lt;name&gt;", "join a guild"),
            ("/leave_guild", "leave current guild"),
            ("/myguild", "your guild's status"),
            ("/guild_leaderboard", "top XP guilds"),
            ("/guild_members", "member roster"),
            ("/guild_info &lt;name&gt;", "inspect any guild"),
        ]
    )
    s.p("\n⚡ <i>Every message you send contributes XP to your guild!</i>")
    return s


def help_group_page() -> Screen:
    s = Screen("𝐇𝐄𝐋𝐏 • 𝐋𝐄𝐀𝐃𝐄𝐑𝐁𝐎𝐀𝐑𝐃𝐒")
    s.kv(
        [
            ("/leaderboard", "Top 10 global XP masters"),
            ("/riches", "Top 10 global millionaires"),
            ("/grpleaderboard", "Top 10 group XP elite"),
            ("/grpriches", "Top 10 group coin kings"),
        ]
    )
    return s


def help_casino_page() -> Screen:
    s = Screen("𝐇𝐄𝐋𝐏 • 𝐂𝐀𝐒𝐈𝐍𝐎")
    s.h("🎰 Slots — /slots &lt;bet&gt;", 2)
    s.kv(
        [
            ("777", "10× jackpot"),
            ("Any triple", "5× win"),
            ("Any 7 in reels", "2× win"),
        ]
    )
    s.p("\n🎟️ Lottery tickets available in /shop — instant scratch animation.")
    return s


def help_owner_page() -> Screen:
    s = Screen("𝐇𝐄𝐋𝐏 • 𝐎𝐖𝐍𝐄𝐑 & 𝐀𝐃𝐌𝐈𝐍")
    s.kv(
        [
            ("/analytics", "group statistics"),
            ("/members", "member telemetry"),
            ("/top", "quick XP leaderboard"),
            ("/addcoins (reply)", "grant coins"),
            ("/removecoins (reply)", "deduct coins"),
            ("/stats", "all monitored groups"),
            ("/broadcast (DM)", "global announcement"),
        ]
    )
    return s


# ----------------------------------------------------------------------------
# Handlers
# ----------------------------------------------------------------------------
@safe_reply
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    username = username_of(user)
    await db.update_user_global(user.id, username)

    bot_username = context.bot.username

    # Deep links — /start help / profile / shop / guilds
    if context.args and update.effective_chat.type == ChatType.PRIVATE:
        dest = context.args[0].lower()
        view = LiveView.from_update(update)
        if dest == "help":
            await view.open("Opening help")
            await view.show(help_screen(), markup=keyboards.help_categories())
            return
        if dest == "profile":
            await view.open("Loading profile")
            await view.show(await screens.profile_screen(user.id, username), markup=keyboards.back_home())
            return
        if dest == "shop":
            from . import economy

            await economy.cmd_shop(update, context)
            return
        if dest == "guilds":
            await view.open("Loading guilds")
            await view.show(await screens.guilds_lb_screen(), markup=keyboards.back_home())
            return

    if update.effective_chat.type == ChatType.PRIVATE:
        s = Screen("𝓛𝓤𝓜𝓘𝓡𝓐 • 𝐍𝐄𝐁𝐔𝐋𝐀", subtitle=f"Hello, {user.first_name} — the Ultimate Group Master")
        s.quote(
            "XP levels. Coin economy. Guild wars. Savage AI. Streaming replies. Live-updating panels. One bot, zero spam.",
            cite="v4 — reconstructed",
        )
        s.h("🌟 Installed Systems", 2)
        s.items(
            [
                ("", "<b>Economy & Shop</b> — coins, shields, lottery, streaks"),
                ("", "<b>RPG Levels</b> — 70 levels with custom emblems"),
                ("", "<b>Guild Wars</b> — alliances & leaderboards"),
                ("", "<b>AI Core</b> — savage roasts + streaming Q&A"),
                ("", "<b>Casino</b> — native 🎰 slot machine duels"),
            ],
            checked=[True, True, True, True, True],
        )
        view = LiveView.from_update(update)
        await view.show(s, markup=keyboards.dashboard(bot_username), prefer_rich=True, effect="party")
    else:
        s = Screen("𝓛𝓤𝓜𝓘𝓡𝓐 • 𝐆𝐑𝐎𝐔𝐏 𝐀𝐂𝐓𝐈𝐕𝐄")
        s.p(f"👋 Greetings, <b>{user.first_name}</b>!")
        s.p(f"✨ 𝓛𝓾𝓶𝓲𝓻𝓪 is actively monitoring <b>{update.effective_chat.title}</b>.")
        s.items(
            [
                ("", "💬 Chat to earn XP & Coins automatically"),
                ("", "📚 /help — open the command center"),
            ]
        )
        await update.message.reply_text(
            s.classic_html(),
            reply_markup=keyboards.activation(bot_username),
            parse_mode=ParseMode.HTML,
        )


@safe_reply
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    view = LiveView.from_update(update)
    await view.open("Opening help")
    await view.show(help_screen(), markup=keyboards.help_categories())


@safe_reply
async def cb_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, _, target = (query.data or "").partition(":")
    user = query.from_user
    username = username_of(user)
    view = LiveView.from_query(query)
    bot_username = context.bot.username

    routes = {
        "home": lambda: (home_screen(bot_username, user.first_name), keyboards.dashboard(bot_username)),
        "help": lambda: (help_screen(), keyboards.help_categories()),
        "help_user": lambda: (help_user_page(), keyboards.back("nav:help")),
        "help_pvp": lambda: (help_pvp_page(), keyboards.back("nav:help")),
        "help_guild": lambda: (help_guild_page(), keyboards.back("nav:help")),
        "help_group": lambda: (help_group_page(), keyboards.back("nav:help")),
        "help_casino": lambda: (help_casino_page(), keyboards.back("nav:help")),
        "help_owner": lambda: (help_owner_page(), keyboards.back("nav:help")),
    }

    if target in routes:
        screen, markup = routes[target]()
        await view.show(screen, markup=markup)
        return

    if target == "profile":
        await view.show(await screens.profile_screen(user.id, username), markup=keyboards.back_home())
    elif target == "lb":
        await view.show(await screens.global_lb_screen(), markup=keyboards.back_home())
    elif target == "riches":
        await view.show(await screens.global_riches_screen(), markup=keyboards.back_home())
    elif target == "guilds":
        await view.show(await screens.guilds_lb_screen(), markup=keyboards.back_home())
    elif target == "grptop":
        chat = query.message.chat
        if chat and chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
            await view.show(await screens.group_lb_screen(chat.id))
        else:
            await show_toast(query, "This works inside groups only!")
    else:
        await view.show(home_screen(bot_username, user.first_name), markup=keyboards.dashboard(bot_username))


async def show_toast(query, text: str, alert: bool = True) -> None:
    try:
        await query.answer(text=text, show_alert=alert)
    except Exception:
        pass


def register(application) -> None:
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("menu", cmd_help))
    application.add_handler(CallbackQueryHandler(cb_nav, pattern=r"^nav:"))
