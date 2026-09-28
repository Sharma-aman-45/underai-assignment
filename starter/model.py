"""OpenAI-compatible chat-completions adapter (tested with Groq).

Environment:
  UNDERAI_API_KEY, UNDERAI_BASE_URL, UNDERAI_MODEL   required
  UNDERAI_PROMPT_FILE   optional, default starter/candidate_prompt.md
  UNDERAI_TEMPERATURE   optional, default 0

The model only returns route/action/priority/escalate; the ticket id is set in
code so it cannot be altered by ticket content. Invalid outputs are retried.
Token usage and latency are accumulated in USAGE for run.py to report.
"""

import json
import os
import re
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from contract import validate_decision

ROOT = Path(__file__).resolve().parent.parent
MAX_ATTEMPTS = int(os.environ.get("UNDERAI_MAX_ATTEMPTS", "8"))

USAGE = {"calls": 0, "retries": 0, "prompt_tokens": 0, "completion_tokens": 0,
         "total_tokens": 0, "api_seconds": 0.0, "rate_limit_wait_seconds": 0.0}


def config():
    cfg = {
        "api_key": os.environ.get("UNDERAI_API_KEY"),
        "base_url": os.environ.get("UNDERAI_BASE_URL"),
        "model": os.environ.get("UNDERAI_MODEL"),
        "prompt_file": Path(os.environ.get("UNDERAI_PROMPT_FILE",
                                           ROOT / "starter" / "candidate_prompt.md")),
        "temperature": float(os.environ.get("UNDERAI_TEMPERATURE", "0")),
    }
    if not all((cfg["api_key"], cfg["base_url"], cfg["model"])):
        raise RuntimeError("Set UNDERAI_API_KEY, UNDERAI_BASE_URL, and UNDERAI_MODEL")
    return cfg


def system_prompt(cfg):
    prompt = cfg["prompt_file"].read_text(encoding="utf-8")
    policy = (ROOT / "policy.md").read_text(encoding="utf-8")
    return prompt + "\n\n# Reference policy (source of truth)\n\n" + policy


def _post(cfg, payload):
    request = Request(
        cfg["base_url"].rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {cfg['api_key']}",
            "Content-Type": "application/json",
            "User-Agent": "underai-triage/1.0",  # some providers block the urllib default
        },
        method="POST",
    )
    pause = float(os.environ.get("UNDERAI_PAUSE_SECONDS", "0"))
    if pause and USAGE["calls"]:
        time.sleep(pause)
    start = time.perf_counter()
    with urlopen(request, timeout=60) as response:
        result = json.load(response)
    USAGE["api_seconds"] += time.perf_counter() - start
    USAGE["calls"] += 1
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        USAGE[key] += int((result.get("usage") or {}).get(key, 0))
    return result["choices"][0]["message"]["content"]


def _retry_wait(exc, body, attempt):
    """Honour the provider's retry hint (Retry-After header or 'try again in Xs')."""
    header = exc.headers.get("retry-after") if exc.headers else None
    if header:
        try:
            return float(header) + 0.5
        except ValueError:
            pass
    match = re.search(r"try again in ([\d.]+)\s*(ms|s)", body)
    if match:
        seconds = float(match.group(1)) / (1000 if match.group(2) == "ms" else 1)
        return seconds + 0.5
    return min(60.0, 5.0 * (attempt + 1))


def _parse(content, ticket_id):
    match = re.search(r"\{.*\}", content or "", re.DOTALL)
    if not match:
        raise ValueError(f"no JSON object in model output: {content!r}")
    raw = json.loads(match.group(0))
    decision = {
        "id": ticket_id,
        "route": raw.get("route"),
        "action": raw.get("action"),
        "priority": raw.get("priority"),
        "escalate": raw.get("escalate"),
    }
    return validate_decision(decision, ticket_id)


def llm_decide(ticket, text_override=None):
    """Ask the model. text_override lets the hybrid pass a sanitised ticket."""
    cfg = config()
    ticket_view = {"subject": ticket.get("subject", ""), "body": ticket.get("body", "")}
    if text_override is not None:
        ticket_view = {"subject": "", "body": text_override}
    payload = {
        "model": cfg["model"],
        "temperature": cfg["temperature"],
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt(cfg)},
            {"role": "user", "content": "<ticket>\n" + json.dumps(ticket_view, ensure_ascii=False)
                                        + "\n</ticket>"},
        ],
    }
    last_error = None
    for attempt in range(MAX_ATTEMPTS):
        if attempt:
            USAGE["retries"] += 1
        try:
            return _parse(_post(cfg, payload), ticket["id"])
        except HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            last_error = f"HTTP {exc.code}: {body[:300]}"
            if exc.code == 400 and "response_format" in payload:
                payload.pop("response_format")  # provider without JSON mode
            elif exc.code in (429, 500, 502, 503):
                wait = _retry_wait(exc, body, attempt)
                USAGE["rate_limit_wait_seconds"] += wait
                print(f"  {ticket['id']}: HTTP {exc.code}, waiting {wait:.1f}s then retrying")
                time.sleep(wait)
            else:
                raise RuntimeError(last_error) from exc
        except (URLError, TimeoutError) as exc:
            last_error = str(exc)
            time.sleep(2 * (attempt + 1))
        except ValueError as exc:  # bad JSON or contract violation
            last_error = str(exc)
    raise RuntimeError(f"model failed after {MAX_ATTEMPTS} attempts: {last_error}")


def decide(ticket):
    return llm_decide(ticket)