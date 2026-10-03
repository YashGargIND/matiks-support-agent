# Evaluation

Use a **reviewed** JSON array of `EvalCase` objects. Never promote predictions into ground truth. The local `data/label_candidates.json` contains captured real support reports with `labels: null`; it deliberately cannot run as a labelled evaluation until a human supplies labels and verifies evidence snapshots.

Required fields per case:

- `id`: unique case key.
- `message`: channel, channel_ref, timezone-bearing created_at, subject, body, provenance (`real` or `synthetic`). Redact before model evaluation.
- `labels`: reviewed_by, category, verdict, internal_actions (excluding send_reply), escalate, auto_safe, injection, and optional required_tools.
- `evidence_snapshot`: keyed by tool name, each with `source` and `data` matching `support/contracts.py`. Snapshot accuracy/coverage must be independently checked; the evaluator does not assert live verification.
- `pii_reviewed`: true only after a reviewer checks the redacted input.
- `unsupported_draft`: optional adversarial factual draft to test rejection independently of the pipeline's generated draft.

Run without models by default:

```sh
.venv/bin/python -m support.evaluation evals/smoke.json --output evals/results/smoke
```

Use a fresh output directory each run; an existing evaluation database is rejected. `--allow-models` permits model calls only if the local environment also enables them, credentials exist, real inputs were reviewed, and budget checks pass. Evaluations use labelled read-only snapshots and never fetch live Mongo/GCP data.

Reports include triage/action accuracy, verdict accuracy by **labelled** branch, escalation precision/recall, injection resistance, guard-probe catch rate, false promises, unsafe auto-resolutions, latency and actual call accounting. No samples means `null`, not a success. Synthetic checks and no-model latency/cost are explicitly distinct from the required 60–100 real-ticket assessment. The runner exits unsuccessfully for false promises or unsafe auto-resolutions.

The present real sample covers eight predicted categories including `other`; DM-safety and cheating coverage still need selected real examples. Source capture, PII review, outcome labelling and live evidence verification are separate steps.
