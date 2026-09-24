"""Offline functional tests for the Lumira v4 stack (no Telegram needed).

Run:  python tests/test_engine.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("BOT_TOKEN", "123:ABC")
os.environ.setdefault("DATABASE_URL", "postgresql://x:y@localhost/db")

from telegram import Chat, Message
from telegram.error import BadRequest

from lumira import config
from lumira.engine import LiveView
from lumira.rich import Screen
from lumira.handlers.casino import decode_slots, payout

PASS = 0
FAIL = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}  {extra}")


class FakeBot:
    """Records every API call; toggleable failures to test fallbacks."""

    username = "lumira_test_bot"
    id = 999999

    def __init__(self, fail_rich: bool = False, fail_edit: bool = False):
        self.calls = []
        self.fail_rich = fail_rich
        self.fail_edit = fail_edit
        self._mid = 100

    def _msg(self, chat_id, text):
        self._mid += 1
        m = Message(self._mid, datetime.now(config.IST), Chat(chat_id, "supergroup"), text=text)
        return m

    async def _post(self, endpoint, data=None, **kw):
        self.calls.append(("RAW:" + endpoint, data))
        if self.fail_rich and ("Rich" in endpoint or "rich_message" in (data or {})):
            raise BadRequest("can't parse rich message")
        if endpoint == "sendRichMessage":
            chat_id = (data or {}).get("chat_id", -100)
            self._mid += 1
            return {"message_id": self._mid, "date": 1700000000, "chat": {"id": chat_id, "type": "supergroup"}}
        return True

    async def send_message(self, chat_id, text, **kw):
        self.calls.append(("send_message", {"chat_id": chat_id, "text": text, **{k: v for k, v in kw.items() if k not in ("reply_markup",)}}))
        return self._msg(chat_id, text)

    async def edit_message_text(self, text, chat_id=None, message_id=None, **kw):
        self.calls.append(("edit_message_text", {"chat_id": chat_id, "message_id": message_id, "text": text}))
        if self.fail_edit:
            raise BadRequest("Message to edit not found")
        return self._msg(chat_id, text)

    async def send_message_draft(self, chat_id, draft_id, text, **kw):
        self.calls.append(("draft", {"text": text}))
        return True


async def test_animations():
    print("\n— LiveView: open → animate → final markup/effect —")
    bot = FakeBot(fail_rich=True)
    view = LiveView(bot, chat_id=-100)
    await view.open("Loading")
    frames = []
    for i in range(3):
        s = Screen("T")
        s.p(f"frame {i}")
        frames.append(s)
    await view.animate(frames, interval=0.01)
    kinds = [k for k, _ in bot.calls]
    check("placeholder sent", "send_message" in kinds)
    check("raw rich edit attempted then fallback", any(k == "RAW:editMessageText" for k in kinds) and kinds.count("edit_message_text") >= 3)
    check("no crash under permanent rich failure", True)


async def test_rich_send_path():
    print("\n— LiveView: rich send path when capability available —")
    from lumira import tgapi

    tgapi.caps.rich = True
    tgapi.caps._failures.clear()
    bot = FakeBot(fail_rich=False)
    view = LiveView(bot, chat_id=-100)
    s = Screen("𝐑𝐈𝐂𝐇")
    s.h("Section", 2)
    s.kv([("k", "v")])
    await view.show(s, effect="party")
    kinds = [k for k, _ in bot.calls]
    check("sendRichMessage called", "RAW:sendRichMessage" in kinds, str(kinds))
    tgapi.caps.rich = True  # reset


async def test_type_stream():
    print("\n— LiveView: typewriter streaming —")

    async def gen():
        for piece in ["Hello", " brave", " new", " world"]:
            yield piece

    bot = FakeBot(fail_rich=True)
    view = LiveView(bot, chat_id=-100)
    final = await view.type_stream(gen(), title="t", header_html="<b>H</b>", footer_html="<i>F</i>", interval=0.01)
    check("returns full text", final == "Hello brave new world")
    kinds = [k for k, _ in bot.calls]
    check("message sent for stream", "send_message" in kinds or "edit_message_text" in kinds)

    async def gen2():
        for piece in ["x" * 40 for _ in range(8)]:
            yield piece

    bot2 = FakeBot(fail_rich=True)
    view2 = LiveView(bot2, chat_id=42)
    await view2.type_stream(gen2(), title="t", draft=False, interval=0.01)
    sends = [c for c in bot2.calls if c[0] == "send_message"]
    edits = [c for c in bot2.calls if c[0] == "edit_message_text"]
    check("stream sends exactly ONE message", len(sends) == 1, f"sends={len(sends)}")
    check("stream progress uses EDITS", len(edits) >= 1, f"edits={len(edits)}")


def test_screens_render():
    print("\n— Screen: dual-mode rendering —")
    s = Screen("𝐓𝐈𝐓𝐋𝐄", subtitle="sub")
    s.h("Head", 2)
    s.p("para <b>x</b>")
    s.divider()
    s.kv([("one", "1"), ("two", "2")])
    s.items([("🥇", "gold"), ("🥈", "silver")], checked=[True, False])
    s.quote("quote text", cite="cit")
    s.table([["h1", "h2"], ["a", "b"]], header=True)
    rich = s.rich_html()
    classic = s.classic_html()
    check("rich has heading tag", "<h2>" in rich, rich[:120])
    check("rich has table", "<table" in rich)
    check("rich has checkbox list", "checkbox checked" in rich and ' checkbox>' in rich.replace("checkbox checked", ""))
    check("rich has blockquote cite", "<cite>" in rich)
    check("rich has title h1", rich.startswith("<h1>"))
    check("classic has border", "╔═" in classic and "╚" in classic)
    check("classic has rows", "one" in classic and "1" in classic)
    check("classic bullet tree", "┣" in classic or "┗" in classic)


def test_slots_logic():
    print("\n— Casino: slots decode + payout —")
    check("64 decodes to 777", decode_slots(64) == (3, 3, 3))
    check("777 pays 10x", payout((3, 3, 3), 100)[0] == 10)
    check("triple grapes pays 5x", payout((1, 1, 1), 100)[0] == 5)
    check("single seven pays 2x", payout((3, 0, 1), 100)[0] == 2)
    check("double seven pays 3x", payout((3, 3, 0), 100)[0] == 3)
    check("no seven no triple loses", payout((0, 1, 2), 100)[0] == 0)


async def main():
    test_screens_render()
    test_slots_logic()
    await test_rich_send_path()
    await test_animations()
    await test_type_stream()
    print(f"\n{'=' * 40}\nRESULT: {PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    asyncio.run(main())
