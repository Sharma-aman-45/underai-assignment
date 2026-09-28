# Candidate starter code

This is the codebase to work on. The CLI, input/output contract, basic evaluator,
and optional model adapter are implemented. The decision logic and evaluation
are intentionally incomplete. Read the parent [assignment](../ASSIGNMENT.md)
before changing them.

## Offline run

From the assignment folder, using Python 3.10+:

```bash
python3 starter/run.py --mode heuristic --output results/decisions.jsonl
python3 starter/evaluate.py --decisions results/decisions.jsonl
```

The heuristic in `triage.py` has known policy mistakes. It is a plumbing smoke
check, not a completed model migration. The evaluator currently validates shape
and compares with the frozen baseline. Extend it with policy checks, extra cases, and a
deliberately weakened configuration.

## Optional model run

`model.py` uses a standard chat-completions style HTTP endpoint, without extra
dependencies. Set the variables for a provider you can access:

```bash
export UNDERAI_API_KEY=your_key
export UNDERAI_BASE_URL=https://your-provider.example/v1
export UNDERAI_MODEL=your-model-id
python3 starter/run.py --mode api --output results/decisions.jsonl
```

The request payload uses `model`, `messages`, and `temperature`; providers with
different APIs need an adapter change. Review and improve `candidate_prompt.md`.
Do not commit API keys. A model result that breaks the output contract fails
the run with its ticket ID; decide how to handle this in your solution.
Commit your final `results/decisions.jsonl` with the submission; the starter
repository does not include a generated result.

## Where to work

- `triage.py`: replace or improve the deterministic candidate behavior.
- `candidate_prompt.md` and `model.py`: configure and improve model behavior.
- `evaluate.py`: make tests sensitive to policy and behavior regressions.
- `run.py`: keep the JSONL interface while adding logging, cost measurement, or
  error handling if needed.

No solution or gold labels for the public cases are embedded in runtime code.
