"""Guild system: create/delete/list/join/leave/info/members/stats/transfer/rename."""
from __future__ import annotations

import re

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from .. import config, keyboards
from ..db import db
from ..engine import LiveView
from ..rich import Screen
from ..utils import border_text, esc, format_number, logger, safe_reply, username_of
from . import screens

NAME_RE = re.compile(r"^[a-zA-Z0-9 ]+$")


def _guild_hero(guild: dict, members: list, user_id: int | None = None) -> Screen:
    level, need = db.guild_next_level(guild["total_xp"])
    s = Screen(f"🏰 {esc(guild['name'])}", subtitle="𝐆𝐔𝐈𝐋𝐃 𝐒𝐓𝐀𝐓𝐔𝐒")
    s.divider()
    s.kv(
        [
            ("📊 Level", str(level)),
            ("✨ Total XP", format_number(guild["total_xp"])),
            ("👥 Members", f"{len(members)} / {config.MAX_GUILD_MEMBERS}"),
        ]
    )
    if need:
        from ..utils import create_progress_bar

        next_thresh = guild["total_xp"] + need
        s.p(f"📈 <code>{create_progress_bar(guild['total_xp'], next_thresh)}</code> <i>{format_number(need)} XP to lvl {level + 1}</i>")
    else:
        s.quote("☬ Maximum guild prestige reached", cite="𝓛𝓾𝓶𝓲𝓻𝓪")
    if user_id:
        contrib = next((m["contribution_xp"] for m in members if m["user_id"] == user_id), 0)
        joined = next((m["joined_at"] for m in members if m["user_id"] == user_id), None)
        s.h("📈 Your Record", 2)
        s.kv(
            [
                ("✨ Contribution", f"{format_number(contrib)} XP"),
                ("📅 Enlisted", joined.strftime("%Y-%m-%d") if joined else "N/A"),
            ]
        )
    return s


