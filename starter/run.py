"""Generate one decision per input ticket.
 
Modes: heuristic (rules only), api (LLM only), hybrid (rules guardrails + LLM).
Writes results/decisions.jsonl plus <output>_runlog.json (model, parameters,
tokens, timing) and, for hybrid, <output>_trace.jsonl.
"""
 
import argparse
import hashlib
import json
import os
import platform
import time
from datetime import datetime, timezone
from pathlib import Path
 
from contract import read_jsonl, validate_decision
 
ROOT = Path(__file__).resolve().parent.parent
 
 
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("heuristic", "api", "hybrid"), default="heuristic")
    parser.add_argument("--cases", type=Path, default=ROOT / "cases.jsonl")
    parser.add_argument("--output", type=Path, default=ROOT / "results" / "decisions.jsonl")
    args = parser.parse_args()
 
    if args.mode == "api":
        from model import decide
    elif args.mode == "hybrid":
        from hybrid import decide
    else:
        from triage import decide
 
    tickets = list(read_jsonl(args.cases))
    ids = [ticket["id"] for ticket in tickets]
    if len(ids) != len(set(ids)):
        raise ValueError("input contains duplicate ticket IDs")
 
    # Collect and validate before writing, so a failed run does not leave a
    # partially generated decision file.
    start = time.perf_counter()
    decisions = []
    for ticket in tickets:
        try:
            decisions.append(validate_decision(decide(ticket), ticket["id"]))
        except Exception as exc:
            raise RuntimeError(f"ticket {ticket['id']} failed: {exc}") from exc
    elapsed = time.perf_counter() - start
 
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in decisions),
        encoding="utf-8",
    )
 
    log = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": args.mode,
        "cases": str(args.cases.name),
        "tickets": len(decisions),
        "elapsed_seconds": round(elapsed, 2),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "dependencies": "standard library only",
    }
    if args.mode in ("api", "hybrid"):
        import model
        prompt_path = model.config()["prompt_file"]
        log.update({
            "provider_base_url": os.environ.get("UNDERAI_BASE_URL"),
            "model": os.environ.get("UNDERAI_MODEL"),
            "temperature": model.config()["temperature"],
            "prompt_file": str(prompt_path.name),
            "prompt_sha256_12": hashlib.sha256(prompt_path.read_bytes()).hexdigest()[:12],
            "usage": {k: (round(v, 2) if isinstance(v, float) else v)
                      for k, v in model.USAGE.items()},
        })
    if args.mode == "hybrid":
        import hybrid
        trace_path = args.output.with_name(args.output.stem + "_trace.jsonl")
        trace_path.write_text("".join(json.dumps(t) + "\n" for t in hybrid.TRACE), encoding="utf-8")
        log["hybrid_sources"] = {s: sum(t["source"] == s for t in hybrid.TRACE)
                                 for s in sorted({t["source"] for t in hybrid.TRACE})}
 
    log_path = args.output.with_name(args.output.stem + "_runlog.json")
    log_path.write_text(json.dumps(log, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(decisions)} decisions to {args.output} in {elapsed:.1f}s")
    if "usage" in log:
        u = log["usage"]
        print(f"LLM calls={u['calls']} retries={u['retries']} tokens={u['total_tokens']} "
              f"(prompt {u['prompt_tokens']}, completion {u['completion_tokens']})")
    print(f"Run log: {log_path}")
 
 
if __name__ == "__main__":
    main()
 