"""Screen builder — describe a UI once, render it two ways:

  • Rich mode  → Bot API 10.1 Rich HTML (<h1>.. <table> <details> <ul> ...)
  • Classic mode → the v3 bordered HTML box (╔══ ✧ TITLE ✧ ══╗) for any
                   client/server without Rich Message support.

Handlers never care which mode renders; the engine decides at send time.
User-provided text must be passed through utils.esc() before being embedded.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

DIVIDER = "━" * 20


class Block:
    def rich(self) -> str:  # Bot API 10.1 Rich HTML
        raise NotImplementedError

    def classic(self) -> str:  # legacy bordered HTML body line(s)
        raise NotImplementedError


@dataclass
class Heading(Block):
    text: str  # already-escaped HTML fragment
    level: int = 2  # 1..3

    def rich(self) -> str:
        lvl = min(6, max(1, self.level))
        return f"<h{lvl}>{self.text}</h{lvl}>"

    def classic(self) -> str:
        if self.level == 1:
            return f"\n<b>✛ {self.text} ✛</b>\n{DIVIDER}"
        return f"\n<b>» {self.text}</b>"


@dataclass
class Para(Block):
    text: str  # HTML fragment

    def rich(self) -> str:
        return f"<p>{self.text}</p>"

    def classic(self) -> str:
        return self.text


@dataclass
class Div(Block):
    def rich(self) -> str:
        return "<hr>"

    def classic(self) -> str:
        return DIVIDER


@dataclass
class KeyValues(Block):
    """Aligned key/value panel → rich table or classic aligned list."""

    pairs: Sequence[Tuple[str, str]]  # (label html, value html)

    def rich(self) -> str:
        rows = "".join(f'<tr><td>{k}</td><td align="right"><b>{v}</b></td></tr>' for k, v in self.pairs)
        return f"<table compact>{rows}</table>"

    def classic(self) -> str:
        lines = []
        for k, v in self.pairs:
            lines.append(f"{k} <b>{v}</b>")
        return "\n".join(lines)


@dataclass
class Items(Block):
    """Bulleted / check-list items."""

    items: Sequence[Tuple[str, str]]  # (prefix, text_html) — prefix: "•", "✅", "🥇" ...
    checked: Optional[Sequence[bool]] = None  # when set → checkbox list in rich mode

    def rich(self) -> str:
        if self.checked is not None:
            lis = []
            for (_, text), ok in zip(self.items, self.checked):
                chk = " checkbox checked" if ok else " checkbox"
                lis.append(f"<li{chk}>{text}</li>")
            return f'<ul>{"".join(lis)}</ul>'
        return "<ul>" + "".join(f"<li>{(p + ' ') if p else ''}{t}</li>" for p, t in self.items) + "</ul>"

    def classic(self) -> str:
        out = []
        for i, (prefix, text) in enumerate(self.items):
            if self.checked is not None and i < len(self.checked):
                mark = "✅" if self.checked[i] else "☐"
                out.append(f"┣ {mark} {text}")
            else:
                out.append(f"┣ {prefix + ' ' if prefix else ''}{text}")
        if out:
            out[-1] = out[-1].replace("┣", "┗", 1)
        return "\n".join(out)


@dataclass
class Quote(Block):
    text: str
    cite: Optional[str] = None
    expandable: bool = False

    def rich(self) -> str:
        attr = " expandable" if self.expandable else ""
        cite = f"<cite>{self.cite}</cite>" if self.cite else ""
        return f"<blockquote{attr}>{self.text}{cite}</blockquote>"

    def classic(self) -> str:
        cite = f"\n<i>— {self.cite}</i>" if self.cite else ""
        return f"<blockquote>{self.text}</blockquote>{cite}"


@dataclass
class Details(Block):
    """Collapsible section (rich) — flattened under a heading in classic."""

    summary: str
    body: List[Block]

    def rich(self) -> str:
        inner = "".join(b.rich() for b in self.body)
        return f"<details><summary>{self.summary}</summary>{inner}</details>"

    def classic(self) -> str:
        inner = "\n".join(b.classic() for b in self.body)
        return f"\n<b>▼ {self.summary}</b>\n{inner}"


@dataclass
class Table(Block):
    """Real table in rich mode; monospaced grid in classic mode."""

    rows: Sequence[Sequence[str]]  # HTML fragments per cell
    header: bool = False

    def rich(self) -> str:
        body = []
        for i, row in enumerate(self.rows):
            tag = "th" if self.header and i == 0 else "td"
            body.append("<tr>" + "".join(f"<{tag}>{c}</{tag}>" for c in row) + "</tr>")
        return f"<table compact bordered>{''.join(body)}</table>"

    def classic(self) -> str:
        if not self.rows:
            return ""
        cols = max(len(r) for r in self.rows)
        import re as _re

        widths = [0] * cols
        plain_rows: List[List[str]] = []
        for row in self.rows:
            plain = [_re.sub(r"<[^>]+>", "", c) for c in row]
            plain_rows.append(plain)
            for i, cell in enumerate(plain):
                widths[i] = max(widths[i], len(cell))
        lines = []
        for i, (row, plain) in enumerate(zip(self.rows, plain_rows)):
            pad = [plain[j] + " " * (widths[j] - len(plain[j])) for j in range(len(row))]
            lines.append(f"<code>{' │ '.join(pad)}</code>")
            if self.header and i == 0:
                lines.append("<code>" + "─┼─".join("─" * w for w in widths) + "</code>")
        return "\n".join(lines)


@dataclass
class Code(Block):
    text: str

    def rich(self) -> str:
        import html as _h

        return f"<pre><code>{_h.escape(self.text)}</code></pre>"

    def classic(self) -> str:
        import html as _h

        return f"<pre><code>{_h.escape(self.text)}</code></pre>"


# ----------------------------------------------------------------------------
class Screen:
    """A panel the bot shows: renders rich (10.1) or classic bordered HTML."""

    def __init__(self, title: str, subtitle: Optional[str] = None):
        self.title = title
        self.subtitle = subtitle
        self.blocks: List[Block] = []

    # fluent builders ---------------------------------------------------------
    def h(self, text: str, level: int = 2) -> "Screen":
        self.blocks.append(Heading(text, level))
        return self

    def p(self, text: str) -> "Screen":
        self.blocks.append(Para(text))
        return self

    def divider(self) -> "Screen":
        self.blocks.append(Div())
        return self

    def kv(self, pairs: Sequence[Tuple[str, str]]) -> "Screen":
        self.blocks.append(KeyValues(pairs))
        return self

    def items(self, items: Sequence[Tuple[str, str]], checked: Optional[Sequence[bool]] = None) -> "Screen":
        self.blocks.append(Items(items, checked))
        return self

    def quote(self, text: str, cite: Optional[str] = None, expandable: bool = False) -> "Screen":
        self.blocks.append(Quote(text, cite, expandable))
        return self

    def details(self, summary: str, body: List[Block]) -> "Screen":
        self.blocks.append(Details(summary, body))
        return self

    def table(self, rows: Sequence[Sequence[str]], header: bool = False) -> "Screen":
        self.blocks.append(Table(rows, header))
        return self

    def code(self, text: str) -> "Screen":
        self.blocks.append(Code(text))
        return self

    # renderers ---------------------------------------------------------------
    def rich_html(self) -> str:
        parts = [f"<h1>{self.title}</h1>"]
        if self.subtitle:
            parts.append(f"<p><i>{self.subtitle}</i></p><hr>")
        parts.extend(b.rich() for b in self.blocks)
        return "\n".join(parts)

    def classic_html(self) -> str:
        from .utils import border_text

        lines: List[str] = []
        if self.subtitle:
            lines.append(f"<i>{self.subtitle}</i>")
            lines.append(DIVIDER)
        lines.extend(b.classic() for b in self.blocks)
        return border_text(self.title, "\n".join(lines))

    def __str__(self) -> str:
        return self.classic_html()
