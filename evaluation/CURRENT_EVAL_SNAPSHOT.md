# Current Eval Snapshot

Date: `2026-04-28`

## Automated Checks

- Full test suite: `58 passed`
- MCP regression tests: `8 passed`
- Evaluation tests: `5 passed`

## Runnable Eval Scripts

### Intent Eval

Command:

```bash
python -m ai_radar.evaluation.intent_eval evaluation/data/intent_ground_truth.json
```

Template smoke result:
- total: `3`
- correct: `3`
- accuracy: `1.0`

Notes:
- This verifies the script path and output format.
- It is not yet a real benchmark because the dataset is still only a template.

### Wiki Quality Eval

Command:

```bash
python -m ai_radar.evaluation.wiki_quality_eval evaluation/data/wiki_quality_samples.json
```

Template smoke result:
- count: `1`
- overall average: `5.0`

Notes:
- This confirms the rubric script runs end to end.
- It is not yet representative because the sample is intentionally clean.

### Novelty Eval

Command:

```bash
python -m ai_radar.evaluation.novelty_eval evaluation/data/novelty_ground_truth.json
```

Template smoke result:
- baseline accuracy: `0.0`
- temporal accuracy: `0.0`
- full accuracy: `0.0`

Notes:
- The script is healthy.
- The current template labels are not aligned with the heuristic scorer thresholds, so this output should be read as a pipeline smoke test, not as a product metric.

## What Is Still Missing

To produce meaningful stage-seven metrics, the project still needs:

- real novelty ground truth
- real recommendation relevance labels
- real intent query set beyond the starter template
- more real usage behavior for recommendation and preference-evolution analysis
