"""Evaluation suite for the triage migration.
 
Sections
  1. Contract       - output shape, all case IDs exactly once
  2. Baseline       - exact agreement with the frozen retiring decisions
  3. Policy         - candidate AND baseline checked against policy labels
                      (evals/public_expected.jsonl) plus label-free invariants
  4. Extra cases    - live run on evals/extra_cases.jsonl
  5. Sensitivity    - deliberately weakened configurations must FAIL
 
Policy labels live only here, never in the runtime (triage.py / model.py).
Exit code is 1 if the candidate fails any check or a weakening goes undetected.
"""
 
import argparse
import contextlib
import re
from pathlib import Path
 
import triage
from contract import read_jsonl, validate_decision
 
ROOT = Path(__file__).resolve().parent.parent
EVALS = ROOT / "evals"
FIELDS = ("route", "action", "priority", "escalate")
LABELS = ("route", "action", "priority")
NEVER = re.compile(r"(?!)")  # regex that never matches
 
OUT = []
 
 
def say(line=""):
    print(line)
    OUT.append(line)
 
 
# ---------------------------------------------------------------- loading ---
def load_decisions(path):
    rows = [validate_decision(row) for row in read_jsonl(path)]
    ids = [row["id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate IDs in {path}")
    return {row["id"]: row for row in rows}
 
 
def load_expected(path):
    return {row["id"]: row for row in read_jsonl(path)}
 
 
# ----------------------------------------------------------- policy checks ---
def invariant_errors(d):
    """Rules that hold for every policy outcome, no labels needed."""
    errors = []
    if d["escalate"] != (d["action"] == "escalate"):
        errors.append("escalate flag must equal action==escalate")
    if d["route"] == "safety" and (d["action"] != "escalate" or d["priority"] != "urgent"):
        errors.append("safety must be escalate+urgent")
    if d["route"] != "safety" and (d["priority"] == "urgent" or d["action"] == "escalate"):
        errors.append("only safety may be urgent/escalated")
    if d["action"] == "refuse" and d["route"] != "privacy":
        errors.append("refuse is only valid on privacy")
    if d["action"] == "verify_identity" and d["route"] not in ("privacy", "access"):
        errors.append("verify_identity only valid on privacy/access")
    return errors
 
 
def policy_problems(decision, expected):
    problems = invariant_errors(decision)
    for field in LABELS:
        if decision[field] != expected[field]:
            problems.append(f"{field}={decision[field]} (policy: {expected[field]})")
    return problems
 
 
def score(decisions, expected_rows):
    """Return {id: [problems]} for failing cases only."""
    return {
        case_id: probs
        for case_id, row in expected_rows.items()
        if (probs := policy_problems(decisions[case_id], row["expected"]))
    }
 
 
# --------------------------------------------------------------- systems ---
def run_system(decide, tickets):
    return {t["id"]: validate_decision(decide(t), t["id"]) for t in tickets}
 
 
def starter_heuristic(ticket):
    """Original starter logic, kept as a known-bad control."""
    text = (ticket["subject"] + " " + ticket["body"]).lower()
    if any(w in text for w in ("leaked", "suspicious login", "token")):
        r, a, p = "safety", "escalate", "urgent"
    elif any(w in text for w in ("privacy", "personal data", "usage logs")):
        r, a, p = "privacy", "reply", "normal"
    elif any(w in text for w in ("password", "mfa", "sign-in", "login")):
        r, a, p = "access", "reply", "normal"
    elif any(w in text for w in ("invoice", "charge", "refund", "plan")):
        r, a, p = "billing", "reply", "normal"
    else:
        r, a, p = "general", "reply", "normal"
    return {"id": ticket["id"], "route": r, "action": a, "priority": p, "escalate": a == "escalate"}
 
 
@contextlib.contextmanager
def patched(**overrides):
    saved = {name: getattr(triage, name) for name in overrides}
    try:
        for name, value in overrides.items():
            setattr(triage, name, value)
        yield
    finally:
        for name, value in saved.items():
            setattr(triage, name, value)
 
 
WEAKENINGS = {
    "no_injection_guard": dict(INJECTION=NEVER),
    "no_hypothetical_guard": dict(QUOTED=NEVER, HYPOTHETICAL=NEVER, NEGATED_INCIDENT=NEVER),
    "no_identity_verification": dict(ACCESS_CHANGE=NEVER, PRIVACY_RIGHTS=NEVER),
    "no_third_party_refusal": dict(THIRD_PARTY=NEVER),
}
 
 
# ------------------------------------------------------------------ main ---
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--decisions", type=Path, default=ROOT / "results" / "decisions.jsonl")
    parser.add_argument("--reference", type=Path, default=ROOT / "baseline_decisions.jsonl")
    parser.add_argument("--cases", type=Path, default=ROOT / "cases.jsonl")
    parser.add_argument("--system", choices=("heuristic", "api", "hybrid"), default="heuristic",
                        help="system used for the live extra-case run")
    parser.add_argument("--save", type=Path, default=ROOT / "results" / "evaluation_output.txt")
    args = parser.parse_args()
 
    failed = False
    public_tickets = list(read_jsonl(args.cases))
    public_expected = load_expected(EVALS / "public_expected.jsonl")
    extra_rows = list(read_jsonl(EVALS / "extra_cases.jsonl"))
    extra_expected = {r["id"]: r for r in extra_rows}
 
    # 1. Contract ---------------------------------------------------------
    say("== 1. CONTRACT ==")
    candidate = load_decisions(args.decisions)
    reference = load_decisions(args.reference)
    case_ids = {t["id"] for t in public_tickets}
    if candidate.keys() != case_ids:
        raise SystemExit(f"case IDs differ: missing={sorted(case_ids - candidate.keys())}, "
                         f"extra={sorted(candidate.keys() - case_ids)}")
    say(f"PASS: {len(candidate)} decisions, valid schema, every case ID exactly once")
 
    # 2. Baseline agreement -----------------------------------------------
    say("\n== 2. BASELINE AGREEMENT ==")
    matches = 0
    for case_id in sorted(reference):
        old, new = reference[case_id], candidate[case_id]
        diff = [f"{f}: {old[f]} -> {new[f]}" for f in FIELDS if old[f] != new[f]]
        matches += not diff
        if diff:
            say(f"  {case_id}: " + "; ".join(diff))
    say(f"Agreement: {matches}/{len(reference)} ({matches / len(reference):.1%})")
    for f in FIELDS:
        same = sum(reference[i][f] == candidate[i][f] for i in reference)
        say(f"  {f:<9} {same}/{len(reference)}")
 
    # 3. Policy compliance ------------------------------------------------
    say("\n== 3. POLICY COMPLIANCE (public cases) ==")
    for name, decisions in (("candidate", candidate), ("baseline", reference)):
        problems = score(decisions, public_expected)
        say(f"{name}: {len(public_expected) - len(problems)}/{len(public_expected)} policy-correct")
        for case_id, probs in sorted(problems.items()):
            say(f"  VIOLATION {case_id}: {'; '.join(probs)}")
        if name == "candidate" and problems:
            failed = True
 
    # 4. Extra cases -----------------------------------------------------
    say(f"\n== 4. EXTRA CASES ({args.system}) ==")
    if args.system == "api":
        from model import decide as system_decide
    elif args.system == "hybrid":
        from hybrid import decide as system_decide
    else:
        system_decide = triage.decide
    extra_decisions = run_system(system_decide, extra_rows)
    extra_problems = score(extra_decisions, extra_expected)
    for row in extra_rows:
        probs = extra_problems.get(row["id"])
        say(f"  {'FAIL' if probs else 'PASS'} {row['id']}: {row['reason']}")
        if probs:
            say(f"       -> {'; '.join(probs)}")
    say(f"Extra cases: {len(extra_rows) - len(extra_problems)}/{len(extra_rows)} passed")
    failed |= bool(extra_problems)
 
    # 5. Sensitivity -----------------------------------------------------
    say("\n== 5. SENSITIVITY (weakened configs must fail) ==")
    all_rows = public_tickets + extra_rows
    all_expected = {**public_expected, **extra_expected}
 
    def check(label, decide):
        nonlocal failed
        problems = score(run_system(decide, all_rows), all_expected)
        caught = bool(problems)
        say(f"  {'CAUGHT' if caught else 'MISSED'} {label}: {len(problems)} failing case(s) "
            f"{sorted(problems)}")
        failed |= not caught
 
    check("starter_heuristic", starter_heuristic)
    for label, overrides in WEAKENINGS.items():
        with patched(**overrides):
            check(label, triage.decide)
 
    say("\n== RESULT: " + ("FAIL ==" if failed else "PASS =="))
    args.save.parent.mkdir(parents=True, exist_ok=True)
    args.save.write_text("\n".join(OUT) + "\n", encoding="utf-8")
    print(f"(saved to {args.save})")
    raise SystemExit(1 if failed else 0)
 
 
if __name__ == "__main__":
    main()
 