@safe_reply
async def cmd_newguild(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.GLOBAL_OWNER_ID:
        await update.message.reply_text(
            border_text("𝐆𝐔𝐈𝐋𝐃𝐒 • 𝐀𝐂𝐂𝐄𝐒𝐒", "❌ Only the Global Master can create official guilds."),
            parse_mode=ParseMode.HTML,
        )
        return
    if not context.args:
        await update.message.reply_text(
            border_text("𝐆𝐔𝐈𝐋𝐃𝐒 • 𝐔𝐒𝐀𝐆𝐄", "❌ Usage: <code>/newguild &lt;name&gt;</code>"),
            parse_mode=ParseMode.HTML,
        )
        return
    name = " ".join(context.args).strip()
    if len(name) > 30 or not NAME_RE.match(name):
        await update.message.reply_text(
            border_text("𝐆𝐔𝐈𝐋𝐃𝐒 • 𝐄𝐑𝐑𝐎𝐑", "❌ 1–30 alphanumeric characters/spaces only."),
            parse_mode=ParseMode.HTML,
        )
        return
    try:
        if config.GUILD_CREATION_COST > 0:
            user_data = await db.get_user_global(config.GLOBAL_OWNER_ID)
            if not user_data or user_data["total_coins"] < config.GUILD_CREATION_COST:
                await update.message.reply_text(
                    border_text("𝐆𝐔𝐈𝐋𝐃𝐒 • 𝐂𝐎𝐒𝐓", f"❌ You need {format_number(config.GUILD_CREATION_COST)} coins."),
                    parse_mode=ParseMode.HTML,
                )
                return
            await db.update_user_global(
                config.GLOBAL_OWNER_ID, username_of(update.effective_user), coins_delta=-config.GUILD_CREATION_COST
            )
        guild_id = await db.create_guild(name, creator_id=config.GLOBAL_OWNER_ID)
        s = Screen("𝐆𝐔𝐈𝐋𝐃 𝐂𝐑𝐄𝐀𝐓𝐄𝐃")
        s.kv(
            [
                ("🏰 Name", esc(name)),
                ("🆔 Guild ID", str(guild_id)),
                ("👑 Created by", f"@{username_of(update.effective_user)}"),
            ]
        )
        view = LiveView.from_update(update)
        await view.show(s, effect="party")
    except ValueError as e:
        await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃𝐒 • 𝐄𝐑𝐑𝐎𝐑", f"❌ {e}"), parse_mode=ParseMode.HTML)


@safe_reply
async def cmd_delguild(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.GLOBAL_OWNER_ID:
        await update.message.reply_text(
            border_text("𝐆𝐔𝐈𝐋𝐃𝐒 • 𝐀𝐂𝐂𝐄𝐒𝐒", "❌ Only the Global Master can delete guilds."),
            parse_mode=ParseMode.HTML,
        )
        return
    if not context.args:
        await update.message.reply_text(
            border_text("𝐆𝐔𝐈𝐋𝐃𝐒 • 𝐔𝐒𝐀𝐆𝐄", "❌ Usage: <code>/delguild &lt;name&gt;</code>"),
            parse_mode=ParseMode.HTML,
        )
        return
    name = " ".join(context.args).strip()
    guild = await db.get_guild_by_name(name)
    if not guild:
        await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃𝐒 • 𝐄𝐑𝐑𝐎𝐑", "❌ Guild not found."), parse_mode=ParseMode.HTML)
        return
    s = Screen("𝐆𝐔𝐈𝐋𝐃 • 𝐂𝐎𝐍𝐅𝐈𝐑𝐌 𝐃𝐄𝐋𝐄𝐓𝐈𝐎𝐍")
    s.p(f"⚠️ Permanently delete <b>{esc(name)}</b>? All member records will be cleared.")
    await update.message.reply_text(
        s.classic_html(),
        reply_markup=keyboards.confirm(f"delguild:{guild['guild_id']}", "delguildcancel", "✅ YES, Delete"),
        parse_mode=ParseMode.HTML,
    )


@safe_reply
async def cb_delguild(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    view = LiveView.from_query(query)
    if query.data == "delguildcancel":
        await query.answer("Cancelled")
        s = Screen("𝐆𝐔𝐈𝐋𝐃 • 𝐂𝐀𝐍𝐂𝐄𝐋𝐋𝐄𝐃")
        s.p("❌ Deletion aborted.")
        await view.show(s)
        return
    if query.from_user.id != config.GLOBAL_OWNER_ID:
        await query.answer("Owner only.", show_alert=True)
        return
    guild_id = int(query.data.split(":")[1])
    await db.delete_guild(guild_id, admin_id=query.from_user.id)
    await query.answer("Guild deleted.")
    s = Screen("𝐆𝐔𝐈𝐋𝐃 • 𝐃𝐄𝐋𝐄𝐓𝐄𝐃")
    s.p("✅ Guild permanently deleted.")
    await view.show(s)


@safe_reply
async def cmd_guilds_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.GLOBAL_OWNER_ID:
        await update.message.reply_text(
            border_text("𝐆𝐔𝐈𝐋𝐃𝐒 • 𝐀𝐂𝐂𝐄𝐒𝐒", "❌ Only the Global Master can view the full registry."),
            parse_mode=ParseMode.HTML,
        )
        return
    guilds = await db.list_guilds()
    s = Screen("𝐀𝐋𝐋 𝐑𝐄𝐆𝐈𝐒𝐓𝐄𝐑𝐄𝐃 𝐆𝐔𝐈𝐋𝐃𝐒")
    if not guilds:
        s.p("No guilds created yet.")
    else:
        s.p(f"📋 <b>Total: {len(guilds)}</b>")
        s.items(
            [
                ("🏰", f"<b>{esc(g['name'])}</b> (ID {g['guild_id']}) — 👥 {g['member_count']} • {format_number(g['total_xp'])} XP")
                for g in guilds
            ]
        )
    view = LiveView.from_update(update)
    await view.open("Loading registry")
    await view.show(s)


@safe_reply
async def cmd_join_guild(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    username = username_of(user)
    if not context.args:
        await update.message.reply_text(
            border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐔𝐒𝐀𝐆𝐄", "❌ Usage: <code>/join_guild &lt;guild_name&gt;</code>"),
            parse_mode=ParseMode.HTML,
        )
        return
    name = " ".join(context.args).strip()
    guild = await db.get_guild_by_name(name)
    if not guild:
        await update.message.reply_text(
            border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐄𝐑𝐑𝐎𝐑", f"❌ Guild <b>'{esc(name)}'</b> not found. Check /guild_leaderboard!"),
            parse_mode=ParseMode.HTML,
        )
        return
    success, msg = await db.add_user_to_guild(user.id, guild["guild_id"], username)
    s = Screen("𝐉𝐎𝐈𝐍𝐄𝐃 𝐆𝐔𝐈𝐋𝐃 • 𝐒𝐔𝐂𝐂𝐄𝐒𝐒" if success else "𝐆𝐔𝐈𝐋𝐃 • 𝐉𝐎𝐈𝐍 𝐅𝐀𝐈𝐋𝐄𝐃")
    if success:
        s.p(f"✅ <b>You joined {esc(guild['name'])}!</b>")
        s.p("Every message you send now feeds your guild's XP pool! ⚡")
        view = LiveView.from_update(update)
        await view.show(s, effect="party")
    else:
        s.p(f"❌ {msg}")
        await update.message.reply_text(s.classic_html(), parse_mode=ParseMode.HTML)


@safe_reply
async def cmd_leave_guild(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    guild = await db.get_user_guild(user_id)
    if not guild:
        await update.message.reply_text(
            border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐍𝐎𝐓𝐈𝐂𝐄", "❌ You are not in any guild."),
            parse_mode=ParseMode.HTML,
        )
        return
    s = Screen("𝐆𝐔𝐈𝐋𝐃 • 𝐂𝐎𝐍𝐅𝐈𝐑𝐌 𝐋𝐄𝐀𝐕𝐄")
    s.p(f"⚠️ Leave <b>{esc(guild['name'])}</b>? A 24h rejoin cooldown applies.")
    await update.message.reply_text(
        s.classic_html(),
        reply_markup=keyboards.confirm(f"leave:{guild['guild_id']}", "leavecancel", "✅ YES, Leave"),
        parse_mode=ParseMode.HTML,
    )


@safe_reply
async def cb_leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    view = LiveView.from_query(query)
    if query.data == "leavecancel":
        await query.answer("Cancelled")
        s = Screen("𝐆𝐔𝐈𝐋𝐃 • 𝐂𝐀𝐍𝐂𝐄𝐋𝐋𝐄𝐃")
        s.p("❌ You remain in your guild.")
        await view.show(s)
        return
    guild_id = int(query.data.split(":")[1])
    guild = await db.get_user_guild(user_id)
    if not guild or guild["guild_id"] != guild_id:
        await query.answer("You are no longer in that guild.", show_alert=True)
        return
    success, msg = await db.remove_user_from_guild(user_id)
    await query.answer()
    s = Screen("𝐆𝐔𝐈𝐋𝐃 • 𝐋𝐄𝐅𝐓" if success else "𝐆𝐔𝐈𝐋𝐃 • 𝐄𝐑𝐑𝐎𝐑")
    s.p("✅ Left the guild successfully." if success else f"❌ {msg}")
    await view.show(s)


@safe_reply
async def cmd_myguild(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    guild = await db.get_user_guild(user_id)
    if not guild:
        await update.message.reply_text(
            border_text("𝐘𝐎𝐔𝐑 𝐆𝐔𝐈𝐋𝐃", "❌ Not enlisted! <code>/join_guild &lt;name&gt;</code>"),
            parse_mode=ParseMode.HTML,
        )
        return
    members = await db.get_guild_members(guild["guild_id"])
    view = LiveView.from_update(update)
    await view.open("Loading guild")
    await view.show(_guild_hero(guild, members, user_id))


@safe_reply
async def cmd_guild_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    view = LiveView.from_update(update)
    await view.open("Ranking guilds")
    await view.show(await screens.guilds_lb_screen(), effect="fire")


@safe_reply
async def cmd_guild_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    guild = await db.get_user_guild(user_id)
    if not guild:
        await update.message.reply_text(
            border_text("𝐆𝐔𝐈𝐋𝐃 𝐌𝐄𝐌𝐁𝐄𝐑𝐒", "❌ You are not in any guild."),
            parse_mode=ParseMode.HTML,
        )
        return
    members = await db.get_guild_members(guild["guild_id"])
    s = Screen(f"🏰 {esc(guild['name'])} • 𝐑𝐎𝐒𝐓𝐄𝐑")
    if not members:
        s.p("❌ No members found.")
    else:
        rows = []
        for i, m in enumerate(members[:30]):
            rows.append((config.MEDALS[i] if i < len(config.MEDALS) else f"{i+1}.", f"@{esc(m['username'])} — <b>{format_number(m['contribution_xp'])} XP</b>"))
        s.items(rows)
        if len(members) > 30:
            s.p(f"\n<i>…and {len(members) - 30} more.</i>")
    view = LiveView.from_update(update)
    await view.open("Loading roster")
    await view.show(s)


@safe_reply
async def cmd_guild_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐈𝐍𝐅𝐎", "❌ Usage: <code>/guild_info &lt;guild_name&gt;</code>"),
            parse_mode=ParseMode.HTML,
        )
        return
    name = " ".join(context.args).strip()
    guild = await db.get_guild_by_name(name)
    if not guild:
        await update.message.reply_text(
            border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐈𝐍𝐅𝐎", f"❌ Guild <b>'{esc(name)}'</b> not found."),
            parse_mode=ParseMode.HTML,
        )
        return
    members = await db.get_guild_members(guild["guild_id"])
    view = LiveView.from_update(update)
    await view.open("Inspecting guild")
    s = _guild_hero(guild, members)
    s.p(f"📅 <b>Founded:</b> {guild['created_at'].strftime('%Y-%m-%d') if guild.get('created_at') else 'N/A'}")
    await view.show(s)


@safe_reply
async def cmd_transfer_guild(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.GLOBAL_OWNER_ID:
        await update.message.reply_text(
            border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐓𝐑𝐀𝐍𝐒𝐅𝐄𝐑", "❌ Only the Global Master."),
            parse_mode=ParseMode.HTML,
        )
        return
    if len(context.args) < 2:
        await update.message.reply_text(
            border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐓𝐑𝐀𝐍𝐒𝐅𝐄𝐑", "❌ Usage: <code>/transfer_guild &lt;name&gt; &lt;new_owner_username&gt;</code>"),
            parse_mode=ParseMode.HTML,
        )
        return
    old_name = context.args[0]
    new_owner_username = context.args[1].lstrip("@")
    guild = await db.get_guild_by_name(old_name)
    if not guild:
        await update.message.reply_text(
            border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐓𝐑𝐀𝐍𝐒𝐅𝐄𝐑", "❌ Guild not found."),
            parse_mode=ParseMode.HTML,
        )
        return
    chat_id = update.effective_chat.id if update.effective_chat else 0
    new_user_id = await db.find_user_by_username(chat_id, new_owner_username)
    if not new_user_id:
        await update.message.reply_text(
            border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐓𝐑𝐀𝐍𝐒𝐅𝐄𝐑", f"❌ User @{esc(new_owner_username)} not found in records."),
            parse_mode=ParseMode.HTML,
        )
        return
    try:
        async with db.transaction() as conn:
            await conn.execute("UPDATE guilds SET owner_id = $1 WHERE guild_id = $2", new_user_id, guild["guild_id"])
            existing = await conn.fetchval("SELECT 1 FROM guild_members WHERE user_id = $1", new_user_id)
            if not existing:
                await conn.execute(
                    "INSERT INTO guild_members (user_id, guild_id, contribution_xp) VALUES ($1, $2, 0)",
                    new_user_id, guild["guild_id"],
                )
                await conn.execute("UPDATE guilds SET member_count = member_count + 1 WHERE guild_id = $1", guild["guild_id"])
        s = Screen("𝐆𝐔𝐈𝐋𝐃 • 𝐓𝐑𝐀𝐍𝐒𝐅𝐄𝐑")
        s.p(f"✅ <b>{esc(guild['name'])}</b> transferred to @{esc(new_owner_username)}!")
        view = LiveView.from_update(update)
        await view.show(s, effect="party")
    except Exception:
        logger.exception("Error transferring guild")
        await update.message.reply_text(
            border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐓𝐑𝐀𝐍𝐒𝐅𝐄𝐑", "❌ Transfer failed."),
            parse_mode=ParseMode.HTML,
        )


@safe_reply
async def cmd_rename_guild(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.GLOBAL_OWNER_ID:
        await update.message.reply_text(
            border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐑𝐄𝐍𝐀𝐌𝐄", "❌ Only the Global Master."),
            parse_mode=ParseMode.HTML,
        )
        return
    if len(context.args) < 2:
        await update.message.reply_text(
            border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐑𝐄𝐍𝐀𝐌𝐄", "❌ Usage: <code>/rename_guild &lt;old_name&gt; &lt;new_name&gt;</code>"),
            parse_mode=ParseMode.HTML,
        )
        return
    old_name = context.args[0]
    new_name = " ".join(context.args[1:]).strip()
    if len(new_name) > 30 or not NAME_RE.match(new_name):
        await update.message.reply_text(
            border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐑𝐄𝐍𝐀𝐌𝐄", "❌ 1–30 alphanumeric characters/spaces only."),
            parse_mode=ParseMode.HTML,
        )
        return
    guild = await db.get_guild_by_name(old_name)
    if not guild:
        await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐑𝐄𝐍𝐀𝐌𝐄", "❌ Guild not found."), parse_mode=ParseMode.HTML)
        return
    try:
        async with db.transaction() as conn:
            await conn.execute("UPDATE guilds SET name = $1 WHERE guild_id = $2", new_name, guild["guild_id"])
        s = Screen("𝐆𝐔𝐈𝐋𝐃 • 𝐑𝐄𝐍𝐀𝐌𝐄")
        s.p(f"✅ Guild renamed to <b>'{esc(new_name)}'</b>.")
        await update.message.reply_text(s.classic_html(), parse_mode=ParseMode.HTML)
    except Exception as e:
        if "UniqueViolation" in type(e).__name__:
            await update.message.reply_text(
                border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐑𝐄𝐍𝐀𝐌𝐄", "❌ A guild with that name already exists."),
                parse_mode=ParseMode.HTML,
            )
        else:
            logger.exception("Error renaming guild")
            await update.message.reply_text(
                border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐑𝐄𝐍𝐀𝐌𝐄", "❌ Rename failed."),
                parse_mode=ParseMode.HTML,
            )


@safe_reply
async def cmd_guild_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.GLOBAL_OWNER_ID:
        await update.message.reply_text(
            border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐒𝐓𝐀𝐓𝐒", "❌ Only the Global Master."),
            parse_mode=ParseMode.HTML,
        )
        return
    if not context.args:
        await update.message.reply_text(
            border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐒𝐓𝐀𝐓𝐒", "❌ Usage: <code>/guild_stats &lt;guild_name&gt;</code>"),
            parse_mode=ParseMode.HTML,
        )
        return
    name = " ".join(context.args).strip()
    guild = await db.get_guild_by_name(name)
    if not guild:
        await update.message.reply_text(border_text("𝐆𝐔𝐈𝐋𝐃 • 𝐒𝐓𝐀𝐓𝐒", "❌ Guild not found."), parse_mode=ParseMode.HTML)
        return
    members = await db.get_guild_members(guild["guild_id"])
    s = _guild_hero(guild, members)
    avg = guild["total_xp"] // max(1, len(members))
    top = members[0] if members else None
    s.h("📊 Deep Analytics", 2)
    s.kv(
        [
            ("📈 Avg contribution", f"{format_number(avg)} XP"),
            ("🥇 Top contributor", f"@{esc(top['username'])}" if top else "—"),
            ("🆔 Guild ID", str(guild["guild_id"])),
        ]
    )
    view = LiveView.from_update(update)
    await view.open("Computing stats")
    await view.show(s)


def register(application) -> None:
    application.add_handler(CommandHandler("newguild", cmd_newguild))
    application.add_handler(CommandHandler("delguild", cmd_delguild))
    application.add_handler(CommandHandler("guilds_list", cmd_guilds_list))
    application.add_handler(CommandHandler("join_guild", cmd_join_guild))
    application.add_handler(CommandHandler("leave_guild", cmd_leave_guild))
    application.add_handler(CommandHandler("myguild", cmd_myguild))
    application.add_handler(CommandHandler("guild_leaderboard", cmd_guild_leaderboard))
    application.add_handler(CommandHandler("guild_members", cmd_guild_members))
    application.add_handler(CommandHandler("guild_info", cmd_guild_info))
    application.add_handler(CommandHandler("transfer_guild", cmd_transfer_guild))
    application.add_handler(CommandHandler("rename_guild", cmd_rename_guild))
    application.add_handler(CommandHandler("guild_stats", cmd_guild_stats))
    application.add_handler(CallbackQueryHandler(cb_delguild, pattern=r"^delguild(:|cancel)"))
    application.add_handler(CallbackQueryHandler(cb_leave, pattern=r"^leave(:|cancel)"))
