"""
Lumira — production-grade Telegram group master bot.

𝒗4.0 "Nebula": rebuilt as a modular package with a LiveView smooth-editing
engine, Bot API 10.x Rich Messages & Ephemeral Messages (with graceful
fallbacks), streaming AI, native dice games and message effects.

Bot API research baked in (official changelog, core.telegram.org/bots/api-changelog):
  • 9.3  — sendMessageDraft native streaming (DM only, 30s preview)
  • 10.1 — Rich Messages: sendRichMessage / sendRichMessageDraft /
           editMessageText(rich_message=): headings, tables, details, lists
  • 10.2 — Ephemeral messages: receiver_user_id / callback_query_id on sends,
           editEphemeralMessageText/Media/Caption/ReplyMarkup, deleteEphemeralMessage
  • 8.x  — message_effect_id, set_message_reaction, Telegram Stars gifts
  • Free-native toys — sendDice 🎰 (real slot animation, bot knows value instantly)
"""

__version__ = "4.0.0"
BOT_NAME = "Lumira"
BOT_SIGNATURE = "𝓛𝓾𝓶𝓲𝓻𝓪"
