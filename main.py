#!/usr/bin/env python3
"""
Lumira v4 "Nebula" — entry point.

Modular rebuild of the Group Master Elite bot with the newest free Bot API
features (9.3 / 10.1 / 10.2): live-morphing panels, Rich Messages, Ephemeral
replies, native AI streaming, message effects & reactions, casino dice.

Run modes:
    polling  → python main.py          (default when WEBHOOK_URL is unset)
    webhook  → set WEBHOOK_URL (+ PORT / WEBHOOK_LISTEN / WEBHOOK_SECRET)
"""
from __future__ import annotations

import sys

from telegram import BotCommand, BotCommandScopeChat, Update
from telegram.ext import ApplicationBuilder

from lumira import config, tgapi
from lumira.db import db
from lumira.handlers import register_all
from lumira.utils import logger, pending_manager

# ----------------------------------------------------------------------------
# Bot menu & profile text (free — set via Bot API on every boot)
# ----------------------------------------------------------------------------
USER_COMMANDS = [
    BotCommand("start", "✨ Open the Lumira dashboard"),
    BotCommand("help", "📚 Interactive command center"),
    BotCommand("rank", "🆙 Your profile card"),
    BotCommand("daily", "💰 Claim daily coins + streak"),
    BotCommand("scratch", "🎫 Animated scratch card"),
    BotCommand("slots", "🎰 Native slot machine"),
    BotCommand("shop", "🛒 Shields, XP boost, lottery"),
    BotCommand("gift", "🎁 Send gifts (reply)"),
    BotCommand("mygifts", "🎁 Your received gifts"),
    BotCommand("pay", "💸 Transfer coins (reply)"),
    BotCommand("roast", "🔥 Savage AI roast"),
    BotCommand("kill", "🔪 Assassinate (reply)"),
    BotCommand("rob", "💰 Steal coins (reply)"),
    BotCommand("revive", "💪 Return from the dead"),
    BotCommand("ai", "🤖 Streaming AI assistant"),
    BotCommand("leaderboard", "🏆 Global XP top 10"),
    BotCommand("riches", "💎 Global coin top 10"),
    BotCommand("grpleaderboard", "🏆 Group XP top 10"),
    BotCommand("grpriches", "💎 Group coin top 10"),
    BotCommand("join_guild", "🏰 Join a guild"),
    BotCommand("leave_guild", "🏰 Leave your guild"),
    BotCommand("myguild", "🏰 Your guild status"),
    BotCommand("guild_leaderboard", "🏰 Top guilds"),
    BotCommand("guild_info", "🏰 Inspect a guild"),
]

OWNER_COMMANDS = USER_COMMANDS + [
    BotCommand("broadcast", "📢 Global announcement"),
    BotCommand("stats", "📊 Monitored groups"),
    BotCommand("newguild", "🏰 Create a guild"),
    BotCommand("delguild", "🏰 Delete a guild"),
    BotCommand("guild_stats", "🏰 Deep guild analytics"),
]

BOT_DESCRIPTION = (
    "𝓛𝓾𝓶𝓲𝓻𝓪 — the Ultimate Group Master.\n\n"
    "• RPG levels & XP (70 levels, custom emblems)\n"
    "• Coin economy: daily streaks, scratch cards, casino slots, loot heists\n"
    "• Guild wars & global leaderboards\n"
    "• Savage AI roasts + streaming AI answers\n"
    "• Live-updating panels — one message that morphs, zero spam\n\n"
    "Add me to a group and promote me to Admin for the full experience!"
)
BOT_SHORT_DESCRIPTION = "⚡ Levels • Economy • Guild Wars • Streaming AI — the smoothest group bot on Telegram."


async def post_init(application) -> None:
    await db.initialize()
    await db.init_schema()
    await tgapi.caps.probe(application.bot)

    # Menu + profile
    try:
        await application.bot.set_my_commands(USER_COMMANDS)
        await application.bot.set_my_commands(
            OWNER_COMMANDS, scope=BotCommandScopeChat(chat_id=config.GLOBAL_OWNER_ID)
        )
        await application.bot.set_my_description(description=BOT_DESCRIPTION)
        await application.bot.set_my_short_description(short_description=BOT_SHORT_DESCRIPTION)
    except Exception as e:
        logger.warning(f"profile setup skipped: {e}")

    # Pending-state sweeper
    if application.job_queue:
        application.job_queue.run_repeating(lambda _ctx: pending_manager.cleanup_pass(), interval=config.PENDING_CLEANUP_INTERVAL, first=10)

    logger.info("𝓛𝓾𝓶𝓲𝓻𝓪 v4 initialized — all systems nominal")


async def post_shutdown(application) -> None:
    await db.close()
    logger.info("𝓛𝓾𝓶𝓲𝓻𝓪 shutdown complete")


def main() -> None:
    if not config.BOT_TOKEN:
        logger.error("BOT_TOKEN not set!")
        sys.exit(1)
    if not config.DATABASE_URL:
        logger.error("DATABASE_URL not set!")
        sys.exit(1)

    application = (
        ApplicationBuilder()
        .token(config.BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    register_all(application)

    if config.RUN_MODE == "polling" or not config.WEBHOOK_URL:
        logger.info("Starting 𝓛𝓾𝓶𝓲𝓻𝓪 in POLLING mode…")
        application.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
    else:
        logger.info(f"Starting webhook on {config.WEBHOOK_LISTEN}:{config.PORT} → {config.WEBHOOK_URL}")
        application.run_webhook(
            listen=config.WEBHOOK_LISTEN,
            port=config.PORT,
            url_path=config.BOT_TOKEN,
            webhook_url=f"{config.WEBHOOK_URL}/{config.BOT_TOKEN}",
            secret_token=config.WEBHOOK_SECRET,
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES,
        )


if __name__ == "__main__":
    main()
