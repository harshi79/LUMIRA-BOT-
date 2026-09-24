"""Command/callback/message handler registration."""
from __future__ import annotations

from . import admin, basics, casino, economy, events, gifts, guilds, pvp


def register_all(application) -> None:
    for module in (basics, economy, casino, pvp, gifts, guilds, admin, events):
        module.register(application)
