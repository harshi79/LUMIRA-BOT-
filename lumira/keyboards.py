"""Inline keyboard builders — consistent across every screen."""
from __future__ import annotations

from typing import List

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from . import config


def dashboard(bot_username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("👤 My Profile", callback_data="nav:profile"),
                InlineKeyboardButton("🏆 Top XP", callback_data="nav:lb"),
            ],
            [
                InlineKeyboardButton("💎 Top Riches", callback_data="nav:riches"),
                InlineKeyboardButton("🏰 Guilds", callback_data="nav:guilds"),
            ],
            [
                InlineKeyboardButton("📚 Commands", callback_data="nav:help"),
                InlineKeyboardButton("🛒 Shop", url=f"https://t.me/{bot_username}?start=shop"),
            ],
        ]
    )


def welcome_group(bot_username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("👤 My Profile", callback_data="nav:profile"),
                InlineKeyboardButton("📚 Help", url=f"https://t.me/{bot_username}?start=help"),
            ]
        ]
    )


def activation(bot_username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📚 Commands Help", url=f"https://t.me/{bot_username}?start=help"),
                InlineKeyboardButton("🏆 Group Top", callback_data="nav:grptop"),
            ]
        ]
    )


def help_categories() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("👤 User & Economy", callback_data="nav:help_user"),
                InlineKeyboardButton("⚔️ PVP & Games", callback_data="nav:help_pvp"),
            ],
            [
                InlineKeyboardButton("🏰 Guild System", callback_data="nav:help_guild"),
                InlineKeyboardButton("📊 Group & Ranks", callback_data="nav:help_group"),
            ],
            [
                InlineKeyboardButton("🎰 Casino", callback_data="nav:help_casino"),
                InlineKeyboardButton("👑 Owner", callback_data="nav:help_owner"),
            ],
            [InlineKeyboardButton("🏠 Dashboard", callback_data="nav:home")],
        ]
    )


def back(target: str = "nav:help", label: str = "🔙 Back") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=target)]])


def back_home() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🏠 Dashboard", callback_data="nav:home")]]
    )


def shop() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"🛡️ Shield — {'{:,}'.format(config.SHIELD_COST)} coins", callback_data="buy:shield")],
            [InlineKeyboardButton("✨ Random XP Boost — 100 coins", callback_data="buy:xp")],
            [InlineKeyboardButton("🎟️ Lottery Ticket — 50 coins", callback_data="buy:lottery")],
            [InlineKeyboardButton(f"💪 Revive Self — {'{:,}'.format(config.REVIVE_SELF_COST)} coins", callback_data="buy:revive_self")],
            [InlineKeyboardButton(f"👥 Revive Other — {'{:,}'.format(config.REVIVE_OTHER_COST)} coins", callback_data="buy:revive_other")],
        ]
    )


def confirm(confirm_data: str, cancel_data: str, confirm_label: str, cancel_label: str = "❌ Cancel") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(confirm_label, callback_data=confirm_data),
                InlineKeyboardButton(cancel_label, callback_data=cancel_data),
            ]
        ]
    )


def gifts() -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    items = list(config.GIFT_TYPES.items())
    for i in range(0, len(items), 2):
        row: List[InlineKeyboardButton] = []
        for gtype, info in items[i : i + 2]:
            row.append(
                InlineKeyboardButton(
                    f"{info['emoji']} {gtype.capitalize()} ({info['price']})",
                    callback_data=f"gift:{gtype}",
                )
            )
        rows.append(row)
    return InlineKeyboardMarkup(rows)


def pay_confirm(amount: int, target_id: int) -> InlineKeyboardMarkup:
    return confirm(
        f"pay:{amount}:{target_id}",
        "paycancel",
        f"✅ Send {amount:,} coins",
    )


def profile_actions(bot_username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🛒 Shop", url=f"https://t.me/{bot_username}?start=shop"),
                InlineKeyboardButton("🏆 Leaderboard", callback_data="nav:lb"),
            ],
            [InlineKeyboardButton("🏠 Dashboard", callback_data="nav:home")],
        ]
    )


def add_to_group(bot_username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("👑 Add me to your group", url=f"https://t.me/{bot_username}?startgroup=true")],
            [InlineKeyboardButton("📚 Help Dashboard", callback_data="nav:help")],
        ]
    )
