# nla-claim-verification

Can a natural language autoencoder (NLA) check its own explanations?

Anthropic's NLA paper proposed, but did not test, using the activation reconstructor as a verifier: if a claim in an explanation is true, deleting it should hurt reconstruction more than deleting a plausible false claim. This repository holds the first per-claim test of that idea, on the public Qwen3.6-27B community NLA, together with the labeled claim dataset, every scored edit, the analysis, and the write-up.

## Headline results

TRUE vs RELATED_FALSE claims about the source text, AUROC with 95% context-level bootstrap intervals.

| Signal | n | AUROC | 95% CI |
|---|---:|---:|---|
| Reconstructor: deletion excess (headline) | 2,119 | 0.477 | [0.452, 0.502] |
| Reconstructor: fluent LLM-rewritten deletion | 200 | 0.516 | [0.440, 0.597] |
| Reconstructor: claim scored alone (inverted) | 2,119 | 0.404 | [0.379, 0.430] |
| LLM judge, explanation only (DeepSeek v4) | 500 | 0.522 | [0.471, 0.570] |
| Recurrence across 9 neighboring positions | 2,119 | 0.665 | [0.643, 0.688] |
| LLM judge with source text (ceiling) | 500 | 0.920 | [0.894, 0.944] |

Other numbers that matter:

- 59.6% of this NLA's claims about its source text were plausible fabrications (1,283 of 2,153).
- Truth contributes about 0.001 MSE to reconstruction cost; per-claim deletion-excess noise is 0.037.
- A crude recurrence filter lifts claim precision from 40% to 56% at 47% coverage, and to 64% at 18%.

The reconstructor reads meaning: genuine explanations reach FVE 0.637 against 0.002 for shuffled text and negative values for copied or mismatched text. It does not read truth. The verification information is absent from any single explanation, partly recoverable across resampled explanations, and fully present only in ground truth that a deployed NLA does not have.

Full write-up: `writeup/nla-reconstructor-verification-writeup.docx`. Detailed analysis log: `results/analysis_report.md`.

## Layout

```
src/
  00_smoke_test.py             reproduce released FVE and calibrate activation extraction
  01_collect_contexts.py       300 contexts in three strata
  02_extract_activations.py    layer-42 activations at the final 10 token positions (Modal, GPU)
  03_generate_explanations.py  verbalizer decoding, 3,900 explanations (Modal, GPU)
  phase3_claims.py             claim splitting, labeling, recurrence judgments (fixed prompts, gated)
  05_score_ar.py               reconstructor scoring of every edit (Modal, GPU)
  08_analysis.py               metrics, bootstrap CIs, controls, golden tests, figures
data/
  contexts.parquet             300 source texts
  explanations.parquet         3,900 NLA explanations
  claims_labeled.parquet       2,971 atomic claims with labels and recurrence counts
  texts_to_score.parquet       12,759 texts scored by the reconstructor (genuine, deletions, random spans, solo, controls)
  scores.parquet               reconstruction MSE for each scored text
  scores_siblings.parquet      scores for neighboring-position explanations
  judge_*_input.jsonl          inputs for the two LLM-judge baselines
results/
  phase6_metrics.json          every AUROC, CI, and per-claim metric
  phase6_robustness.json       outlier, batch-size, splitter, edit-quality checks
  phase6_golden_tests.json     hand-computable fixtures that gate the analysis
  judge_baselines.json         judge AUROCs; judge_*_scores.jsonl are the raw scores
  consistency_filter_curve.json precision/coverage by recurrence threshold
  activation_calibration.json  cosine against Anthropic's released fixtures
  human_blindlabel_check*.json human label checks (seed-0 exposed, seed-1 clean) with raw label files
  analysis_report.md           full analysis log
  extreme_cases.md             40 highest-magnitude cases with source text and edits
  figs/                        all figures in the write-up
```

Activation tensors (23 MB, regenerable with `02_extract_activations.py`) and operational logs are not included.

## Reproducing

GPU stages run on [Modal](https://modal.com). `setup_modal.sh` installs the client. The scripts are numbered in run order; each writes its outputs and a gate file that the next stage checks before running. Local analysis needs only:

```
pip install -r requirements.txt
python src/08_analysis.py
```

The analysis is gated by four golden tests (hand-computed AUROC, sign-flip, context bootstrap, edit fixtures). It refuses to write metrics if any fail.

## Model and data

- Model: Qwen3.6-27B with the community NLA adapters from `ceselder/qwen3.6-27b-nla-rl` (layer 42, iteration-300 verbalizer). Released FVE reproduced at 0.782 before any experiment.
- Contexts: 100 web pretraining passages, 100 chat and agent transcripts, 100 knowledge-dense Wikipedia passages.
- Labels: TRUE, RELATED_FALSE (right topic, wrong specifics), UNRELATED_FALSE, UNVERIFIABLE, from a fixed prompt with the source text. Human agreement 92% on an exposed 50-claim sample and 86% on a clean one, with the human stricter in every disagreement.

## Limitations

One checkpoint. Model-generated labels with human spot checks. A crude token-overlap recurrence matcher. Only claims about the source text can be verified; claims about model cognition cannot. See the write-up for the full list.

## Author

Hetansh Waghela. Produced as the research task for Neel Nanda's MATS 12.0 stream application, September 2026.
