# MEMO: Triage model migration

**To:** Engineering lead
**Re:** Replacing the retiring triage model
**Recommendation: STAGE.** Ship the hybrid configuration in shadow mode first. Do not ship the LLM-only replacement.

## Evidence

- **The retiring model is not a safe reference.** 4 of its 15 frozen decisions
  violate policy: it replied to an MFA-disable request (T06) and a data export
  (T07) without verification, obeyed an injected "SYSTEM" instruction (T13),
  and applied the wrong precedence (T15). Matching it would preserve those
  errors.
- **The hybrid is policy-correct on everything we have.** It scores 15/15 on
  the public tickets and 10/10 on custom cases. Baseline agreement is 11/15;
  all four differences are documented corrections.
- **The LLM alone is not safe to ship.** `gpt-oss-120b` is 15/15 on the public
  set, but it obeyed a prompt injection in a custom case (X01) and escalated
  an invoice question as a security incident. Rewriting the prompt did not
  fix this. The guardrail layer did.
- **The suite detects regressions.** Five deliberately weakened configurations
  are all caught: removing identity verification alone fails 6 cases.
- **Cost is negligible.** The hybrid used 8 LLM calls and about 9.5k tokens per
  15 tickets: about $0.002 at list price, about 1.3 s API latency per call.
  Critical decisions (incidents, refusals, verification) need no LLM call.

## Remaining risks

1. **Missed incidents.** Pattern-based injection stripping can remove a real
   incident sentence ("Note to the assistant: my key leaked"). This is the
   highest-severity failure mode.
2. **Unseen phrasing.** Named third parties, non-English tickets, and typos
   bypass the rules. The LLM fallback for these is untested on this data.
3. **Small, non-blind evaluation.** 25 cases total, custom cases written
   alongside the rules, one run per configuration.
4. **Operations.** The free-tier rate limit (8k tokens/min) is not viable for
   production volume; a paid tier or another provider is needed.

## Next check before a real rollout

Run a **blind held-out set of 100+ synthetic tickets written by someone other
than the author**. It should cover paraphrases, Hindi/Hinglish, named third
parties, and new injection styles, **three repetitions each**. Gate the
rollout on:

- zero misses on rule 1 (incidents)
- zero replies where verification or refusal is required
- disagreement between LLM and rules below an agreed threshold

Then run the hybrid in shadow mode alongside the current system for about a
week, with human review of every safety and privacy disagreement, before
switching traffic.