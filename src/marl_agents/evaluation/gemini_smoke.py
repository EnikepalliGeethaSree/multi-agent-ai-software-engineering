"""Live Gemini smoke test.

    python -m marl_agents.evaluation.gemini_smoke --config configs/gemini.yaml

Makes a few very small real requests on one synthetic Python file, and records each check as
`live`, `local` or `simulated`, so a passing unit test is never reported as a live result.

- Uses `GEMINI_API_KEY`. The `GOOGLE_API_KEY` fallback needs `--allow-google-api-key`, because that
  key may belong to another project, perhaps with billing on.
- If the configured model is unavailable it reports that and stops. It never switches model.
- Rate-limit and quota errors are not provoked on purpose: that would waste the quota. Those checks
  are `simulated`, covered by tests/unit/llm/test_gemini.py.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from marl_agents.agents.code_review import CodeReviewAgent
from marl_agents.config import LLMSettings, Settings, load_settings
from marl_agents.core.schemas import AgentRequest, FindingSource
from marl_agents.evaluation.recorder import RunRecorder
from marl_agents.llm.base import LLMError, LLMProvider, Message
from marl_agents.llm.factory import create_provider
from marl_agents.llm.gemini import recommend_model

KEY_VARIABLES = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
INVALID_KEY_VARIABLE = "MARL_SMOKE_INVALID_KEY"
INVALID_KEY_VALUE = "invalid-smoke-test-key"
TIMEOUT_S = 0.01
SYNTHETIC_FILE = "smoke_example.py"
# Written for this test, so no private code leaves the machine. The bug is deliberate.
SYNTHETIC_CODE = '''"""Synthetic example for the Gemini smoke test."""


def average(values: list[float]) -> float:
    """Return the mean of values."""
    return sum(values) / len(values)


def report(values: list[float]) -> str:
    """Describe the mean of values."""
    return f"mean={average(values)}"
'''


class Ping(BaseModel):
    status: str


class Check(BaseModel):
    name: str
    kind: Literal["live", "local", "simulated"]
    passed: bool | None  # None = not run live
    detail: str


Factory = Callable[[LLMSettings], LLMProvider]


@contextmanager
def _environment(remove: tuple[str, ...] = (), add: dict[str, str] | None = None) -> Iterator[None]:
    saved = {k: os.environ.get(k) for k in (*remove, *(add or {}))}
    try:
        for name in remove:
            os.environ.pop(name, None)
        os.environ.update(add or {})
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def key_variable() -> str | None:
    """The variable that holds the key. Only its name is ever reported."""
    return next((name for name in KEY_VARIABLES if os.environ.get(name)), None)


def _missing_key(settings: Settings, factory: Factory) -> Check:
    with _environment(remove=KEY_VARIABLES):
        try:
            factory(settings.llm)
        except LLMError as exc:
            helpful = "GEMINI_API_KEY" in str(exc)
            return Check(name="missing_key", kind="local", passed=helpful, detail=str(exc))
    return Check(name="missing_key", kind="local", passed=False, detail="no error was raised")


def _structured_reply(llm: LLMProvider) -> Check:
    messages = [
        Message(role="system", content="Reply with a JSON object only."),
        Message(role="user", content='Return exactly this JSON: {"status": "ok"}'),
    ]
    try:
        reply = llm.generate_structured(messages, Ping)
    except LLMError as exc:
        return Check(name="json_and_schema", kind="live", passed=False, detail=str(exc))
    usage = llm.usage
    return Check(
        name="json_and_schema",
        kind="live",
        passed=reply.status == "ok",
        detail=f"reply={reply.status!r} tokens={usage.input_tokens}+{usage.output_tokens}",
    )


def _review_settings(settings: Settings) -> Settings:
    s = settings.model_copy(deep=True)
    s.review.mode = "full"
    s.review.suggest_fixes = False
    s.review.unit_cache = False
    s.review.analysis_cache = False
    s.rag.enabled = False
    return s


def _review(settings: Settings, llm: LLMProvider) -> Any:
    agent = CodeReviewAgent(llm, settings=_review_settings(settings), progress=lambda _m: None)
    return agent.run(AgentRequest(snippet=SYNTHETIC_CODE, snippet_filename=SYNTHETIC_FILE))


def _agent_review(settings: Settings, llm: LLMProvider) -> Check:
    try:
        result = _review(settings, llm)
    except Exception as exc:  # any crash here is the finding this check exists to report
        return Check(
            name="agent_review", kind="live", passed=False, detail=f"{type(exc).__name__}: {exc}"
        )
    failed = int(result.stats.get("units_failed", 0) or 0)
    from_llm = [f for f in result.findings if FindingSource.LLM in f.sources]
    usage = result.stats.get("llm_usage") or {}
    return Check(
        name="agent_review",
        kind="live",
        passed=failed == 0 and bool(usage.get("calls")),
        detail=(
            f"failed units={failed} calls={usage.get('calls')} findings={len(result.findings)} "
            f"from LLM={len(from_llm)} rejected={result.stats.get('llm_rejected_by_reason') or {}}"
        ),
    )


def _invalid_key(settings: Settings, factory: Factory) -> tuple[Check, Check]:
    """A real request with a false key, then a whole review with it. Neither can use quota."""
    llm_settings = settings.llm.model_copy(update={"api_key_env": INVALID_KEY_VARIABLE})
    with _environment(add={INVALID_KEY_VARIABLE: INVALID_KEY_VALUE}):
        llm = factory(llm_settings)
    message = [Message(role="user", content='Return {"status": "ok"}')]
    try:
        llm.generate(message)
        rejected = Check(
            name="invalid_key", kind="live", passed=False, detail="the request was accepted"
        )
    except LLMError as exc:
        attempts = exc.attempts
        leaked = INVALID_KEY_VALUE in str(exc)
        rejected = Check(
            name="invalid_key",
            kind="live",
            passed=len(attempts) == 1 and not leaked,
            detail=(
                f"attempts={len(attempts)} kind={attempts[-1].error_kind if attempts else None} "
                f"status={attempts[-1].status if attempts else None} key in message={leaked}"
            ),
        )
    try:
        result = _review(settings, llm)
    except Exception as exc:  # a failed request must never crash a review
        return rejected, Check(
            name="failed_request_is_safe",
            kind="live",
            passed=False,
            detail=f"the review crashed: {type(exc).__name__}",
        )
    failed = int(result.stats.get("units_failed", 0) or 0)
    return rejected, Check(
        name="failed_request_is_safe",
        kind="live",
        passed=failed > 0 and bool(result.errors),
        detail=f"failed units={failed}; static findings kept={len(result.findings)}",
    )


def _timeout(settings: Settings, factory: Factory) -> Check:
    """A real request given too little time, with one retry."""
    llm = factory(settings.llm.model_copy(update={"timeout_s": TIMEOUT_S, "max_retries": 1}))
    try:
        llm.generate([Message(role="user", content='Return {"status": "ok"}')])
    except LLMError as exc:
        kinds = [a.error_kind for a in exc.attempts]
        return Check(
            name="timeout_and_retry",
            kind="live",
            passed=len(kinds) == 2 and all(k == "transient" for k in kinds),
            detail=f"attempts={len(kinds)} kinds={kinds}",
        )
    return Check(
        name="timeout_and_retry",
        kind="live",
        passed=False,
        detail=f"a {TIMEOUT_S}s request succeeded, so no timeout was observed",
    )


NOT_PROVOKED = (
    ("rate_limit_429", "waits as the server asks, then retries"),
    ("daily_quota", "stops at once and reports the Pacific reset time"),
)


def run_smoke(
    settings: Settings, factory: Factory = create_provider, allow_google_key: bool = False
) -> list[Check]:
    """Each check is independent where it can be. Stops before any request if the key is wrong."""
    checks = [_missing_key(settings, factory)]
    variable = key_variable()
    if variable is None or (variable == "GOOGLE_API_KEY" and not allow_google_key):
        detail = (
            "no key set; add GEMINI_API_KEY to .env"
            if variable is None
            else "only GOOGLE_API_KEY is set; add GEMINI_API_KEY, or confirm that key is a free "
            "AI Studio key and pass --allow-google-api-key"
        )
        checks.append(Check(name="key", kind="local", passed=False, detail=detail))
        return checks
    checks.append(Check(name="key", kind="local", passed=True, detail=f"variable: {variable}"))
    llm = factory(settings.llm)
    try:
        models = llm.list_models()  # type: ignore[attr-defined]
    except LLMError as exc:
        checks.append(Check(name="model_access", kind="live", passed=False, detail=str(exc)))
        return checks
    if settings.llm.model not in models:
        best = recommend_model(models)
        detail = (
            f"{settings.llm.model} is not available to this key. Recommended free model: {best}. "
            "Not switching: set GEMINI_MODEL yourself."
        )
        checks.append(Check(name="model_access", kind="live", passed=False, detail=detail))
        return checks
    checks.append(
        Check(
            name="model_access",
            kind="live",
            passed=True,
            detail=f"{settings.llm.model} is listed ({len(models)} text models available)",
        )
    )
    checks.append(_structured_reply(llm))
    checks.append(_agent_review(settings, llm))
    checks.extend(_invalid_key(settings, factory))
    checks.append(_timeout(settings, factory))
    for name, behaviour in NOT_PROVOKED:
        detail = f"not provoked live; unit tests with a fake client verify that it {behaviour}"
        checks.append(Check(name=name, kind="simulated", passed=None, detail=detail))
    return checks


def summary_md(checks: list[Check], model: str | None) -> str:
    def mark(c: Check) -> str:
        return "not run live" if c.passed is None else "PASS" if c.passed else "FAIL"

    lines = [
        "# Gemini smoke test",
        "",
        f"Model: `{model}`. Synthetic code only.",
        "",
        "| Check | Kind | Result | Detail |",
        "|---|---|---|---|",
    ]
    lines += [f"| {c.name} | {c.kind} | {mark(c)} | {c.detail} |" for c in checks]
    return "\n".join([*lines, ""])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live Gemini smoke test on synthetic code")
    parser.add_argument("--config", type=Path)
    parser.add_argument(
        "--allow-google-api-key",
        action="store_true",
        help="use GOOGLE_API_KEY when GEMINI_API_KEY is empty",
    )
    args = parser.parse_args(argv)
    settings = load_settings(args.config)
    if settings.llm.provider != "gemini":
        print(
            f"error: the provider is {settings.llm.provider!r}. Set LLM_PROVIDER=gemini in .env.",
            file=sys.stderr,
        )
        return 2
    checks = run_smoke(settings, allow_google_key=args.allow_google_api_key)
    recorder = RunRecorder("gemini_smoke", settings)
    for check in checks:
        recorder.prediction(check.model_dump())
    failed = [c.name for c in checks if c.passed is False]
    live = [c for c in checks if c.kind == "live"]
    md = summary_md(checks, settings.llm.model)
    out = recorder.finish(
        {
            "benchmark": "gemini_smoke",
            "provider": settings.llm.provider,
            "model": settings.llm.model,
            "live_checks": len(live),
            "live_passed": sum(1 for c in live if c.passed),
            "failed": failed,
            "checks": [c.model_dump() for c in checks],
        },
        md,
        benchmark="gemini_smoke",
        llm_provider=settings.llm.provider,
        llm_model=settings.llm.model,
    )
    print(md)
    print(f"saved: {out}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
