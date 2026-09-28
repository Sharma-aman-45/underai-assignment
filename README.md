# UnderAI Model Migration: submission

A replacement support-ticket triage configuration with a **hybrid architecture**:
deterministic policy guardrails plus an LLM (`openai/gpt-oss-120b` on Groq),
and an evaluation suite that compares it with the frozen baseline and with
`policy.md`.

- Analysis: [REPORT.md](REPORT.md)
- Rollout recommendation: [MEMO.md](MEMO.md)

## Setup

Python 3.10+ (tested on 3.11.1, Windows 10). **No third-party packages**; only the standard library.

The LLM modes need an OpenAI-compatible endpoint. A free Groq key works:

```cmd
:: Windows (cmd)
set UNDERAI_API_KEY=<your key>
set UNDERAI_BASE_URL=https://api.groq.com/openai/v1
set UNDERAI_MODEL=openai/gpt-oss-120b
set UNDERAI_PAUSE_SECONDS=15
```
```bash
# macOS / Linux
export UNDERAI_API_KEY=<your key> UNDERAI_BASE_URL=https://api.groq.com/openai/v1
export UNDERAI_MODEL=openai/gpt-oss-120b UNDERAI_PAUSE_SECONDS=15
```

`UNDERAI_PAUSE_SECONDS` spaces out calls to stay under Groq's free-tier limit
of 8,000 tokens per minute. The adapter also honours the provider's retry-after
hint on HTTP 429.

Optional variables: `UNDERAI_PROMPT_FILE` (default `starter/candidate_prompt.md`)
and `UNDERAI_TEMPERATURE` (default `0`).

## Generate `results/decisions.jsonl` (one command)

```bash
python starter/run.py --mode hybrid --output results/decisions.jsonl
```

On Windows, use `py` in place of `python`. This takes about 2 minutes on the
free tier because of pacing. With no API key, `--mode heuristic` runs the
rules layer offline; it produces the same decisions on the 15 public cases.

## Evaluate

```bash
python starter/evaluate.py --system hybrid
```

This checks the contract, baseline agreement, policy compliance, the 10
custom cases in `evals/extra_cases.jsonl`, and five deliberately weakened
configurations. It writes `results/evaluation_output.txt` and exits non-zero
on any failure.

## Modes

| Mode | What it does |
| --- | --- |
| `heuristic` | Rules only (`starter/triage.py`) |
| `api` | LLM only (`starter/model.py` + `candidate_prompt.md` + `policy.md`) |
| `hybrid` | Rules first; safety-critical rule hits are final. Otherwise the LLM classifies an injection-stripped ticket. An LLM answer that breaks a policy invariant falls back to the rules (`starter/hybrid.py`) |

## Files

| Path | Purpose |
| --- | --- |
| `starter/triage.py` | Deterministic policy engine: injection stripping, quote/hypothetical filter, rules 1-6 in order |
| `starter/model.py` | OpenAI-compatible adapter: JSON mode, retries, rate-limit handling, token/latency accounting. Sets `id` in code |
| `starter/hybrid.py` | Hybrid decision logic and per-ticket trace |
| `starter/candidate_prompt.md` | Replacement prompt |
| `starter/run.py` | CLI; writes decisions, `<output>_runlog.json`, and `<output>_trace.jsonl` for hybrid |
| `starter/evaluate.py` | Evaluation suite |
| `evals/public_expected.jsonl` | Policy labels for the 15 public cases (evaluator only, never read at runtime) |
| `evals/extra_cases.jsonl` | 10 custom cases, each with a reason |
| `results/` | Final decisions, run logs, hybrid trace, and evaluation outputs for every configuration |

The runtime never reads case IDs, the policy labels, or `baseline_decisions.jsonl`.
No secrets are stored in the repository.