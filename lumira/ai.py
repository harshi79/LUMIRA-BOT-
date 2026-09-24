"""AI service — Groq (AsyncGroq) with real token streaming for the LiveView."""
from __future__ import annotations

from typing import AsyncGenerator

from . import config
from .utils import logger

LUMIRA_PERSONA = (
    "You are Lumira — a sharp, elite AI assistant inside a Telegram group "
    "gaming bot. Answer helpfully and concisely (under 120 words unless the "
    "question truly needs more). Light flair welcome, no filler."
)
ROAST_PERSONA = (
    "You are a savage, witty roast generator. Roasts are playful burns with "
    "modern slang and emojis — never hateful, never targeted at protected traits."
)


class AIService:
    def __init__(self) -> None:
        self._client = None
        if config.GROQ_API_KEY:
            from groq import AsyncGroq

            self._client = AsyncGroq(api_key=config.GROQ_API_KEY)

    @property
    def ready(self) -> bool:
        return self._client is not None

    async def ask(self, question: str, context: str = "") -> str:
        """One-shot answer (kept for compatibility)."""
        if not self._client:
            return "AI is not configured right now. Set GROQ_API_KEY and try again!"
        user_msg = question if not context else f"Context: {context}\n\nQuestion: {question}"
        try:
            resp = await self._client.chat.completions.create(
                model=config.GROQ_MODEL,
                messages=[
                    {"role": "system", "content": LUMIRA_PERSONA},
                    {"role": "user", "content": user_msg},
                ],
                max_tokens=600,
                temperature=0.7,
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception as e:
            logger.error(f"AI error: {e}")
            return "AI is recharging. Try again shortly!"

    async def stream(
        self,
        question: str,
        *,
        context: str = "",
        persona: str = LUMIRA_PERSONA,
        max_tokens: int = 600,
    ) -> AsyncGenerator[str, None]:
        """True token-streaming generator — feeds the typewriter UX."""
        if not self._client:
            yield "AI is not configured right now. Set GROQ_API_KEY and try again!"
            return
        user_msg = question if not context else f"Context: {context}\n\nQuestion: {question}"
        try:
            stream = await self._client.chat.completions.create(
                model=config.GROQ_MODEL,
                messages=[
                    {"role": "system", "content": persona},
                    {"role": "user", "content": user_msg},
                ],
                max_tokens=max_tokens,
                temperature=0.8,
                stream=True,
            )
            async for event in stream:
                try:
                    delta = event.choices[0].delta
                    piece = getattr(delta, "content", None) or ""
                except Exception:
                    piece = ""
                if piece:
                    yield piece
        except Exception as e:
            logger.error(f"AI stream error: {e}")
            yield "…the AI stream glitched. Try again in a moment!"

    async def roast(self, target_name: str, context: str = "") -> str:
        if not self._client:
            return "AI is not configured right now. Stay safe!"
        prompt = f"Roast {target_name}. Keep it under 20 words, savage, witty, modern slang and emojis."
        if context:
            prompt += f" Context: {context}"
        try:
            resp = await self._client.chat.completions.create(
                model=config.GROQ_MODEL,
                messages=[
                    {"role": "system", "content": ROAST_PERSONA},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=100,
                temperature=1.0,
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception as e:
            logger.error(f"AI error: {e}")
            return "AI is recharging its savage energy. Try again later!"


ai_service = AIService()
