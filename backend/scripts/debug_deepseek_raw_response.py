"""Quick CLI to verify DeepSeek complete_text returns raw_text (calls real API if configured)."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.llm_provider_raw_debug_service import invoke_provider_raw_debug
from app.schemas.llm_extraction import ProviderRawDebugRequest


async def main() -> int:
    body = ProviderRawDebugRequest(
        provider="deepseek",
        model_name="deepseek-chat",
        prompt='请只输出一个 JSON object：{"ok": true}',
        temperature=0,
        max_tokens=256,
        response_format={"type": "json_object"},
    )
    result = await invoke_provider_raw_debug(body)
    print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))
    return 0 if result.raw_text_present else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
