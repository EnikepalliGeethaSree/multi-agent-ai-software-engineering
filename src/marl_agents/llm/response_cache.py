"""On-disk cache of LLM replies, so a repeated request costs no quota.

The key is the sha256 of everything that decides the reply: provider, model, temperature, output
limit, seed, JSON mode, provider-specific options, the full prompt (every message) and the prompt
template version. Changing any of them makes a new key, so a stale reply is never reused.

Files hold the reply text, the model id the server reported and the token counts of the original
call. They hold no API key or key label. Writes are atomic (temporary file, then rename).
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from marl_agents.llm.base import GenerationConfig, Message

logger = logging.getLogger(__name__)


class CachedReply(BaseModel):
    text: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str | None = None


def cache_key(
    provider: str,
    model: str,
    messages: list[Message],
    config: GenerationConfig,
    json_mode: bool = False,
    extra_params: dict[str, Any] | None = None,
) -> str:
    payload = {
        "provider": provider,
        "model": model,
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
        "seed": config.seed,
        "stop": config.stop,
        "json_mode": json_mode,
        "extra_params": extra_params or {},
        "prompt_version": config.prompt_version,
        "messages": [m.model_dump() for m in messages],
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class ResponseCache:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.hits = 0
        self.misses = 0

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> CachedReply | None:
        path = self._path(key)
        if not path.is_file():
            self.misses += 1
            return None
        try:
            reply = CachedReply.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError):
            logger.warning("Ignoring unreadable cached reply %s", path.name)
            self.misses += 1
            return None
        self.hits += 1
        return reply

    def put(self, key: str, reply: CachedReply) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(reply.model_dump_json(), encoding="utf-8")
        tmp.replace(path)
