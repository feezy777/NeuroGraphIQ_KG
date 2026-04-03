from __future__ import annotations

import json
import os
from typing import Any
from urllib import request


class DeepSeekClient:
    def __init__(self, base_url: str | None = None, model: str | None = None, api_key: str | None = None):
        self.base_url = (base_url or os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com").rstrip("/")
        self.model = model or os.getenv("DEEPSEEK_MODEL") or "deepseek-chat"
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY", "")
        if not self.api_key:
            raise ValueError("DEEPSEEK_API_KEY is required.")

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> Any:
        parsed, _ = self.chat_json_with_status(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return parsed

    def chat_json_with_status(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> tuple[Any, int]:
        payload = {
            "model": self.model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        with request.urlopen(req, timeout=120) as resp:
            status_code = int(getattr(resp, "status", 200) or 200)
            raw = resp.read().decode("utf-8")
        data = json.loads(raw)
        content = data["choices"][0]["message"]["content"]
        return _parse_json_payload(content), status_code


def _parse_json_payload(content: str) -> Any:
    text = str(content or "").strip()
    candidates: list[str] = [text]

    # Pull possible fenced JSON blocks.
    if "```" in text:
        for part in text.split("```"):
            block = part.strip()
            if not block:
                continue
            if block.lower().startswith("json"):
                block = block[4:].strip()
            candidates.append(block)

    # Add broad bracket slices as fallback candidates.
    array_start = text.find("[")
    array_end = text.rfind("]")
    if array_start >= 0 and array_end > array_start:
        candidates.append(text[array_start : array_end + 1])

    object_start = text.find("{")
    object_end = text.rfind("}")
    if object_start >= 0 and object_end > object_start:
        candidates.append(text[object_start : object_end + 1])

    decoder = json.JSONDecoder()
    visited: set[str] = set()
    last_error: json.JSONDecodeError | None = None

    for candidate in candidates:
        value = candidate.strip()
        if not value or value in visited:
            continue
        visited.add(value)

        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            last_error = exc

        # Try to raw-decode the first valid JSON entity from noisy content.
        for idx, ch in enumerate(value):
            if ch not in "[{":
                continue
            try:
                parsed, _ = decoder.raw_decode(value, idx=idx)
                return parsed
            except json.JSONDecodeError as exc:
                last_error = exc

    if last_error is not None:
        raise last_error
    raise ValueError("DeepSeek response does not contain valid JSON payload.")
