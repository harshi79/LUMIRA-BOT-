# ✨ 𝓛𝓾𝓶𝓲𝓻𝓪 v4 «Nebula»

**The Ultimate Production-Grade Telegram Group Master** — rebuilt from the ground up on the newest **free** Telegram Bot API features (no Telegram Premium needed anywhere), with a signature *LiveView* engine: one message that morphs, animates and streams — zero chat spam.

---

## 🚀 What's new in v4

### ⚡ LiveView engine — "message editing, but smooth haha"
Every interaction happens **inside one message**:

* **Loading shimmer** — commands open an animated placeholder (`⠋ Loading…`) that morphs into the result. No multi-message noise.
* **Animated reveals** — scratch cards scrape themselves frame-by-frame, lottery tickets spin reels, assassinations play a 3-act cutscene.
* **Typewriter AI** — `/ai` and `/roast` answers stream *live* into the message with a blinking `▌` cursor.
* **Tab switching** — the whole dashboard (`/start`, `/help`, profile, leaderboards, guilds) is a single panel that pivots as you tap buttons.
* **Live broadcast dashboard** — the owner literally watches the dispatch progress bar fill up.

### 🧩 Researched & adopted — official Bot API changelog 2025→2026

| API | Feature | How Lumira uses it |
| --- | --- | --- |
| **9.3** | `sendMessageDraft` | Native streaming AI previews in DM (animated, 30s preview window) |
| **10.1** | **Rich Messages** — `sendRichMessage`, `editMessageText(rich_message=)` | Dashboards, profiles & leaderboards render as structured documents: headings, key-value tables, checkbox lists, collapsible details, footnotes |
| **10.2** | **Ephemeral Messages** — `receiver_user_id` + `editEphemeralMessageText` | `/rank` and cooldown notices appear **only to you** inside groups — your balance stays private |
| 8.x | `message_effect_id` | 🎉 on level-ups & jackpots, 🔥 on elite, 💩 on lost bets — 100% free in groups |
| 8.x | `set_message_reaction` | Bot reacts 🔥/💀/😆/👌/🎉 to key moments — the bot feels alive |
| native | `sendDice 🎰` | Real slot machine with honest reels — `/slots <bet>` knows your win before the animation lands |

> **Graceful degradation everywhere.** Rich/ephemeral/draft/effect/reaction calls are probed and rate-counted; if a server or client rejects them, Lumira silently falls back to the classic bordered-HTML UI and keeps working. Old Telegram clients see the v3 look; new clients get the premium look. *Free-able only* — custom emoji, gifts-as-Stars and other Premium-gated toys were deliberately left out.

### 🎮 Gameplay upgrades

* 🔥 **Daily streaks** — claim `/daily` within 36h to build a streak; every 7 days pays a +350 coin milestone bonus (with streak-sync animation).
* 🎰 **Casino** — `/slots <bet>` native slot machine: `777` pays 10×, any triple 5×, any 7 2×. 30s machine cooldown, dead players can't gamble.
* 💸 **`/pay`** — consent-based transfers with confirm buttons.
* 🏆 **Profile card 2.0** — global & group rank position, streak, guild, shield, alive status.
* 🤖 **Streaming AI** — Groq `AsyncGroq` token streaming into LiveView; `/ai` also works in DM (native drafts) or as a reply to any message.

### 🏗 Architecture — from 1 file / 2,956 lines → 17 modules

```
lumira/
├── config.py        env + game-balance constants
├── utils.py         rate limiting, pending FSM, decorators, md→html
├── db.py            asyncpg pool, schema+migrations, atomic transfers
├── ai.py            AsyncGroq service (ask / roast / stream)
├── tgapi.py         Bot API 10.x bridge + capability flags  ← the 2026 magic
├── rich.py          dual-mode Screen builder (rich ↔ classic)
├── engine.py        LiveView: open · show · animate · type_stream  ← the butter
├── keyboards.py     all inline keyboards
└── handlers/
    ├── screens.py   shared renderers (profile, leaderboards, guilds)
    ├── basics.py    /start /help dashboard & nav
    ├── economy.py   rank · daily · scratch · shop · pay
    ├── casino.py    /slots (native 🎰)
    ├── pvp.py       roast · kill · rob · revive · /ai
    ├── gifts.py     /gift /mygifts (animated unboxing)
    ├── guilds.py    full guild lifecycle
    ├── admin.py     analytics · addcoins · stats · broadcast (live progress)
    └── events.py    XP pipeline · welcomes · member tracking
main.py              entry point (polling / webhook), BotFather menu setup
tests/test_engine.py offline test-suite with a FakeBot (22 tests)
requirements.txt     python-telegram-bot[ext,webhooks,job-queue]==22.8
```

---

## ☁️ Setup

1. **BotFather**
   * `/newbot` → copy the token
   * **`/setprivacy` → Disable** (required — Lumira reads group messages for XP)

2. **PostgreSQL** — any 13+ instance; tables & migrations run automatically at boot.

3. **Environment** (see `.env.example`)

```bash
BOT_TOKEN=123:xxx
DATABASE_URL=postgresql://user:pass@host:5432/lumira
GROQ_API_KEY=gsk_xxx            # optional but recommended — powers /ai & /roast
GLOBAL_OWNER_ID=7728424218

# webhook (production) — omit for polling
WEBHOOK_URL=https://your-domain
PORT=8443
WEBHOOK_SECRET=random-string    # recommended in production
```

4. **Install & run** (Python 3.11+)

```bash
pip install -r requirements.txt
python main.py            # polling
# WEBHOOK_URL set → thin webhook server on PORT
```

Every feature has an off-switch env var (`ENABLE_RICH_MESSAGES`, `ENABLE_EPHEMERAL`, `ENABLE_DRAFTS`, `ENABLE_EFFECTS`, `ENABLE_REACTIONS`) — though you never need them, everything self-degrades.

---

## 📚 Command palette

**Everyone** — `/start` `/help` `/rank` `/daily` `/scratch` `/slots <bet>` `/shop` `/gift` `/mygifts` `/pay` `/roast` `/kill` `/rob` `/revive` `/ai` `/leaderboard` `/riches` `/grpleaderboard` `/grpriches` `/join_guild` `/leave_guild` `/myguild` `/guild_leaderboard` `/guild_members` `/guild_info`

**Group owner** — `/analytics` `/members` `/top` `/addcoins` `/removecoins`

**Global Master** — `/broadcast` `/stats` `/newguild` `/delguild` `/guilds_list` `/transfer_guild` `/rename_guild` `/guild_stats`

The bot's slash-command menu, bio and description are (re)written automatically on every boot.

---

## 🧪 Tests

```bash
python tests/test_engine.py     # 22 offline tests — engine, fallbacks, slots, screens
```

## 💡 Design principles

1. **One message per interaction** — edit, don't spam.
2. **Every premium-feel feature must be free** — effects, reactions, rich docs, ephemeral privacy.
3. **Every new API call carries its own parachute** — capability flags + classic fallback, always.
4. **Craft over content** — typewriter cursors, cutscene kills, streak-sync animations.

*Lumira NEBULA — the smoothest group bot on Telegram.* ☬
