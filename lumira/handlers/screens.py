"""Shared screen builders (used by multiple handler modules)."""
from __future__ import annotations

from typing import List, Optional

from .. import config
from ..db import db
from ..rich import Screen
from ..utils import create_progress_bar, esc, format_number, get_level_symbol, mention_html


async def profile_screen(user_id: int, username: str, chat_id: Optional[int] = None) -> Screen:
    """Rich profile card — global stats + optional group position."""
    global_data = await db.get_user_global(user_id)
    if not global_data:
        s = Screen("𝐍𝐎 𝐒𝐓𝐀𝐓𝐒")
        s.p("❌ You don't have any stats yet. Send a few messages to start your journey!")
        return s

    total_xp = global_data["total_xp"]
    total_coins = global_data["total_coins"]
    level = min(total_xp // config.XP_PER_LEVEL, config.MAX_LEVEL)
    symbol = get_level_symbol(level)
    xp_into = total_xp % config.XP_PER_LEVEL
    progress = create_progress_bar(xp_into, config.XP_PER_LEVEL)
    total_msgs = await db.get_user_total_messages(user_id)
    gpos = await db.get_global_rank_position(user_id, by="xp")

    guild = await db.get_user_guild(user_id)
    guild_name = esc(guild["name"]) if guild else "—"

    s = Screen("𝓛𝓾𝓶𝓲𝓻𝓪 • 𝐏𝐑𝐎𝐅𝐈𝐋𝐄 𝐂𝐀𝐑𝐃", subtitle=f"@{esc(username)}")
    s.divider()
    s.h("⚔️ Combat Record", 2)
    pairs: List[tuple] = [
        ("✨ Total XP", f"<code>{format_number(total_xp)}</code>"),
        ("🆙 Level", f"{level} <code>{symbol}</code>"),
        ("💰 Coins", f"{format_number(total_coins)}"),
        ("📨 Messages", f"{format_number(total_msgs)}"),
        ("🏰 Guild", guild_name),
    ]
    if gpos and gpos.get("pos"):
        pairs.append(("🌍 Global Rank", f"#{gpos['pos']} / {format_number(gpos['total'])}"))
    s.kv(pairs)
    if level < config.MAX_LEVEL:
        s.h("📈 Next Level", 2)
        need = config.XP_PER_LEVEL - xp_into
        s.p(f"{progress}\n<i>{format_number(need)} XP remaining</i>")
    else:
        s.quote("☬ ELITE — maximum level achieved", cite="𝓛𝓾𝓶𝓲𝓻𝓪")

    if chat_id:
        per = await db.get_user_per_group(user_id, chat_id)
        pos = await db.get_group_rank_position(user_id, chat_id)
        if per and pos.get("pos"):
            s.h("🏘️ This Group", 2)
            gpairs = [
                ("🏅 Rank", f"#{pos['pos']} / {format_number(pos['total'])}"),
                ("✨ Group XP", f"<code>{format_number(per['xp'])}</code>"),
                ("💰 Group Coins", f"{format_number(per['coins'])}"),
                ("🔥 Daily Streak", f"{per.get('daily_streak', 0)} days"),
                ("🛡️ Shield", "ACTIVE" if per.get("shield_expiry") else "—"),
                ("💀 Status", "DEAD — /revive" if per.get("is_dead") else "Alive"),
            ]
            s.kv(gpairs)
    return s


async def global_lb_screen(limit: int = 10) -> Screen:
    rows = await db.get_global_leaderboard(limit=limit)
    s = Screen("𝐆𝐋𝐎𝐁𝐀𝐋 𝐗𝐏 𝐋𝐄𝐀𝐃𝐄𝐑𝐁𝐎𝐀𝐑𝐃")
    if not rows:
        s.p("❌ No global XP recorded yet.")
        return s
    entries: List[tuple] = []
    for i, row in enumerate(rows):
        medal = config.MEDALS[i] if i < len(config.MEDALS) else f"{i+1}."
        name = row["username"] or "Unknown"
        level = min(row["level"], config.MAX_LEVEL)
        entries.append((medal, f"{mention_html(row['user_id'], name)} • L{level} <code>{get_level_symbol(level)}</code> • {format_number(row['total_xp'])} XP"))
    s.items(entries)
    s.p("\n🔥 <i>Keep active in chat to ascend the hierarchy!</i>")
    return s


async def global_riches_screen(limit: int = 10) -> Screen:
    rows = await db.get_riches_leaderboard(limit=limit)
    s = Screen("𝐆𝐋𝐎𝐁𝐀𝐋 𝐂𝐎𝐈𝐍 𝐇𝐎𝐀𝐑𝐃𝐄𝐑𝐒")
    if not rows:
        s.p("❌ No coin records yet.")
        return s
    entries = []
    for i, row in enumerate(rows):
        title = config.RICHES_TITLES[i] if i < len(config.RICHES_TITLES) else f"{i+1}."
        entries.append((title, f"{mention_html(row['user_id'], row['username'] or 'Unknown')} • {format_number(row['total_coins'])} 💰"))
    s.items(entries)
    s.p("\n💎 <i>Hoard coins through daily rewards and lucky scratch cards!</i>")
    return s


async def group_lb_screen(chat_id: int, limit: int = 10) -> Screen:
    rows = await db.get_group_leaderboard(chat_id, limit=limit)
    s = Screen("𝐓𝐇𝐈𝐒 𝐆𝐑𝐎𝐔𝐏'𝐒 𝐗𝐏 𝐄𝐋𝐈𝐓𝐄")
    if not rows:
        s.p("❌ No group stats recorded yet.")
        return s
    entries = []
    for i, row in enumerate(rows):
        medal = config.MEDALS[i] if i < len(config.MEDALS) else f"{i+1}."
        level = min(row["level"], config.MAX_LEVEL)
        entries.append((medal, f"{mention_html(row['user_id'], row['username'] or 'Unknown')} • L{level} <code>{get_level_symbol(level)}</code> • {format_number(row['xp'])} XP"))
    s.items(entries)
    s.p("\n🚀 <i>The most elite conversationalists of this group!</i>")
    return s


async def group_riches_screen(chat_id: int, limit: int = 10) -> Screen:
    rows = await db.get_group_riches(chat_id, limit=limit)
    s = Screen("𝐓𝐇𝐈𝐒 𝐆𝐑𝐎𝐔𝐏'𝐒 𝐂𝐎𝐈𝐍 𝐊𝐈𝐍𝐆𝐒")
    if not rows:
        s.p("❌ No group coin stats recorded yet.")
        return s
    entries = []
    for i, row in enumerate(rows):
        medal = config.MEDALS[i] if i < len(config.MEDALS) else f"{i+1}."
        entries.append((medal, f"{mention_html(row['user_id'], row['username'] or 'Unknown')} • {format_number(row['coins'])} 💰"))
    s.items(entries)
    s.p("\n💸 <i>Use /shop to spend your wealth!</i>")
    return s


async def guilds_lb_screen(limit: int = 10) -> Screen:
    guilds = await db.get_guild_leaderboard(limit=limit)
    s = Screen("𝐓𝐎𝐏 𝐆𝐔𝐈𝐋𝐃𝐒 𝐎𝐅 𝐋𝐔𝐌𝐈𝐑𝐀")
    if not guilds:
        s.p("No guilds created yet. Use /newguild and /join_guild!")
        return s
    entries = []
    for i, g in enumerate(guilds):
        medal = config.MEDALS[i] if i < len(config.MEDALS) else f"{i+1}."
        entries.append((medal, f"<b>{esc(g['name'])}</b> — Lvl {g['level']} • {format_number(g['total_xp'])} XP • 👥 {g['members']}"))
    s.items(entries)
    return s
