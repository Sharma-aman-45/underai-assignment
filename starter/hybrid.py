"""Hybrid triage: deterministic guardrails + LLM.
 
1. Rules run first. If they fire a safety-critical rule (incident, third-party
   refusal, privacy-rights or account-change verification), that decision is
   final: the LLM cannot downgrade it.
2. Otherwise the LLM classifies an injection-stripped copy of the ticket, which
   lets it catch phrasings the regexes miss (e.g. named third parties).
3. An LLM answer that breaks a policy invariant falls back to the rules answer.
 
Every decision is traced in TRACE for the report.
"""
 
import triage
from model import llm_decide
 
AUTHORITATIVE = {"rule1_incident", "rule2_third_party",
                 "rule3_privacy_rights", "rule4_access_change"}
TRACE = []
 
 
def _invariants_ok(d):
    safety = d["route"] == "safety"
    if safety != (d["action"] == "escalate") or safety != (d["priority"] == "urgent"):
        return False
    if d["action"] == "refuse" and d["route"] != "privacy":
        return False
    if d["action"] == "verify_identity" and d["route"] not in ("privacy", "access"):
        return False
    return True
 
 
def decide(ticket):
    rules = triage.decide(ticket)
    reason = triage.classify(ticket)[3]
    entry = {"id": ticket["id"], "rules_reason": reason,
             "rules": {k: rules[k] for k in ("route", "action", "priority")}}
 
    if reason in AUTHORITATIVE:
        entry.update(source="rules", llm=None)
        TRACE.append(entry)
        return rules
 
    sanitised, _ = triage.clean(ticket)
    llm = llm_decide(ticket, text_override=sanitised)
    entry["llm"] = {k: llm[k] for k in ("route", "action", "priority")}
    if _invariants_ok(llm):
        entry["source"] = "llm" if entry["llm"] != entry["rules"] else "agree"
        TRACE.append(entry)
        return llm
    entry["source"] = "rules_fallback_invalid_llm"
    TRACE.append(entry)
    return rules
 