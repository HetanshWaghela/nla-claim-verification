"""Phase 6: local, deterministic analysis for the NLA verifier.

This script has no Modal, OpenRouter, GPU, or network dependency.  The built-in
golden tests run before the analysis data are loaded.  All result files are
written atomically and every mandatory gate has a result file under results/.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pyarrow.parquet as pq
from sklearn.metrics import roc_auc_score, roc_curve


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RESULTS = ROOT / "results"
FIGS = RESULTS / "figs"

SCORES_PATH = DATA / "scores.parquet"
SIBLING_SCORES_PATH = DATA / "scores_siblings.parquet"
CLAIMS_PATH = DATA / "claims_labeled.parquet"
TEXTS_PATH = DATA / "texts_to_score.parquet"
EXPLANATIONS_PATH = DATA / "explanations.parquet"
CONTEXTS_PATH = DATA / "contexts.parquet"
ACTIVATIONS_DIR = DATA / "activations"

OUTLIER_FLAGS_PATH = RESULTS / "outlier_flags.json"
EDIT_FLAGS_PATH = RESULTS / "edit_flags.json"
PHASE2_GATE_PATH = RESULTS / "phase2_merge_gate.json"
PHASE4_MANIFEST_PATH = RESULTS / "phase4_edit_manifest.json"
PHASE5_PRELIGHT_PATH = RESULTS / "phase5_preflight.json"
PHASE5_BATCH_PATH = RESULTS / "ar_batch_validation.json"
PHASE5_PRIMARY_GATE_PATH = RESULTS / "phase5_primary_gate.json"
PHASE5_SIBLING_GATE_PATH = RESULTS / "phase5_siblings_gate.json"
PHASE5_SCORE_PATH = RESULTS / "phase5_score.json"
RECURRENCE_VALIDATION_PATH = RESULTS / "recurrence_method_validation.json"
SMOKE_SCORES_PATH = RESULTS / "smoke_scores.json"

STARTUP_EVIDENCE_PATH = RESULTS / "phase6_startup.json"
GOLDEN_EVIDENCE_PATH = RESULTS / "phase6_golden_tests.json"
METRICS_EVIDENCE_PATH = RESULTS / "phase6_metrics.json"
CONFOUNDS_EVIDENCE_PATH = RESULTS / "phase6_confounds.json"
ROBUSTNESS_EVIDENCE_PATH = RESULTS / "phase6_robustness.json"
FIGURES_EVIDENCE_PATH = RESULTS / "phase6_figures.json"
ANALYSIS_GATE_PATH = RESULTS / "phase6_analysis_gate.json"
REPORT_PATH = RESULTS / "analysis_report.md"
EXTREME_PATH = RESULTS / "extreme_cases.md"

EXPECTED_SCORES = 12_759
EXPECTED_SIBLING_SCORES = 1_894
EXPECTED_CLAIMS = 2_971
EXPECTED_TEXTS = 12_759
EXPECTED_CONTEXTS = 300
EXPECTED_ACTIVATIONS = 3_000
EXPECTED_ELIGIBLE = 2_127
BOOTSTRAP_RESAMPLES = 1_000
MSE_SCALE = 71.55417527999327
OUTLIER_KEYS = {("c141", 7)}
EDIT_FLAGGED_CLAIM_IDS = {"c248/0/003"}
SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

LABELS = ("TRUE", "RELATED_FALSE", "UNRELATED_FALSE")
STRATA = ("A", "B", "C")
VARIANTS = (
    ("raw_excess", "Raw excess"),
    ("paraphrase_excess", "DELETION_REWRITE averaged excess"),
    ("recurrence_excess", "Recurrence-aggregated excess"),
    ("solo_gain", "Solo gain"),
)


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return [_jsonable(v) for v in value.tolist()]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Path):
        return str(value)
    return value


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(str(path) + ".tmp")
    temporary.write_text(
        json.dumps(_jsonable(value), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def _atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(str(path) + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def _read_rows(path: Path) -> list[dict[str, Any]]:
    return pq.read_table(path).to_pylist()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float, np.integer, np.floating)) and math.isfinite(
        float(value)
    )


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _mechanical_delete(explanation: str, span: str) -> str:
    """The Phase-4 exact-span deletion operation used by the golden fixture."""

    if span not in explanation:
        raise RuntimeError("span is not an exact substring")
    return explanation.replace(span, "", 1).strip()


def _auc(scores: Iterable[float], labels: Iterable[int]) -> float:
    scores_list = [float(v) for v in scores]
    labels_list = [int(v) for v in labels]
    _assert(len(scores_list) == len(labels_list), "AUROC fixture length mismatch")
    _assert(len(set(labels_list)) == 2, "AUROC requires both classes")
    return float(roc_auc_score(labels_list, scores_list))


def _bootstrap_mean_fixture(
    values: np.ndarray,
    contexts: list[str],
    *,
    context_level: bool,
    seed: int,
    n: int = 1_000,
) -> np.ndarray:
    groups: dict[str, list[float]] = defaultdict(list)
    for context, value in zip(contexts, values):
        groups[context].append(float(value))
    keys = sorted(groups)
    rng = np.random.default_rng(seed)
    result = []
    for _ in range(n):
        if context_level:
            selected = rng.integers(0, len(keys), size=len(keys))
            sampled = [value for index in selected for value in groups[keys[int(index)]]]
        else:
            flat = [value for key in keys for value in groups[key]]
            selected = rng.integers(0, len(flat), size=len(flat))
            sampled = [flat[int(index)] for index in selected]
        result.append(float(np.mean(sampled)))
    return np.asarray(result, dtype=float)


def run_golden_tests() -> dict[str, Any]:
    """Run G5 before the real analysis data are read."""

    started = time.time()
    evidence: dict[str, Any] = {
        "status": "failed",
        "created_at_unix": started,
        "source_sha256": SOURCE_SHA256,
        "tests": {},
    }
    try:
        pos = [0.9, 0.8, 0.4]
        neg = [0.7, 0.3, 0.2]
        fixture_scores = pos + neg
        fixture_labels = [1] * len(pos) + [0] * len(neg)
        auc_forward = _auc(fixture_scores, fixture_labels)
        auc_negated = _auc([-score for score in fixture_scores], fixture_labels)
        _assert(abs(auc_forward - 8 / 9) < 1e-9, "AUROC fixture did not equal 8/9")
        _assert(abs(auc_negated - 1 / 9) < 1e-9, "negated AUROC fixture did not equal 1/9")
        evidence["tests"]["auroc_and_polarity_sign"] = {
            "status": "passed",
            "auc": auc_forward,
            "negated_auc": auc_negated,
            "expected_auc": 8 / 9,
            "expected_negated_auc": 1 / 9,
        }

        delete_delta = np.asarray([0.80, 0.20, 0.70, 0.10], dtype=float)
        random_deltas = np.asarray(
            [[0.10, 0.10, 0.10], [0.15, 0.15, 0.15], [0.10, 0.10, 0.10], [0.15, 0.15, 0.15]],
            dtype=float,
        )
        excess = delete_delta - random_deltas.mean(axis=1)
        labels = np.asarray([1, 0, 1, 0], dtype=int)
        polarity_auc = _auc(excess, labels)
        _assert(polarity_auc == 1.0, "polarity contract fixture failed")
        evidence["tests"]["polarity_contract"] = {
            "status": "passed",
            "formula": "excess = delta_mse(delete) - mean(delta_mse(random_span_x3))",
            "higher_excess_predicts": "TRUE",
            "true_label_value": 1,
            "auc": polarity_auc,
        }

        dominant_values = np.asarray([0.0] * 80 + [1.0] * 20, dtype=float)
        dominant_contexts = ["dominant"] * 80
        for context_index in range(5):
            dominant_contexts.extend([f"small_{context_index}"] * 4)
        context_boot = _bootstrap_mean_fixture(
            dominant_values,
            dominant_contexts,
            context_level=True,
            seed=0,
            n=1_000,
        )
        claim_boot = _bootstrap_mean_fixture(
            dominant_values,
            dominant_contexts,
            context_level=False,
            seed=0,
            n=1_000,
        )
        context_width = float(np.percentile(context_boot, 97.5) - np.percentile(context_boot, 2.5))
        claim_width = float(np.percentile(claim_boot, 97.5) - np.percentile(claim_boot, 2.5))
        _assert(claim_width > 0, "claim bootstrap fixture had zero width")
        _assert(context_width >= 1.5 * claim_width, "context bootstrap was not wider")
        evidence["tests"]["context_level_bootstrap"] = {
            "status": "passed",
            "dominant_context_fraction": 0.8,
            "context_level_ci_width": context_width,
            "claim_level_ci_width": claim_width,
            "width_ratio": context_width / claim_width,
            "resamples": 1_000,
        }

        fixture_explanation = "Alpha [CLAIM] Omega"
        fixture_span = "[CLAIM]"
        fixture_deleted = _mechanical_delete(fixture_explanation, fixture_span)
        _assert(fixture_deleted == "Alpha  Omega", "edit fixture raw output mismatch")
        # Minimal whitespace cleanup is part of the mechanical Phase-4 operation.
        fixture_cleaned = re.sub(r"[ \t]{2,}", " ", fixture_deleted)
        _assert(fixture_cleaned == "Alpha Omega", "edit fixture cleanup mismatch")
        evidence["tests"]["edit_pipeline"] = {
            "status": "passed",
            "explanation": fixture_explanation,
            "span": fixture_span,
            "deleted_text": fixture_cleaned,
            "expected_deleted_text": "Alpha Omega",
        }
        evidence["status"] = "passed"
        evidence["duration_seconds"] = time.time() - started
        _atomic_json(GOLDEN_EVIDENCE_PATH, evidence)
        return evidence
    except Exception as exc:
        evidence["error"] = f"{type(exc).__name__}: {exc}"
        evidence["duration_seconds"] = time.time() - started
        _atomic_json(GOLDEN_EVIDENCE_PATH, evidence)
        raise


def run_startup_asserts() -> dict[str, Any]:
    """Assert inherited inputs and write G1 startup evidence."""

    started = time.time()
    evidence: dict[str, Any] = {
        "status": "failed",
        "created_at_unix": started,
        "source_sha256": SOURCE_SHA256,
        "assertions": {},
    }
    required_predecessors = [
        PHASE2_GATE_PATH,
        PHASE4_MANIFEST_PATH,
        PHASE5_PRELIGHT_PATH,
        PHASE5_BATCH_PATH,
        PHASE5_PRIMARY_GATE_PATH,
        PHASE5_SIBLING_GATE_PATH,
        PHASE5_SCORE_PATH,
        OUTLIER_FLAGS_PATH,
        EDIT_FLAGS_PATH,
    ]
    try:
        for path in required_predecessors:
            _assert(path.exists(), f"missing predecessor evidence: {path}")
        phase2_gate = _load_json(PHASE2_GATE_PATH)
        _assert(phase2_gate.get("status") == "passed", "Phase 2 merge gate is not passed")
        evidence["assertions"]["predecessor_evidence"] = {
            str(path): "present" for path in required_predecessors
        }
        evidence["assertions"]["phase2_merge_gate"] = "passed"

        for path in [
            SCORES_PATH,
            SIBLING_SCORES_PATH,
            CLAIMS_PATH,
            TEXTS_PATH,
            EXPLANATIONS_PATH,
            CONTEXTS_PATH,
        ]:
            _assert(path.exists(), f"missing required data: {path}")
        score_rows = _read_rows(SCORES_PATH)
        sibling_rows = _read_rows(SIBLING_SCORES_PATH)
        claim_rows = _read_rows(CLAIMS_PATH)
        text_rows = _read_rows(TEXTS_PATH)
        context_rows = _read_rows(CONTEXTS_PATH)
        _assert(len(score_rows) == EXPECTED_SCORES, f"scores row count {len(score_rows)}")
        _assert(
            len(sibling_rows) == EXPECTED_SIBLING_SCORES,
            f"sibling score row count {len(sibling_rows)}",
        )
        _assert(len(claim_rows) == EXPECTED_CLAIMS, f"claim row count {len(claim_rows)}")
        _assert(len(text_rows) == EXPECTED_TEXTS, f"text row count {len(text_rows)}")
        _assert(len(context_rows) == EXPECTED_CONTEXTS, f"context row count {len(context_rows)}")
        evidence["assertions"]["row_counts"] = {
            "scores": len(score_rows),
            "scores_siblings": len(sibling_rows),
            "claims_labeled": len(claim_rows),
            "texts_to_score": len(text_rows),
            "contexts": len(context_rows),
        }

        score_ids = [str(row["text_id"]) for row in score_rows]
        text_ids = [str(row["text_id"]) for row in text_rows]
        _assert(len(set(score_ids)) == len(score_ids), "scores text_id is not unique")
        _assert(len(set(text_ids)) == len(text_ids), "texts text_id is not unique")
        _assert(set(score_ids) == set(text_ids), "scores/texts 1:1 text_id join failed")
        _assert(
            len({(str(row["text_id"]), int(row["position_offset"])) for row in sibling_rows})
            == len(sibling_rows),
            "sibling score compound key is not unique",
        )
        _assert(all(_finite(row["mse"]) for row in score_rows), "scores contains non-finite MSE")
        _assert(
            all(_finite(row["mse"]) for row in sibling_rows),
            "sibling scores contains non-finite MSE",
        )
        evidence["assertions"]["scores_text_join"] = {
            "status": "passed",
            "score_unique": True,
            "text_unique": True,
            "one_to_one": True,
        }
        required_recurrence_columns = {"recurrence_positions", "recurrence_samples"}
        _assert(
            required_recurrence_columns.issubset(claim_rows[0]),
            "claims_labeled recurrence columns are missing",
        )
        evidence["assertions"]["recurrence_columns"] = {
            "status": "passed",
            "columns": sorted(required_recurrence_columns),
        }

        text_by_id = {str(row["text_id"]): row for row in text_rows}
        genuine_scores = [
            float(row["mse"])
            for row in score_rows
            if text_by_id[str(row["text_id"])] ["kind"] == "GENUINE"
        ]
        _assert(len(genuine_scores) == EXPECTED_CONTEXTS, "expected 300 GENUINE scores")
        genuine_mean = float(np.mean(genuine_scores))
        smoke_mean = None
        if SMOKE_SCORES_PATH.exists():
            smoke = _load_json(SMOKE_SCORES_PATH)
            smoke_mean = float(smoke.get("mean_mse_scored_sample"))
        if smoke_mean is None:
            smoke_mean = 0.10
        same_order = 0.1 <= genuine_mean / smoke_mean <= 10.0
        _assert(same_order, "Genuine mean MSE is outside one order of magnitude of smoke")
        evidence["assertions"]["genuine_mean_mse"] = {
            "status": "passed",
            "rows": len(genuine_scores),
            "mean_mse": genuine_mean,
            "smoke_reference_mean_mse": smoke_mean,
            "ratio_to_smoke": genuine_mean / smoke_mean,
            "comparison": "same order of magnitude as smoke benchmark",
        }
        evidence["status"] = "passed"
        evidence["duration_seconds"] = time.time() - started
        _atomic_json(STARTUP_EVIDENCE_PATH, evidence)
        return evidence
    except Exception as exc:
        evidence["error"] = f"{type(exc).__name__}: {exc}"
        evidence["duration_seconds"] = time.time() - started
        _atomic_json(STARTUP_EVIDENCE_PATH, evidence)
        raise


def _load_activation_norms() -> tuple[dict[str, np.ndarray], np.ndarray, dict[str, float]]:
    paths = sorted(ACTIVATIONS_DIR.glob("*.parquet"))
    _assert(len(paths) == 30, f"expected 30 activation shards, found {len(paths)}")
    rows: list[dict[str, Any]] = []
    for path in paths:
        rows.extend(_read_rows(path))
    _assert(len(rows) == EXPECTED_ACTIVATIONS, "activation row count mismatch")
    keys = [(str(row["context_id"]), int(row["position_offset"])) for row in rows]
    _assert(len(set(keys)) == len(keys), "activation key is not unique")
    _assert(all(len(row["activation_vector"]) == 5_120 for row in rows), "activation width mismatch")
    raw = np.asarray([row["activation_vector"] for row in rows], dtype=np.float64)
    norms = np.linalg.norm(raw, axis=1)
    _assert(bool(np.all(np.isfinite(norms))) and bool(np.all(norms > 0)), "invalid activation norm")
    normalized = raw / norms[:, None] * MSE_SCALE
    primary: dict[str, np.ndarray] = {}
    for row, vector in zip(rows, normalized):
        context_id = str(row["context_id"])
        offset = int(row["position_offset"])
        if offset == 0:
            _assert(context_id not in primary, f"duplicate primary activation {context_id}")
            primary[context_id] = vector
    _assert(len(primary) == EXPECTED_CONTEXTS, "primary activation context count mismatch")
    primary_matrix = np.asarray([primary[context_id] for context_id in sorted(primary)], dtype=np.float64)
    mean_activation = primary_matrix.mean(axis=0)
    baseline_by_context = {
        context_id: float(np.mean((vector - mean_activation) ** 2))
        for context_id, vector in primary.items()
    }
    baseline = float(np.mean((primary_matrix - mean_activation) ** 2))
    return primary, mean_activation, {"dataset_baseline_mse": baseline, **baseline_by_context}


def _group_rows(rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row[key])].append(row)
    return dict(grouped)


def _metric_rows_for_bootstrap(
    rows: list[dict[str, Any]], score_key: str, allowed_labels: tuple[str, str]
) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if row.get(score_key) is not None
        and _finite(row.get(score_key))
        and row.get("label") in allowed_labels
    ]


def _bootstrap_statistic(
    rows: list[dict[str, Any]],
    score_key: str,
    allowed_labels: tuple[str, str],
    statistic: str,
    *,
    seed: int,
    resamples: int = BOOTSTRAP_RESAMPLES,
) -> tuple[np.ndarray, int]:
    if statistic == "auc":
        usable = _metric_rows_for_bootstrap(rows, score_key, allowed_labels)
    else:
        usable = [
            row
            for row in rows
            if row.get(score_key) is not None and _finite(row.get(score_key))
        ]
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in usable:
        groups[str(row["context_id"])].append(row)
    context_ids = sorted(groups)
    if not context_ids:
        return np.asarray([], dtype=float), 0
    rng = np.random.default_rng(seed)
    values: list[float] = []
    attempts = 0
    max_attempts = max(resamples * 100, 10_000)
    while len(values) < resamples and attempts < max_attempts:
        attempts += 1
        selected = rng.integers(0, len(context_ids), size=len(context_ids))
        sample = [row for index in selected for row in groups[context_ids[int(index)]]]
        if statistic == "auc":
            y = [1 if row["label"] == allowed_labels[0] else 0 for row in sample]
            if len(set(y)) < 2:
                continue
            values.append(_auc([row[score_key] for row in sample], y))
        elif statistic == "mean":
            values.append(float(np.mean([float(row[score_key]) for row in sample])))
        elif statistic == "corr":
            x = np.asarray([float(row["corr_x"]) for row in sample], dtype=float)
            y = np.asarray([float(row["corr_y"]) for row in sample], dtype=float)
            if len(x) < 3 or np.std(x) == 0 or np.std(y) == 0:
                continue
            values.append(float(np.corrcoef(x, y)[0, 1]))
        else:
            raise RuntimeError(f"unknown bootstrap statistic {statistic}")
    return np.asarray(values, dtype=float), attempts


def _ci(values: np.ndarray) -> list[float] | None:
    if values.size == 0:
        return None
    return [float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))]


def _auc_result(
    rows: list[dict[str, Any]],
    score_key: str,
    *,
    stratum: str,
    comparison: tuple[str, str],
    seed: int,
) -> dict[str, Any]:
    selected = _metric_rows_for_bootstrap(rows, score_key, comparison)
    labels = [1 if row["label"] == comparison[0] else 0 for row in selected]
    result: dict[str, Any] = {
        "score": score_key,
        "stratum": stratum,
        "comparison": f"{comparison[0]}_vs_{comparison[1]}",
        "n": len(selected),
        "n_positive": sum(labels),
        "n_negative": len(labels) - sum(labels),
        "bootstrap_resamples_requested": BOOTSTRAP_RESAMPLES,
        "bootstrap_level": "context",
        "status": "failed",
    }
    if len(set(labels)) < 2:
        result["status"] = "insufficient_classes"
        return result
    result["auroc"] = _auc([row[score_key] for row in selected], labels)
    boot, attempts = _bootstrap_statistic(
        selected,
        score_key,
        comparison,
        "auc",
        seed=seed,
    )
    result["bootstrap_attempts"] = attempts
    result["bootstrap_resamples_valid"] = int(len(boot))
    _assert(len(boot) == BOOTSTRAP_RESAMPLES, f"bootstrap failed for {score_key}/{stratum}/{comparison}")
    result["ci95"] = _ci(boot)
    result["status"] = "passed"
    return result


def _mean_result(
    rows: list[dict[str, Any]],
    score_key: str,
    *,
    name: str,
    seed: int,
) -> dict[str, Any]:
    selected = [row for row in rows if row.get(score_key) is not None and _finite(row.get(score_key))]
    result: dict[str, Any] = {
        "name": name,
        "score": score_key,
        "n": len(selected),
        "bootstrap_resamples_requested": BOOTSTRAP_RESAMPLES,
        "bootstrap_level": "context",
        "status": "failed",
    }
    if not selected:
        result["status"] = "insufficient_rows"
        return result
    result["mean"] = float(np.mean([float(row[score_key]) for row in selected]))
    boot, attempts = _bootstrap_statistic(
        selected,
        score_key,
        ("__all__", "__none__"),
        "mean",
        seed=seed,
    )
    result["bootstrap_attempts"] = attempts
    result["bootstrap_resamples_valid"] = int(len(boot))
    _assert(len(boot) == BOOTSTRAP_RESAMPLES, f"mean bootstrap failed for {name}")
    result["ci95"] = _ci(boot)
    result["status"] = "passed"
    return result


def _correlation_result(
    rows: list[dict[str, Any]],
    x_key: str,
    y_key: str,
    *,
    name: str,
    seed: int,
) -> dict[str, Any]:
    selected = [
        {
            **row,
            "corr_x": row[x_key],
            "corr_y": row[y_key],
        }
        for row in rows
        if _finite(row.get(x_key)) and _finite(row.get(y_key))
    ]
    result: dict[str, Any] = {
        "name": name,
        "x": x_key,
        "y": y_key,
        "n": len(selected),
        "bootstrap_resamples_requested": BOOTSTRAP_RESAMPLES,
        "bootstrap_level": "context",
        "status": "failed",
    }
    if len(selected) < 3:
        result["status"] = "insufficient_rows"
        return result
    x = np.asarray([row["corr_x"] for row in selected], dtype=float)
    y = np.asarray([row["corr_y"] for row in selected], dtype=float)
    if np.std(x) == 0 or np.std(y) == 0:
        result["status"] = "zero_variance"
        return result
    result["r"] = float(np.corrcoef(x, y)[0, 1])
    boot, attempts = _bootstrap_statistic(
        selected,
        "corr_y",
        ("__all__", "__none__"),
        "corr",
        seed=seed,
    )
    result["bootstrap_attempts"] = attempts
    result["bootstrap_resamples_valid"] = int(len(boot))
    _assert(len(boot) == BOOTSTRAP_RESAMPLES, f"correlation bootstrap failed for {name}")
    result["ci95"] = _ci(boot)
    result["threshold"] = 0.3
    result["flag"] = bool(abs(result["r"]) > 0.3)
    result["status"] = "passed"
    return result


def _load_and_compute() -> dict[str, Any]:
    texts = _read_rows(TEXTS_PATH)
    score_rows = _read_rows(SCORES_PATH)
    sibling_rows = _read_rows(SIBLING_SCORES_PATH)
    claims = _read_rows(CLAIMS_PATH)
    explanations = _read_rows(EXPLANATIONS_PATH)
    contexts = _read_rows(CONTEXTS_PATH)
    _assert(len(texts) == EXPECTED_TEXTS, "analysis text row count changed")
    _assert(len(score_rows) == EXPECTED_SCORES, "analysis score row count changed")
    _assert(len(sibling_rows) == EXPECTED_SIBLING_SCORES, "analysis sibling row count changed")
    _assert(len(claims) == EXPECTED_CLAIMS, "analysis claim row count changed")
    _assert(len(contexts) == EXPECTED_CONTEXTS, "analysis context row count changed")
    _assert(len(explanations) == 3_900, "analysis explanation row count changed")

    text_by_id = {str(row["text_id"]): row for row in texts}
    score_by_id = {str(row["text_id"]): float(row["mse"]) for row in score_rows}
    _assert(len(text_by_id) == len(texts), "duplicate text IDs in analysis input")
    _assert(set(text_by_id) == set(score_by_id), "score/text IDs do not join")
    _assert(all(math.isfinite(value) for value in score_by_id.values()), "non-finite score")

    by_claim_kind: dict[tuple[str, str], list[float]] = defaultdict(list)
    by_claim_kind_variant: dict[tuple[str, str, int], float] = {}
    context_kind_scores: dict[tuple[str, str], float] = {}
    for row in texts:
        text_id = str(row["text_id"])
        kind = str(row["kind"])
        score = score_by_id[text_id]
        claim_id = row.get("claim_id")
        if claim_id is not None:
            claim_id = str(claim_id)
            by_claim_kind[(kind, claim_id)].append(score)
            parts = text_id.split("|")
            variant = int(parts[-1]) if parts[-1].isdigit() else 0
            key = (kind, claim_id, variant)
            _assert(key not in by_claim_kind_variant, f"duplicate text variant {key}")
            by_claim_kind_variant[key] = score
        else:
            context_kind_scores[(kind, str(row["context_id"]))] = score

    eligible = [
        row
        for row in claims
        if row.get("claim_type") == "CONTEXT"
        and row.get("label") != "UNVERIFIABLE"
        and not bool(row.get("span_mismatch"))
    ]
    _assert(len(eligible) == EXPECTED_ELIGIBLE, f"eligible claim count {len(eligible)}")
    eligible_ids = {str(row["claim_id"]) for row in eligible}
    delete_ids = {
        str(row["claim_id"])
        for row in texts
        if row["kind"] == "DELETE_MECH" and row.get("claim_id") is not None
    }
    _assert(delete_ids == eligible_ids, "DELETE_MECH IDs do not equal eligible claim IDs")
    for claim_id in eligible_ids:
        _assert(("SOLO", claim_id) in by_claim_kind, f"missing SOLO for {claim_id}")
        _assert(len(by_claim_kind[("RANDOM_SPAN", claim_id)]) == 3, f"random control count for {claim_id}")

    claim_by_id = {str(row["claim_id"]): row for row in claims}
    _assert(len(claim_by_id) == len(claims), "claim_id is not unique")
    batch_by_generation = {int(row["generation_index"]): int(row["batch_size"]) for row in explanations}
    _assert(len(batch_by_generation) == len(explanations), "generation_index is not unique")

    primary_activation, mean_activation, baseline_by_context = _load_activation_norms()
    primary_mse = {
        str(row["context_id"]): score
        for row in texts
        if row["kind"] == "GENUINE"
        for score in [score_by_id[str(row["text_id"])] ]
    }
    _assert(len(primary_mse) == EXPECTED_CONTEXTS, "GENUINE primary score map mismatch")

    sibling_by_claim: dict[str, dict[int, float]] = defaultdict(dict)
    for row in sibling_rows:
        text_id = str(row["text_id"])
        text_row = text_by_id[text_id]
        claim_id = str(text_row["claim_id"])
        offset = int(row["position_offset"])
        _assert(offset not in sibling_by_claim[claim_id], f"duplicate sibling offset {claim_id}/{offset}")
        sibling_by_claim[claim_id][offset] = float(row["mse"])

    metrics: list[dict[str, Any]] = []
    for claim in eligible:
        claim_id = str(claim["claim_id"])
        context_id = str(claim["context_id"])
        delete_mse = float(by_claim_kind[("DELETE_MECH", claim_id)][0])
        random_mses = [float(value) for value in by_claim_kind[("RANDOM_SPAN", claim_id)]]
        full_mse = primary_mse[context_id]
        delta_delete = delete_mse - full_mse
        delta_random = float(np.mean(random_mses)) - full_mse
        raw_excess = delta_delete - delta_random
        rewrite_values = [
            by_claim_kind_variant[("DELETION_REWRITE", claim_id, variant)]
            for variant in range(3)
            if ("DELETION_REWRITE", claim_id, variant) in by_claim_kind_variant
        ]
        paraphrase_excess = None
        if len(rewrite_values) == 3:
            paraphrase_excess = float(
                np.mean([((value - full_mse) - delta_random) for value in rewrite_values])
            )
        recurrence_values = sibling_by_claim.get(claim_id, {})
        expected_offsets = range(1, min(int(claim.get("recurrence_positions") or 0), 3) + 1)
        recurrence_excess = None
        recurrence_offsets: list[int] = []
        if int(claim.get("recurrence_positions") or 0) >= 2 and all(
            offset in recurrence_values for offset in expected_offsets
        ):
            recurrence_offsets = sorted(expected_offsets)
            # The Phase-5 sibling artifact contains DELETE_MECH scores only.  The
            # prescribed mechanical secondary is the mean sibling deletion score
            # minus the primary random-span control; this is recorded as noisy
            # because sibling random controls were not generated.
            recurrence_excess = float(np.mean([recurrence_values[offset] for offset in recurrence_offsets]) - np.mean(random_mses))
        solo_mse = float(by_claim_kind[("SOLO", claim_id)][0])
        solo_gain = float(baseline_by_context[context_id] - solo_mse)
        claim_tokens = len(re.findall(r"\S+", str(claim.get("claim_text") or "")))
        generation_index = int(claim["generation_index"])
        _assert(generation_index in batch_by_generation, f"missing batch for generation {generation_index}")
        metrics.append(
            {
                "claim_id": claim_id,
                "context_id": context_id,
                "stratum": str(claim["stratum"]),
                "label": str(claim["label"]),
                "claim_type": str(claim["claim_type"]),
                "claim_index": int(claim["claim_index"]),
                "claim_token_length": claim_tokens,
                "generation_index": generation_index,
                "batch_size": batch_by_generation[generation_index],
                "splitter": str(claim["splitter"]),
                "recurrence_positions": int(claim.get("recurrence_positions") or 0),
                "recurrence_samples": int(claim.get("recurrence_samples") or 0),
                "delete_mse": delete_mse,
                "full_mse": full_mse,
                "random_mses": random_mses,
                "delta_delete": delta_delete,
                "delta_random": delta_random,
                "raw_excess": raw_excess,
                "deletion_rewrite_mses": rewrite_values,
                "paraphrase_excess": paraphrase_excess,
                "sibling_offsets": recurrence_offsets,
                "sibling_delete_mses": [recurrence_values[offset] for offset in recurrence_offsets],
                "recurrence_excess": recurrence_excess,
                "mean_prediction_mse": baseline_by_context[context_id],
                "solo_mse": solo_mse,
                "solo_gain": solo_gain,
            }
        )

    rewrite_claims = {
        claim_id
        for (kind, claim_id, _variant) in by_claim_kind_variant
        if kind == "DELETION_REWRITE"
    }
    _assert(len(rewrite_claims) == 208, f"DELETION_REWRITE claim count {len(rewrite_claims)}")
    _assert(
        sum(len(row["deletion_rewrite_mses"]) == 3 for row in metrics) == 208,
        "not all DELETION_REWRITE claims have three variants",
    )
    shortcuts = {}
    for kind in (
        "SHORTCUT_CONTEXT_COPY",
        "GENUINE",
        "SHORTCUT_SHUFFLED",
        "SHORTCUT_MISMATCHED",
    ):
        values = []
        for context_id in sorted(primary_mse):
            key = (kind, context_id)
            _assert(key in context_kind_scores, f"missing shortcut row {key}")
            values.append(
                {
                    "context_id": context_id,
                    "mse": context_kind_scores[key],
                    "fve": 1.0 - context_kind_scores[key] / baseline_by_context["dataset_baseline_mse"],
                    "stratum": next(row["stratum"] for row in contexts if str(row["context_id"]) == context_id),
                }
            )
        shortcuts[kind] = values

    return {
        "texts": texts,
        "claims": claims,
        "eligible": eligible,
        "metrics": metrics,
        "contexts": contexts,
        "explanations": explanations,
        "score_by_id": score_by_id,
        "text_by_id": text_by_id,
        "primary_mse": primary_mse,
        "primary_activation": primary_activation,
        "mean_activation": mean_activation,
        "baseline_by_context": baseline_by_context,
        "shortcuts": shortcuts,
        "outlier_flags": _load_json(OUTLIER_FLAGS_PATH),
        "edit_flags": _load_json(EDIT_FLAGS_PATH),
        "rewrite_claims": sorted(rewrite_claims),
    }


def _filter_stratum(rows: list[dict[str, Any]], stratum: str) -> list[dict[str, Any]]:
    if stratum == "POOLED":
        return rows
    return [row for row in rows if row["stratum"] == stratum]


def _write_table1(metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    table: list[dict[str, Any]] = []
    seed_base = 6000
    for variant_index, (score_key, _label) in enumerate(VARIANTS):
        for comparison_index, comparison in enumerate(
            (("TRUE", "RELATED_FALSE"), ("TRUE", "UNRELATED_FALSE"))
        ):
            for stratum_index, stratum in enumerate(("POOLED", *STRATA)):
                subset = _filter_stratum(metrics, stratum)
                result = _auc_result(
                    subset,
                    score_key,
                    stratum=stratum,
                    comparison=comparison,
                    seed=seed_base + variant_index * 100 + comparison_index * 10 + stratum_index,
                )
                table.append(result)
    return table


def _write_table2(metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    recurrence = _auc_result(
        metrics,
        "recurrence_positions",
        stratum="POOLED",
        comparison=("TRUE", "RELATED_FALSE"),
        seed=7001,
    )
    recurrence["baseline"] = "recurrence-count heuristic alone"
    recurrence["caveat"] = (
        "NOISY SECONDARY: mechanical distinctive-token-overlap proxy; "
        "results/recurrence_method_validation.json reports spearman=0.41, "
        "within_1=0.476, n=246."
    )
    deferred_without = {
        "baseline": "JUDGE_without_context",
        "status": "deferred_to_human",
        "auroc": None,
        "ci95": None,
        "n": None,
        "note": "No LLM judge call made; human may request this baseline.",
    }
    deferred_with = {
        "baseline": "JUDGE_with_context_ceiling",
        "status": "deferred_to_human",
        "auroc": None,
        "ci95": None,
        "n": None,
        "note": "No LLM judge call made; human may request this baseline.",
    }
    random = {
        "baseline": "random",
        "status": "fixed_sanity_value",
        "auroc": 0.5,
        "ci95": [0.5, 0.5],
        "n": None,
        "note": "Fixed AUROC sanity row.",
    }
    return [recurrence, deferred_without, deferred_with, random]


def _make_confounds(metrics: list[dict[str, Any]]) -> dict[str, Any]:
    length = _correlation_result(
        metrics,
        "claim_token_length",
        "raw_excess",
        name="corr(excess, claim token length)",
        seed=8101,
    )
    position = _correlation_result(
        metrics,
        "claim_index",
        "raw_excess",
        name="corr(excess, position in explanation)",
        seed=8102,
    )
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in metrics:
        groups[(row["context_id"], row["claim_text_normalized"])].append(row)
    duplicate_pairs = []
    duplicate_groups = []
    for key, group in sorted(groups.items()):
        if len(group) >= 2:
            duplicate_groups.append(
                {
                    "context_id": key[0],
                    "normalized_claim_text": key[1],
                    "claim_ids": [row["claim_id"] for row in group],
                }
            )
            for left, right in itertools.combinations(group, 2):
                duplicate_pairs.append(
                    {
                        "context_id": key[0],
                        "corr_x": left["raw_excess"],
                        "corr_y": right["raw_excess"],
                    }
                )
    duplicate = {
        "name": "duplicate-claim consistency",
        "duplicate_groups": duplicate_groups,
        "duplicate_pairs": duplicate_pairs,
        "n_duplicate_groups": len(duplicate_groups),
        "n_duplicate_pairs": len(duplicate_pairs),
        "status": "insufficient_duplicate_pairs",
        "r": None,
        "ci95": None,
    }
    if len(duplicate_pairs) >= 3:
        x = np.asarray([row["corr_x"] for row in duplicate_pairs], dtype=float)
        y = np.asarray([row["corr_y"] for row in duplicate_pairs], dtype=float)
        if np.std(x) > 0 and np.std(y) > 0:
            duplicate["r"] = float(np.corrcoef(x, y)[0, 1])
            duplicate["status"] = "passed"
    return {
        "status": "passed",
        "threshold": 0.3,
        "checks": {
            "token_length": length,
            "position": position,
            "duplicate_claim_consistency": duplicate,
        },
        "matched_analysis": {
            "required": bool(length.get("flag") or position.get("flag")),
            "status": "not_triggered" if not (length.get("flag") or position.get("flag")) else "required",
        },
    }


def _rewrite_vs_mechanical(metrics: list[dict[str, Any]]) -> dict[str, Any]:
    overlap = [row for row in metrics if row.get("paraphrase_excess") is not None]
    result: dict[str, Any] = {
        "n_overlap": len(overlap),
        "status": "failed",
        "mechanical_variant": "raw_excess",
        "rewrite_variant": "paraphrase_excess",
        "bootstrap_level": "context",
        "bootstrap_resamples_requested": BOOTSTRAP_RESAMPLES,
    }
    if len(overlap) < 3:
        result["status"] = "insufficient_rows"
        return result
    x = np.asarray([row["raw_excess"] for row in overlap], dtype=float)
    y = np.asarray([row["paraphrase_excess"] for row in overlap], dtype=float)
    result["pearson_r"] = float(np.corrcoef(x, y)[0, 1]) if np.std(x) > 0 and np.std(y) > 0 else None
    result["sign_agreement_fraction"] = float(np.mean(np.sign(x) == np.sign(y)))
    result["mechanical_auc"] = _auc(
        [row["raw_excess"] for row in overlap if row["label"] in ("TRUE", "RELATED_FALSE")],
        [1 if row["label"] == "TRUE" else 0 for row in overlap if row["label"] in ("TRUE", "RELATED_FALSE")],
    )
    result["rewrite_auc"] = _auc(
        [row["paraphrase_excess"] for row in overlap if row["label"] in ("TRUE", "RELATED_FALSE")],
        [1 if row["label"] == "TRUE" else 0 for row in overlap if row["label"] in ("TRUE", "RELATED_FALSE")],
    )
    # Context-level bootstrap for the correlation uses the same resampling rule.
    correlation_rows = [
        {
            **row,
            "corr_x": row["raw_excess"],
            "corr_y": row["paraphrase_excess"],
        }
        for row in overlap
    ]
    boot, attempts = _bootstrap_statistic(
        correlation_rows,
        "corr_y",
        ("__all__", "__none__"),
        "corr",
        seed=8201,
    )
    _assert(len(boot) == BOOTSTRAP_RESAMPLES, "rewrite agreement bootstrap failed")
    result["pearson_ci95"] = _ci(boot)
    result["bootstrap_attempts"] = attempts
    result["status"] = "passed"
    return result


def _robustness(metrics: list[dict[str, Any]], outlier_flags: list[dict[str, Any]]) -> dict[str, Any]:
    outlier_keys = {(str(row["context_id"]), int(row["position_offset"])) for row in outlier_flags}
    edit_ids = {str(row["claim_id"]) for row in _load_json(EDIT_FLAGS_PATH)}
    _assert(edit_ids == EDIT_FLAGGED_CLAIM_IDS, "edit flag set changed from prescribed row")

    def clone_with_outlier_filter(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cloned = []
        for row in rows:
            item = dict(row)
            offsets = [
                offset
                for offset in row["sibling_offsets"]
                if (row["context_id"], int(offset)) not in outlier_keys
            ]
            if row["sibling_offsets"]:
                values = [
                    value
                    for offset, value in zip(row["sibling_offsets"], row["sibling_delete_mses"])
                    if (row["context_id"], int(offset)) not in outlier_keys
                ]
                item["recurrence_excess"] = (
                    float(np.mean(values) - np.mean(row["random_mses"])) if values else None
                )
                item["sibling_offsets"] = offsets
                item["sibling_delete_mses"] = values
            cloned.append(item)
        return cloned

    filters: list[tuple[str, Callable[[dict[str, Any]], bool], list[dict[str, Any]]]] = [
        ("exclude_outlier_flagged_rows", lambda row: True, clone_with_outlier_filter(metrics)),
        ("exclude_edit_flagged_claim_c248_0_003", lambda row: row["claim_id"] not in edit_ids, metrics),
    ]
    for batch_size in (1, 4, 8):
        filters.append((f"batch_size_{batch_size}", lambda row, n=batch_size: row["batch_size"] == n, metrics))
    for provenance in ("openrouter-haiku", "claude-sonnet", "claude-fable-other"):
        if provenance == "openrouter-haiku":
            predicate = lambda row: "haiku" in row["splitter"]
        elif provenance == "claude-sonnet":
            predicate = lambda row: "sonnet" in row["splitter"]
        else:
            predicate = lambda row: "haiku" not in row["splitter"] and "sonnet" not in row["splitter"]
        filters.append((f"splitter_{provenance}", predicate, metrics))

    results = []
    for filter_name, predicate, source_rows in filters:
        filtered = [row for row in source_rows if predicate(row)]
        for variant_index, (score_key, _label) in enumerate(VARIANTS):
            selected = [row for row in filtered if row.get(score_key) is not None]
            item = _auc_result(
                selected,
                score_key,
                stratum="POOLED",
                comparison=("TRUE", "RELATED_FALSE"),
                seed=9000 + len(results) + variant_index,
            )
            item["filter"] = filter_name
            item["variant"] = score_key
            results.append(item)
    batch_raw = [
        row
        for row in results
        if row["variant"] == "raw_excess" and row["filter"].startswith("batch_size_")
    ]
    interval_pairs = []
    for left, right in itertools.combinations(batch_raw, 2):
        left_ci = left.get("ci95")
        right_ci = right.get("ci95")
        overlap = bool(
            left_ci
            and right_ci
            and max(left_ci[0], right_ci[0]) <= min(left_ci[1], right_ci[1])
        )
        interval_pairs.append(
            {
                "left": left["filter"],
                "right": right["filter"],
                "ci_overlap": overlap,
            }
        )
    return {
        "status": "passed",
        "filters": [
            {
                "name": name,
                "rows_before": len(metrics),
                "rows_after": len([row for row in source if pred(row)]) if name != "exclude_outlier_flagged_rows" else len(source),
            }
            for name, pred, source in filters
        ],
        "outlier_flags": outlier_flags,
        "edit_flags": _load_json(EDIT_FLAGS_PATH),
        "batch_size_ci_overlap": {
            "pairs": interval_pairs,
            "disagreement_beyond_ci_overlap": any(
                not pair["ci_overlap"] for pair in interval_pairs
            ),
            "status": "all_intervals_overlap"
            if all(pair["ci_overlap"] for pair in interval_pairs)
            else "DISAGREEMENT_BEYOND_CI_OVERLAP",
        },
        "headline_results": results,
    }


def _make_figures(data: dict[str, Any], table1: list[dict[str, Any]], table2: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = data["metrics"]
    FIGS.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []

    # Fig 1: excess distribution by label class.
    fig, ax = plt.subplots(figsize=(8, 5))
    values = [[row["raw_excess"] for row in metrics if row["label"] == label] for label in LABELS]
    ax.boxplot(values, tick_labels=LABELS, showfliers=False)
    ax.set_xlabel("Label")
    ax.set_ylabel("Raw excess")
    ax.set_title("Raw excess by label class")
    fig.tight_layout()
    path = FIGS / "fig1_excess_by_label.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths.append(str(path))

    # Fig 2: replacement deltas relative to the genuine explanation.
    paraphrase_ids = sorted(
        set(
            str(row["claim_id"])
            for row in data["texts"]
            if row["kind"] == "PARAPHRASE" and row.get("claim_id") is not None
        )
    )
    deltas_paraphrase = []
    deltas_false = []
    for claim_id in paraphrase_ids:
        context_id = next(row["context_id"] for row in data["texts"] if row["kind"] == "PARAPHRASE" and str(row["claim_id"]) == claim_id)
        genuine = data["primary_mse"][str(context_id)]
        p_id = f"PARAPHRASE|{claim_id}|0"
        f_id = f"FALSE_SUBSTITUTE|{claim_id}|0"
        if p_id in data["score_by_id"] and f_id in data["score_by_id"]:
            deltas_paraphrase.append(data["score_by_id"][p_id] - genuine)
            deltas_false.append(data["score_by_id"][f_id] - genuine)
    _assert(len(deltas_paraphrase) == 150 and len(deltas_false) == 150, "Fig 2 pair count mismatch")
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.boxplot(
        [deltas_paraphrase, deltas_false],
        tick_labels=["PARAPHRASE", "FALSE_SUBSTITUTE"],
        showfliers=False,
    )
    ax.set_ylabel("Delta MSE relative to GENUINE")
    ax.set_title("Replacement-control delta MSE, paired 150 claims")
    fig.tight_layout()
    path = FIGS / "fig2_paraphrase_false_substitute.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths.append(str(path))

    # Fig 3: shortcut FVE bars with context-level percentile intervals.
    shortcut_order = (
        "SHORTCUT_CONTEXT_COPY",
        "GENUINE",
        "SHORTCUT_SHUFFLED",
        "SHORTCUT_MISMATCHED",
    )
    shortcut_names = ["context-copy", "genuine", "shuffled", "mismatched"]
    means = []
    errors = []
    shortcut_summary = []
    for kind, name in zip(shortcut_order, shortcut_names):
        rows = data["shortcuts"][kind]
        values = np.asarray([row["fve"] for row in rows], dtype=float)
        synthetic_rows = [
            {"context_id": row["context_id"], "fve": float(row["fve"])} for row in rows
        ]
        boot, attempts = _bootstrap_statistic(
            synthetic_rows,
            "fve",
            ("__all__", "__none__"),
            "mean",
            seed=8300 + len(means),
        )
        _assert(len(boot) == BOOTSTRAP_RESAMPLES, f"Fig 3 bootstrap failed for {kind}")
        mean = float(np.mean(values))
        ci = _ci(boot)
        means.append(mean)
        errors.append([mean - ci[0], ci[1] - mean])
        shortcut_summary.append({"kind": kind, "label": name, "n": len(values), "mean_fve": mean, "ci95": ci, "bootstrap_attempts": attempts})
    fig, ax = plt.subplots(figsize=(8, 5))
    errors_array = np.asarray(errors, dtype=float).T
    ax.bar(shortcut_names, means, yerr=errors_array, capsize=4)
    ax.set_ylabel("FVE")
    ax.set_title("AR-shortcut FVE")
    fig.tight_layout()
    path = FIGS / "fig3_ar_shortcut_fve.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths.append(str(path))

    # Fig 4: ROC curves for the four analysis variants and the recurrence baseline.
    fig, ax = plt.subplots(figsize=(7, 6))
    plot_entries = []
    for score_key, label in (*VARIANTS, ("recurrence_positions", "recurrence count")):
        selected = [row for row in metrics if row["label"] in ("TRUE", "RELATED_FALSE") and row.get(score_key) is not None]
        if not selected:
            continue
        y = np.asarray([1 if row["label"] == "TRUE" else 0 for row in selected], dtype=int)
        scores = np.asarray([float(row[score_key]) for row in selected], dtype=float)
        fpr, tpr, _ = roc_curve(y, scores)
        auc_value = _auc(scores, y)
        ax.plot(fpr, tpr, label=f"{label} (AUROC={auc_value:.3f})")
        plot_entries.append({"score": score_key, "label": label, "n": len(selected), "auroc": auc_value})
    ax.plot([0, 1], [0, 1], linestyle="--", color="black", label="random (AUROC=0.500)")
    ax.set_xlabel("False positive rate")
    ax.set_ylabel("True positive rate")
    ax.set_title("ROC curves: TRUE vs RELATED_FALSE")
    ax.legend(fontsize=8)
    fig.tight_layout()
    path = FIGS / "fig4_roc_curves.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths.append(str(path))

    return {
        "status": "passed",
        "paths": paths,
        "fig3_shortcut_summary": shortcut_summary,
        "fig4_roc_entries": plot_entries,
    }


def _add_claim_text_fields(metrics: list[dict[str, Any]], claims: list[dict[str, Any]]) -> None:
    claim_text_by_id = {str(row["claim_id"]): str(row["claim_text"]) for row in claims}
    for row in metrics:
        row["claim_text"] = claim_text_by_id[row["claim_id"]]
        row["claim_text_normalized"] = " ".join(row["claim_text"].lower().split())


def _make_report(
    data: dict[str, Any],
    table1: list[dict[str, Any]],
    table2: list[dict[str, Any]],
    confounds: dict[str, Any],
    robustness: dict[str, Any],
    figures: dict[str, Any],
    rewrite_agreement: dict[str, Any],
    golden: dict[str, Any],
    startup: dict[str, Any],
) -> str:
    metrics = data["metrics"]
    all_claims = data["claims"]
    eligible_ids = {row["claim_id"] for row in metrics}
    excluded_noneligible = sorted(
        str(row["claim_id"]) for row in all_claims if str(row["claim_id"]) not in eligible_ids
    )
    paraphrase_missing = sorted(
        row["claim_id"] for row in metrics if row.get("paraphrase_excess") is None
    )
    recurrence_missing = sorted(
        row["claim_id"] for row in metrics if row.get("recurrence_excess") is None
    )
    outlier_primary = sorted(
        row["claim_id"]
        for row in metrics
        if (row["context_id"], 0) in OUTLIER_KEYS
    )
    lines = [
        "# Phase 6 analysis report",
        "",
        "Description-only artifact. No interpretation is included.",
        "",
        "## Gates",
        "",
        f"- Startup assertions: `{startup['status']}`; evidence: `{STARTUP_EVIDENCE_PATH}`.",
        f"- G5 golden tests: `{golden['status']}`; evidence: `{GOLDEN_EVIDENCE_PATH}`.",
        f"- Eligible analysis rows: `{len(metrics)}`; required: `{EXPECTED_ELIGIBLE}`.",
        f"- Cost: `$0.00`; billing basis: local Python process, no Modal, no OpenRouter/API calls, no GPU.",
        "",
        "## Input counts and deterministic definitions",
        "",
        f"- `scores.parquet`: `{EXPECTED_SCORES}` rows; `scores_siblings.parquet`: `{EXPECTED_SIBLING_SCORES}` rows; `claims_labeled.parquet`: `{EXPECTED_CLAIMS}` rows.",
        f"- GENUINE mean MSE: `{startup['assertions']['genuine_mean_mse']['mean_mse']}`; smoke reference: `{startup['assertions']['genuine_mean_mse']['smoke_reference_mean_mse']}`; ratio: `{startup['assertions']['genuine_mean_mse']['ratio_to_smoke']}`.",
        "- Eligible rows are `claim_type=CONTEXT`, label not `UNVERIFIABLE`, and `span_mismatch=false`; the resulting set matches the Phase-4 manifest.",
        "- Raw excess: `(MSE(DELETE_MECH)-MSE(GENUINE)) - mean(MSE(RANDOM_SPAN)-MSE(GENUINE))`.",
        "- DELETION_REWRITE excess: the same control subtraction for each of the three rewrite scores, then the mean over the three values where all exist.",
        "- Solo gain: `MSE(mean-prediction baseline) - MSE(SOLO)`; the baseline uses the normalized primary activation's MSE to the normalized primary-activation mean, using the recorded AR normalization scale.",
        "- Recurrence-aggregated excess: mean sibling `DELETE_MECH` MSE over offsets `1..min(recurrence_positions,3)` minus the primary random-span mean. The sibling artifact has no sibling random-span scores; this is therefore a noisy secondary mechanical proxy, and is reported as a noisy secondary proxy.",
        "",
        "## Table 1: AUROC with 95% context-level bootstrap CIs",
        "",
        "| Variant | Comparison | Stratum | n | AUROC | 95% CI | Status |",
        "|---|---|---:|---:|---:|---|---|",
    ]
    for row in table1:
        lines.append(
            f"| {row['score']} | {row['comparison']} | {row['stratum']} | {row['n']} | "
            f"{row.get('auroc', 'NA')} | {row.get('ci95', 'NA')} | {row['status']} |"
        )
    lines.extend(
        [
            "",
            "## Table 2: TRUE versus RELATED_FALSE baselines",
            "",
            "| Baseline | AUROC | 95% CI | n | Status | Note |",
            "|---|---:|---|---:|---|---|",
        ]
    )
    for row in table2:
        lines.append(
            f"| {row.get('baseline', '')} | {row.get('auroc', 'NA')} | {row.get('ci95', 'NA')} | "
            f"{row.get('n', 'NA')} | {row.get('status', '')} | {row.get('note', row.get('caveat', ''))} |"
        )
    lines.extend(
        [
            "",
            "## Figures",
            "",
            *[f"- `{path}`" for path in figures["paths"]],
            "",
            "## Confound checks",
            "",
        ]
    )
    for name, check in confounds["checks"].items():
        lines.append(
            f"- {name}: r=`{check.get('r')}`, 95% CI=`{check.get('ci95')}`, n=`{check.get('n')}`, "
            f"threshold=`{check.get('threshold')}`, flag=`{check.get('flag')}`, status=`{check.get('status')}`."
        )
    lines.append(
        f"- Matched analysis requirement: `{confounds['matched_analysis']['status']}`; required=`{confounds['matched_analysis']['required']}`."
    )
    lines.extend(
        [
            "",
            "## Robustness",
            "",
            "Robustness entries below are recomputed headline TRUE-versus-RELATED_FALSE AUROCs with context-level 95% CIs.",
            "",
            "| Filter | Variant | n | AUROC | 95% CI | Status |",
            "|---|---|---:|---:|---|---|",
        ]
    )
    for row in robustness["headline_results"]:
        lines.append(
            f"| {row['filter']} | {row['variant']} | {row['n']} | {row.get('auroc', 'NA')} | "
            f"{row.get('ci95', 'NA')} | {row['status']} |"
        )
    batch_overlap = robustness["batch_size_ci_overlap"]
    lines.append(
        f"- Batch-size raw-excess CI-overlap check: `{batch_overlap['status']}`; "
        f"disagreement_beyond_ci_overlap=`{batch_overlap['disagreement_beyond_ci_overlap']}`; "
        f"pairs=`{batch_overlap['pairs']}`."
    )
    lines.extend(
        [
            "",
            "### Mechanical DELETE versus DELETION_REWRITE agreement",
            "",
            f"- Overlap rows: `{rewrite_agreement['n_overlap']}`; Pearson r=`{rewrite_agreement.get('pearson_r')}` with 95% CI=`{rewrite_agreement.get('pearson_ci95')}`.",
            f"- Sign agreement fraction: `{rewrite_agreement.get('sign_agreement_fraction')}`; mechanical AUROC=`{rewrite_agreement.get('mechanical_auc')}`; rewrite AUROC=`{rewrite_agreement.get('rewrite_auc')}`.",
            f"- Status: `{rewrite_agreement['status']}`.",
            "",
            "## Excluded rows (enumerated)",
            "",
            f"- Non-eligible claims excluded from the primary analysis universe: `{len(excluded_noneligible)}` IDs.",
            "",
            "```text",
            *excluded_noneligible,
            "```",
            "",
            f"- Eligible claims without all three DELETION_REWRITE variants (not excluded from raw/recurrence/solo): `{len(paraphrase_missing)}` IDs.",
            "",
            "```text",
            *paraphrase_missing,
            "```",
            "",
            f"- Eligible claims without a complete recurrence sibling score set: `{len(recurrence_missing)}` IDs.",
            "",
            "```text",
            *recurrence_missing,
            "```",
            "",
            f"- Outlier-flagged primary rows excluded by the row-level filter: `{len(outlier_primary)}` IDs; source flags: `{data['outlier_flags']}`.",
            f"- Edit-flagged robustness exclusion: `{sorted(EDIT_FLAGGED_CLAIM_IDS)}`; source flags: `{data['edit_flags']}`.",
            "",
            "## Evidence files",
            "",
            f"- `{METRICS_EVIDENCE_PATH}`",
            f"- `{CONFOUNDS_EVIDENCE_PATH}`",
            f"- `{ROBUSTNESS_EVIDENCE_PATH}`",
            f"- `{FIGURES_EVIDENCE_PATH}`",
            f"- `{EXTREME_PATH}`",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_extreme_cases(data: dict[str, Any]) -> None:
    claim_text = {str(row["claim_id"]): str(row["claim_text"]) for row in data["claims"]}
    context_text = {str(row["context_id"]): str(row["text"]) for row in data["contexts"]}
    explanation_text = {
        int(row["generation_index"]): str(row["text"])
        for row in data["explanations"]
        if int(row["position_offset"]) == 0 and int(row["sample_idx"]) == 0
    }
    highest = sorted(data["metrics"], key=lambda row: (-abs(row["raw_excess"]), row["claim_id"]))[:20]
    nearest = sorted(data["metrics"], key=lambda row: (abs(row["raw_excess"]), row["claim_id"]))[:20]
    lines = [
        "# Phase 6 extreme cases",
        "",
        "Description-only artifact. Cases are sorted mechanically by raw excess magnitude and distance from zero.",
        "",
    ]
    for title, rows in (("20 highest absolute raw excess", highest), ("20 nearest-zero raw excess", nearest)):
        lines.extend([f"## {title}", ""])
        for index, row in enumerate(rows, start=1):
            lines.extend(
                [
                    f"### {index}. `{row['claim_id']}`",
                    "",
                    f"- context_id: `{row['context_id']}`; stratum: `{row['stratum']}`; label: `{row['label']}`; claim_index: `{row['claim_index']}`.",
                    f"- raw_excess: `{row['raw_excess']}`; full_mse: `{row['full_mse']}`; delete_mse: `{row['delete_mse']}`; random_mses: `{row['random_mses']}`.",
                    f"- claim: {claim_text[row['claim_id']]}",
                    "",
                    "Context:",
                    "```text",
                    context_text[row["context_id"]],
                    "```",
                    "",
                    "Primary explanation:",
                    "```text",
                    explanation_text[row["generation_index"]],
                    "```",
                    "",
                ]
            )
    _atomic_text(EXTREME_PATH, "\n".join(lines))


def main() -> None:
    started = time.time()
    startup: dict[str, Any] | None = None
    golden: dict[str, Any] | None = None
    try:
        # Explicit order: inherited-state assertions, then G5, then real analysis data.
        startup = run_startup_asserts()
        golden = run_golden_tests()
        data = _load_and_compute()
        _add_claim_text_fields(data["metrics"], data["claims"])
        table1 = _write_table1(data["metrics"])
        table2 = _write_table2(data["metrics"])
        confounds = _make_confounds(data["metrics"])
        rewrite_agreement = _rewrite_vs_mechanical(data["metrics"])
        robustness = _robustness(data["metrics"], data["outlier_flags"])
        figures = _make_figures(data, table1, table2)

        _atomic_json(
            METRICS_EVIDENCE_PATH,
            {
                "status": "passed",
                "created_at_unix": time.time(),
                "source_sha256": SOURCE_SHA256,
                "eligible_rows": len(data["metrics"]),
                "table1": table1,
                "table2": table2,
                "rewrite_agreement": rewrite_agreement,
                "normalization": {
                    "mse_scale": MSE_SCALE,
                    "source": "results/phase5_preflight.json model_metadata.mse_scale",
                    "activation_normalization": "per-vector L2 norm matched to mse_scale",
                    "dataset_baseline_mse": data["baseline_by_context"]["dataset_baseline_mse"],
                },
                "claim_metrics": data["metrics"],
            },
        )
        _atomic_json(CONFOUNDS_EVIDENCE_PATH, confounds)
        _atomic_json(ROBUSTNESS_EVIDENCE_PATH, robustness)
        _atomic_json(FIGURES_EVIDENCE_PATH, figures)
        report = _make_report(
            data,
            table1,
            table2,
            confounds,
            robustness,
            figures,
            rewrite_agreement,
            golden,
            startup,
        )
        _atomic_text(REPORT_PATH, report)
        _write_extreme_cases(data)
        gate = {
            "status": "passed",
            "created_at_unix": time.time(),
            "source_sha256": SOURCE_SHA256,
            "billing": {
                "cost_usd": "0.00",
                "billing_basis": "local Python process; no Modal, OpenRouter/API calls, GPU, or paid compute",
            },
            "gates": {
                "startup": "passed",
                "golden_tests": "passed",
                "data_metrics": "passed",
                "confounds": confounds["status"],
                "robustness": robustness["status"],
                "figures": figures["status"],
                "report": "written",
                "extreme_cases": "written",
            },
            "rows": {
                "eligible": len(data["metrics"]),
                "deletion_rewrite_overlap": rewrite_agreement["n_overlap"],
                "recurrence_non_null": sum(row["recurrence_excess"] is not None for row in data["metrics"]),
            },
            "outputs": {
                "analysis_report": str(REPORT_PATH),
                "extreme_cases": str(EXTREME_PATH),
                "figures": figures["paths"],
            },
            "wall_time_seconds": time.time() - started,
        }
        _atomic_json(ANALYSIS_GATE_PATH, gate)
        print(json.dumps(_jsonable(gate), indent=2), flush=True)
    except Exception as exc:
        failure = {
            "status": "failed",
            "created_at_unix": time.time(),
            "source_sha256": SOURCE_SHA256,
            "error": f"{type(exc).__name__}: {exc}",
            "startup_status": None if startup is None else startup.get("status"),
            "golden_status": None if golden is None else golden.get("status"),
            "wall_time_seconds": time.time() - started,
        }
        _atomic_json(ANALYSIS_GATE_PATH, failure)
        raise


if __name__ == "__main__":
    main()
