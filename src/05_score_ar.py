"""Phase 5 AR scoring for the NLA verifier.

The preflight, validation, and scoring jobs are separate Modal functions so
the paid scorer cannot start without fresh predecessor evidence.  The scorer
keeps 300-row checkpoints on the artifact Volume and can be rerun safely.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import modal


ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "nla-verifier-phase5-ar"
MODEL_REPO = "ceselder/qwen3.6-27b-nla-rl"
AR_FILES = [
    "ar_reconstructor/*",
    "av_base/chat_template.jinja",
    "av_base/tokenizer.json",
    "av_base/tokenizer_config.json",
    "data/example_activations.parquet",
    "nla_meta.yaml",
]
PREFLIGHT_FILES = [
    "av_base/chat_template.jinja",
    "av_base/tokenizer.json",
    "av_base/tokenizer_config.json",
    "data/example_activations.parquet",
    "nla_meta.yaml",
]

DATA_DIR = ROOT / "data"
RESULTS_DIR = ROOT / "results"
TEXTS_PATH = DATA_DIR / "texts_to_score.parquet"
CLAIMS_PATH = DATA_DIR / "claims_labeled.parquet"
EXPLANATIONS_PATH = DATA_DIR / "explanations.parquet"
CONTEXTS_PATH = DATA_DIR / "contexts.parquet"
ACTIVATIONS_DIR = DATA_DIR / "activations"
SMOKE_INPUTS_PATH = RESULTS_DIR / "smoke_inputs.json"
PHASE2_GATE_PATH = RESULTS_DIR / "phase2_merge_gate.json"
PHASE4_MANIFEST_PATH = RESULTS_DIR / "phase4_edit_manifest.json"
RIGHTSIZING_PATH = RESULTS_DIR / "container_rightsizing.json"
PREFLIGHT_RESULT_PATH = RESULTS_DIR / "phase5_preflight.json"
BATCH_VALIDATION_RESULT_PATH = RESULTS_DIR / "ar_batch_validation.json"
PRIMARY_GATE_PATH = RESULTS_DIR / "phase5_primary_gate.json"
SIBLING_GATE_PATH = RESULTS_DIR / "phase5_siblings_gate.json"
SCORE_RESULT_PATH = RESULTS_DIR / "phase5_score.json"

REMOTE_WORKSPACE = "/workspace"
REMOTE_ARTIFACT_ROOT = "/artifacts/phase5"
REMOTE_PREFLIGHT_PATH = f"{REMOTE_WORKSPACE}/results/phase5_preflight.json"
REMOTE_PREFLIGHT_ARTIFACT_PATH = f"{REMOTE_ARTIFACT_ROOT}/phase5_preflight.json"
REMOTE_BATCH_VALIDATION_PATH = (
    f"{REMOTE_WORKSPACE}/results/ar_batch_validation.json"
)
REMOTE_PRIMARY_GATE_PATH = f"{REMOTE_ARTIFACT_ROOT}/phase5_primary_gate.json"
REMOTE_SIBLING_GATE_PATH = f"{REMOTE_ARTIFACT_ROOT}/phase5_siblings_gate.json"
REMOTE_SCORE_RESULT_PATH = f"{REMOTE_ARTIFACT_ROOT}/phase5_score.json"
REMOTE_RESOURCE_DIR = f"{REMOTE_ARTIFACT_ROOT}/resource_metrics"
REMOTE_PRIMARY_DIR = f"{REMOTE_ARTIFACT_ROOT}/primary"
REMOTE_SIBLING_DIR = f"{REMOTE_ARTIFACT_ROOT}/siblings"
REMOTE_PRIMARY_FINAL = f"{REMOTE_PRIMARY_DIR}/scores.parquet"
REMOTE_SIBLING_FINAL = f"{REMOTE_SIBLING_DIR}/scores_siblings.parquet"
REMOTE_PRIMARY_CHECKPOINT_DIR = f"{REMOTE_PRIMARY_DIR}/checkpoints"
REMOTE_SIBLING_CHECKPOINT_DIR = f"{REMOTE_SIBLING_DIR}/checkpoints"
REMOTE_PRIMARY_EVIDENCE_DIR = f"{REMOTE_PRIMARY_DIR}/evidence"
REMOTE_SIBLING_EVIDENCE_DIR = f"{REMOTE_SIBLING_DIR}/evidence"

CHECKPOINT_ROWS = 1_000
BATCH_SIZE = 32
EXPECTED_TEXT_ROWS = 12_759
EXPECTED_CONTEXT_ROWS = 300
EXPECTED_ACTIVATION_ROWS = 3_000
ACTIVATION_WIDTH = 5_120
RECURRENCE_POSITION_CAP = 3
BILLING_BASIS = (
    "public per-cycle line-item report: Modal workspace_billing_report at "
    "hourly resolution; public SDK exposes no credit-adjusted summary"
)

SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
SOURCE_MTIME_UNIX = Path(__file__).stat().st_mtime


cache_volume = modal.Volume.from_name("nla-verifier-cache", create_if_missing=True)
artifact_volume = modal.Volume.from_name(
    "nla-verifier-artifacts", create_if_missing=True
)


image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git")
    .env(
        {
            "HF_HOME": "/cache/huggingface",
            "HF_HUB_CACHE": "/cache/huggingface/hub",
            "TRANSFORMERS_CACHE": "/cache/huggingface/transformers",
            "TOKENIZERS_PARALLELISM": "false",
        }
    )
    .uv_pip_install(
        "torch",
        "transformers==5.5.4",
        "accelerate",
        "peft",
        "pyarrow",
        "pyyaml",
        "safetensors",
        "numpy",
        "huggingface_hub",
        "psutil",
    )
    .uv_pip_install("flash-linear-attention")
    .uv_pip_install(
        "git+https://github.com/asherps/EasyNLA.git@4d728477960c18cdfa36dc04ec738d7f55af9f0b",
        extra_options="--no-deps",
    )
)


def _add_local_file(local_path: Path, remote_path: str) -> None:
    global image
    if local_path.exists():
        image = image.add_local_file(str(local_path), remote_path)


_add_local_file(TEXTS_PATH, f"{REMOTE_WORKSPACE}/data/texts_to_score.parquet")
_add_local_file(CLAIMS_PATH, f"{REMOTE_WORKSPACE}/data/claims_labeled.parquet")
_add_local_file(
    EXPLANATIONS_PATH, f"{REMOTE_WORKSPACE}/data/explanations.parquet"
)
_add_local_file(CONTEXTS_PATH, f"{REMOTE_WORKSPACE}/data/contexts.parquet")
_add_local_file(SMOKE_INPUTS_PATH, f"{REMOTE_WORKSPACE}/results/smoke_inputs.json")
_add_local_file(PHASE2_GATE_PATH, f"{REMOTE_WORKSPACE}/results/phase2_merge_gate.json")
_add_local_file(
    PHASE4_MANIFEST_PATH,
    f"{REMOTE_WORKSPACE}/results/phase4_edit_manifest.json",
)
_add_local_file(RIGHTSIZING_PATH, f"{REMOTE_WORKSPACE}/results/container_rightsizing.json")
_add_local_file(PREFLIGHT_RESULT_PATH, REMOTE_PREFLIGHT_PATH)
_add_local_file(BATCH_VALIDATION_RESULT_PATH, REMOTE_BATCH_VALIDATION_PATH)
for activation_path in sorted(ACTIVATIONS_DIR.glob("*.parquet")):
    _add_local_file(
        activation_path,
        f"{REMOTE_WORKSPACE}/data/activations/{activation_path.name}",
    )


GPU_FUNCTION_KWARGS = {
    "image": image,
    "gpu": "A100-80GB",
    "cpu": 5,
    "memory": 70_000,
    "timeout": 24 * 60 * 60,
    "max_containers": 1,
    "volumes": {"/cache": cache_volume, "/artifacts": artifact_volume},
    "secrets": [modal.Secret.from_name("amnesiac-hf-auth")],
}

CPU_FUNCTION_KWARGS = {
    "image": image,
    "cpu": 2,
    "memory": 8_000,
    "timeout": 20 * 60,
    "volumes": {"/cache": cache_volume, "/artifacts": artifact_volume},
    "secrets": [modal.Secret.from_name("amnesiac-hf-auth")],
}


app = modal.App(APP_NAME)


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(str(path) + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    os.replace(temporary, path)


def _atomic_parquet(path: Path, rows: list[dict[str, Any]], schema: Any) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(str(path) + ".tmp")
    table = pa.Table.from_pylist(rows, schema=schema)
    pq.write_table(table, temporary)
    os.replace(temporary, path)


class _ResourceSampler:
    """Best-effort psutil telemetry; instrumentation must not block scoring."""

    def __init__(self, label: str):
        self.label = label
        self.started_at_unix = time.time()
        self.samples: list[dict[str, Any]] = []
        self.errors: list[str] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        try:
            import psutil

            process = psutil.Process()
            process.cpu_percent(None)

            def sample_loop() -> None:
                while not self._stop.wait(5.0):
                    try:
                        self.samples.append(
                            {
                                "at_unix": time.time(),
                                "rss_bytes": int(process.memory_info().rss),
                                "cpu_percent": float(process.cpu_percent(None)),
                            }
                        )
                    except Exception as exc:  # pragma: no cover - best effort
                        self.errors.append(f"{type(exc).__name__}: {exc}")

            self._thread = threading.Thread(
                target=sample_loop, name=f"phase5-{self.label}-psutil", daemon=True
            )
            self._thread.start()
        except Exception as exc:  # pragma: no cover - best effort
            self.errors.append(f"start {type(exc).__name__}: {exc}")

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=7.0)
        try:
            import psutil

            process = psutil.Process()
            self.samples.append(
                {
                    "at_unix": time.time(),
                    "rss_bytes": int(process.memory_info().rss),
                    "cpu_percent": float(process.cpu_percent(None)),
                }
            )
        except Exception as exc:  # pragma: no cover - best effort
            self.errors.append(f"final {type(exc).__name__}: {exc}")

        peak_rss = max((int(s["rss_bytes"]) for s in self.samples), default=None)
        peak_cpu = max(
            (float(s["cpu_percent"]) for s in self.samples), default=None
        )
        result = {
            "label": self.label,
            "started_at_unix": self.started_at_unix,
            "finished_at_unix": time.time(),
            "sample_interval_seconds": 5,
            "samples": self.samples,
            "peak_rss_bytes": peak_rss,
            "peak_cpu_percent": peak_cpu,
            "peak_cpu_cores": None if peak_cpu is None else peak_cpu / 100.0,
            "instrumentation_errors": self.errors,
            "instrumentation_status": "passed" if not self.errors else "degraded",
        }
        try:
            path = Path(REMOTE_RESOURCE_DIR) / f"{self.label}_{int(time.time())}.json"
            _atomic_json(path, result)
            artifact_volume.commit()
            result["artifact_path"] = str(path)
        except Exception as exc:  # pragma: no cover - best effort
            result["instrumentation_errors"].append(
                f"write {type(exc).__name__}: {exc}"
            )
            result["instrumentation_status"] = "degraded"
        return result


def _load_tokenizer(repo_dir: str):
    from transformers import AutoTokenizer, PreTrainedTokenizerFast

    tokenizer_dir = Path(repo_dir) / "av_base"
    try:
        return AutoTokenizer.from_pretrained(tokenizer_dir)
    except ValueError as exc:
        if "TokenizersBackend" not in str(exc):
            raise
        tokenizer = PreTrainedTokenizerFast.from_pretrained(tokenizer_dir)
        template_path = tokenizer_dir / "chat_template.jinja"
        if not template_path.exists():
            raise RuntimeError(
                f"fallback tokenizer needs the shipped chat template at {template_path}"
            )
        tokenizer.chat_template = template_path.read_text(encoding="utf-8")
        return tokenizer


def _write_remote_json(path: str, value: Any) -> None:
    _atomic_json(Path(path), value)
    artifact_volume.commit()


def _read_remote_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _assert_remote_predecessors() -> dict[str, Any]:
    import pyarrow.parquet as pq

    required = {
        "texts_to_score": f"{REMOTE_WORKSPACE}/data/texts_to_score.parquet",
        "claims_labeled": f"{REMOTE_WORKSPACE}/data/claims_labeled.parquet",
        "explanations": f"{REMOTE_WORKSPACE}/data/explanations.parquet",
        "contexts": f"{REMOTE_WORKSPACE}/data/contexts.parquet",
        "phase2_merge_gate": f"{REMOTE_WORKSPACE}/results/phase2_merge_gate.json",
        "phase4_edit_manifest": (
            f"{REMOTE_WORKSPACE}/results/phase4_edit_manifest.json"
        ),
    }
    missing = [name for name, path in required.items() if not Path(path).exists()]
    if missing:
        raise RuntimeError(f"G1 predecessor evidence missing: {missing}")
    phase2 = _read_remote_json(required["phase2_merge_gate"])
    if phase2.get("status") != "passed":
        raise RuntimeError("G1 phase2_merge_gate.json is not passed")
    phase4 = _read_remote_json(required["phase4_edit_manifest"])
    if int(phase4.get("eligible_claims", -1)) != 2127:
        raise RuntimeError(
            "G1 phase4_edit_manifest.json has unexpected eligible_claims: "
            f"{phase4.get('eligible_claims')}"
        )
    texts = pq.read_table(required["texts_to_score"])
    claims = pq.read_table(required["claims_labeled"])
    explanations = pq.read_table(required["explanations"])
    contexts = pq.read_table(required["contexts"])
    if texts.num_rows != EXPECTED_TEXT_ROWS:
        raise RuntimeError(
            f"expected {EXPECTED_TEXT_ROWS} texts, found {texts.num_rows}"
        )
    if claims.num_rows != 2971:
        raise RuntimeError(f"expected 2971 labeled claims, found {claims.num_rows}")
    if explanations.num_rows != 3900:
        raise RuntimeError(
            f"expected 3900 explanations, found {explanations.num_rows}"
        )
    if contexts.num_rows != EXPECTED_CONTEXT_ROWS:
        raise RuntimeError(
            f"expected {EXPECTED_CONTEXT_ROWS} contexts, found {contexts.num_rows}"
        )
    return {
        "phase2_merge_gate": "passed",
        "phase4_edit_manifest": "present",
        "texts_to_score_rows": texts.num_rows,
        "claims_labeled_rows": claims.num_rows,
        "explanations_rows": explanations.num_rows,
        "contexts_rows": contexts.num_rows,
    }


def _assert_paid_predecessors() -> dict[str, Any]:
    if not Path(REMOTE_PREFLIGHT_PATH).exists():
        raise RuntimeError(f"G1/G2 predecessor missing: {REMOTE_PREFLIGHT_PATH}")
    preflight = _read_remote_json(REMOTE_PREFLIGHT_PATH)
    if preflight.get("status") != "passed":
        raise RuntimeError(f"preflight evidence is not passed: {REMOTE_PREFLIGHT_PATH}")
    if preflight.get("source_sha256") != SOURCE_SHA256:
        raise RuntimeError(
            "preflight evidence was produced by a different source revision"
        )
    validation_status = "missing_and_will_run_in_this_app"
    if Path(REMOTE_BATCH_VALIDATION_PATH).exists():
        validation = _read_remote_json(REMOTE_BATCH_VALIDATION_PATH)
        if validation.get("status") == "passed" and validation.get("source_sha256") == SOURCE_SHA256:
            validation_status = "passed_existing"
        else:
            validation_status = "present_but_not_current_and_will_run_in_this_app"
    return {
        "preflight": REMOTE_PREFLIGHT_PATH,
        "batch_validation": validation_status,
        "source_sha256": SOURCE_SHA256,
    }


def _load_activation_map() -> dict[tuple[str, int], list[float]]:
    import pyarrow.parquet as pq

    activation_paths = sorted(Path(f"{REMOTE_WORKSPACE}/data/activations").glob("*.parquet"))
    if len(activation_paths) != 30:
        raise RuntimeError(
            f"expected 30 activation shards, found {len(activation_paths)}"
        )
    activation_map: dict[tuple[str, int], list[float]] = {}
    for path in activation_paths:
        for row in pq.read_table(path).to_pylist():
            context_id = str(row["context_id"])
            offset = int(row["position_offset"])
            vector = row["activation_vector"]
            if len(vector) != ACTIVATION_WIDTH:
                raise RuntimeError(
                    f"activation width mismatch at {context_id}/{offset}: "
                    f"{len(vector)}"
                )
            key = (context_id, offset)
            if key in activation_map:
                raise RuntimeError(f"duplicate activation key {key}")
            activation_map[key] = vector
    if len(activation_map) != EXPECTED_ACTIVATION_ROWS:
        raise RuntimeError(
            f"expected {EXPECTED_ACTIVATION_ROWS} activation rows, "
            f"found {len(activation_map)}"
        )
    contexts = {context_id for context_id, _ in activation_map}
    if len(contexts) != EXPECTED_CONTEXT_ROWS:
        raise RuntimeError(
            f"expected {EXPECTED_CONTEXT_ROWS} activation contexts, found {len(contexts)}"
        )
    for context_id in contexts:
        offsets = {offset for ctx, offset in activation_map if ctx == context_id}
        if offsets != set(range(10)):
            raise RuntimeError(f"activation offsets for {context_id} are {offsets}")
    return activation_map


def _recurrence_inventory() -> dict[str, Any]:
    import pyarrow.parquet as pq

    claims = pq.read_table(
        f"{REMOTE_WORKSPACE}/data/claims_labeled.parquet"
    ).to_pylist()
    texts = pq.read_table(
        f"{REMOTE_WORKSPACE}/data/texts_to_score.parquet"
    ).to_pylist()
    recurrence_by_claim = {
        str(row["claim_id"]): int(row.get("recurrence_positions") or 0)
        for row in claims
    }
    eligible_claim_ids = {
        claim_id
        for claim_id, count in recurrence_by_claim.items()
        if count >= 2
    }
    delete_rows = [row for row in texts if row["kind"] == "DELETE_MECH"]
    selected = [
        row
        for row in delete_rows
        if str(row["claim_id"]) in eligible_claim_ids
    ]
    missing_claim_ids = sorted(eligible_claim_ids - {str(row["claim_id"]) for row in selected})
    expanded_rows = sum(
        min(RECURRENCE_POSITION_CAP, recurrence_by_claim[str(row["claim_id"])])
        for row in selected
    )
    if len({str(row["text_id"]) for row in selected}) != len(selected):
        raise RuntimeError("duplicate eligible DELETE_MECH text_id")
    return {
        "claims_total": len(claims),
        "claims_recurrence_ge_2": len(eligible_claim_ids),
        "delete_mech_rows_total": len(delete_rows),
        "delete_mech_rows_selected": len(selected),
        "claims_without_delete_mech_in_input": len(missing_claim_ids),
        "missing_claim_ids_sample": missing_claim_ids[:20],
        "expanded_sibling_score_rows": expanded_rows,
        "position_selection": "offsets 1 through min(recurrence_positions, 3), nearest first",
        "selected_delete_rows": selected,
        "recurrence_by_claim": recurrence_by_claim,
    }


@app.function(**CPU_FUNCTION_KWARGS)
def preflight() -> dict[str, Any]:
    """G2 preflight with no GPU and no AR model-weight download."""

    import importlib
    import importlib.metadata
    import importlib.util

    started = time.time()
    result: dict[str, Any] = {
        "status": "failed",
        "created_at_unix": started,
        "source_sha256": SOURCE_SHA256,
        "source_mtime_unix": SOURCE_MTIME_UNIX,
        "billing_basis": BILLING_BASIS,
    }
    try:
        import pyarrow.parquet as pq
        import torch
        from huggingface_hub import snapshot_download

        from nla.config import load_nla_config

        predecessor_assertions = _assert_remote_predecessors()
        volume_paths = [
            Path(REMOTE_ARTIFACT_ROOT),
            Path(REMOTE_PRIMARY_CHECKPOINT_DIR),
            Path(REMOTE_SIBLING_CHECKPOINT_DIR),
            Path(REMOTE_RESOURCE_DIR),
        ]
        for path in volume_paths:
            path.mkdir(parents=True, exist_ok=True)
        artifact_volume.commit()

        fla_available = importlib.util.find_spec("fla") is not None
        if not fla_available:
            raise RuntimeError("flash-linear-attention installed but fla is unavailable")
        importlib.import_module("fla")
        imported = {}
        for module_name in (
            "torch",
            "transformers",
            "pyarrow",
            "psutil",
            "nla.config",
            "nla.models",
            "nla.schema",
            "nla.utils",
        ):
            imported[module_name] = importlib.import_module(module_name).__name__

        texts_table = pq.read_table(
            f"{REMOTE_WORKSPACE}/data/texts_to_score.parquet"
        )
        if texts_table.column_names != [
            "text_id",
            "kind",
            "claim_id",
            "context_id",
            "text",
        ]:
            raise RuntimeError(f"unexpected texts schema: {texts_table.column_names}")
        texts = texts_table.to_pylist()
        if any(not isinstance(row["text"], str) for row in texts):
            raise RuntimeError("texts_to_score contains a non-string text")
        if len({str(row["text_id"]) for row in texts}) != len(texts):
            raise RuntimeError("texts_to_score text_id values are not unique")

        explanations = pq.read_table(
            f"{REMOTE_WORKSPACE}/data/explanations.parquet"
        ).to_pylist()
        primary = {
            str(row["context_id"]): row
            for row in explanations
            if int(row["position_offset"]) == 0 and int(row["sample_idx"]) == 0
        }
        genuine = {
            str(row["context_id"]): row["text"]
            for row in texts
            if row["kind"] == "GENUINE"
        }
        if len(primary) != EXPECTED_CONTEXT_ROWS or len(genuine) != EXPECTED_CONTEXT_ROWS:
            raise RuntimeError(
                f"primary/genuine counts are {len(primary)}/{len(genuine)}, "
                f"expected {EXPECTED_CONTEXT_ROWS}/{EXPECTED_CONTEXT_ROWS}"
            )
        if set(primary) != set(genuine):
            raise RuntimeError("GENUINE context IDs do not match primary explanations")
        genuine_mismatches = [
            context_id
            for context_id in primary
            if primary[context_id]["text"] != genuine[context_id]
        ]
        if genuine_mismatches:
            raise RuntimeError(
                f"GENUINE rows do not match primary explanations: {genuine_mismatches[:5]}"
            )

        activation_map = _load_activation_map()
        if any((context_id, 0) not in activation_map for context_id in primary):
            raise RuntimeError("a primary explanation lacks a primary activation")

        recurrence = _recurrence_inventory()
        claims_table = pq.read_table(
            f"{REMOTE_WORKSPACE}/data/claims_labeled.parquet"
        )

        repo_dir = snapshot_download(
            MODEL_REPO,
            allow_patterns=PREFLIGHT_FILES,
            cache_dir="/cache/huggingface/hub",
        )
        tokenizer = _load_tokenizer(repo_dir)
        cfg = load_nla_config(repo_dir, tokenizer)
        fixture_table = pq.read_table(
            Path(repo_dir) / "data/example_activations.parquet"
        )
        fixture_activation_layer = int(
            fixture_table.column("activation_layer")[0].as_py()
        )
        dummy_texts = ["phase5 preflight", "phase5 second row"]
        encoded = [
            tokenizer.encode(
                cfg.critic_prompt_template.format(explanation=text),
                add_special_tokens=False,
            )
            for text in dummy_texts
        ]
        if not encoded or any(not row for row in encoded):
            raise RuntimeError("dummy critic tokenization returned an empty row")
        max_len = max(map(len, encoded))
        dummy_ids = torch.full(
            (len(encoded), max_len),
            tokenizer.eos_token_id,
            dtype=torch.long,
        )
        dummy_mask = torch.zeros_like(dummy_ids)
        for index, ids in enumerate(encoded):
            dummy_ids[index, : len(ids)] = torch.tensor(ids, dtype=torch.long)
            dummy_mask[index, : len(ids)] = 1
        if tuple(dummy_ids.shape) != tuple(dummy_mask.shape):
            raise RuntimeError("dummy input_ids and attention_mask shapes differ")
        dummy_gold = torch.zeros((len(encoded), ACTIVATION_WIDTH), dtype=torch.float32)
        dummy_mse = ((dummy_gold - dummy_gold) ** 2).mean(dim=1)
        if dummy_mse.shape != (len(encoded),) or not torch.isfinite(dummy_mse).all():
            raise RuntimeError("dummy fp32 MSE dry-run failed")

        try:
            fla_core_version = importlib.metadata.version("fla-core")
        except importlib.metadata.PackageNotFoundError:
            fla_core_version = None

        result.update(
            {
                "status": "passed",
                "duration_seconds": time.time() - started,
                "predecessor_assertions": predecessor_assertions,
                "volume_paths": [str(path) for path in volume_paths],
                "imports": imported,
                "flash_linear_attention": {
                    "module_imported": True,
                    "fla_available": fla_available,
                    "fla_core_version": fla_core_version,
                },
                "input_rows": {
                    "texts_to_score": len(texts),
                    "claims_labeled": claims_table.num_rows,
                    "explanations": len(explanations),
                    "contexts": pq.read_table(
                        f"{REMOTE_WORKSPACE}/data/contexts.parquet"
                    ).num_rows,
                    "activations": len(activation_map),
                },
                "primary_match": {
                    "primary_rows": len(primary),
                    "genuine_rows": len(genuine),
                    "exact_text_matches": len(primary),
                },
                "recurrence_inventory": {
                    key: value
                    for key, value in recurrence.items()
                    if key not in {"selected_delete_rows", "recurrence_by_claim"}
                },
                "dummy_data_dry_run": {
                    "rows": len(encoded),
                    "max_tokens": max_len,
                    "activation_width": ACTIVATION_WIDTH,
                    "mse_dtype": "float32",
                    "status": "passed",
                },
                "model_metadata": {
                    "repo": MODEL_REPO,
                    "d_model": int(cfg.d_model),
                    "activation_layer": fixture_activation_layer,
                    "mse_scale": float(cfg.mse_scale),
                    "critic_template_present": cfg.critic_prompt_template is not None,
                    "transformers": importlib.import_module("transformers").__version__,
                },
                "anomalies": [
                    "204 recurrence-eligible claims have no DELETE_MECH row in the supplied texts_to_score input; no rows were fabricated"
                ]
                if recurrence["claims_without_delete_mech_in_input"]
                else [],
            }
        )
    except Exception as exc:
        result.update(
            {
                "error": f"{type(exc).__name__}: {exc}",
                "duration_seconds": time.time() - started,
            }
        )
    _write_remote_json(REMOTE_PREFLIGHT_ARTIFACT_PATH, result)
    if result["status"] != "passed":
        raise RuntimeError(json.dumps(result))
    return result


def _load_model_and_config():
    import torch
    from huggingface_hub import snapshot_download

    from nla.config import load_nla_config
    from nla.models import NLACriticModel

    repo_dir = snapshot_download(
        MODEL_REPO,
        allow_patterns=AR_FILES,
        cache_dir="/cache/huggingface/hub",
    )
    cache_volume.commit()
    tokenizer = _load_tokenizer(repo_dir)
    cfg = load_nla_config(repo_dir, tokenizer)
    if cfg.critic_prompt_template is None:
        raise RuntimeError("NLA metadata has no critic prompt template")
    critic = NLACriticModel.from_pretrained(
        Path(repo_dir) / "ar_reconstructor",
        torch_dtype=torch.bfloat16,
        device_map={"": "cuda:0"},
        attn_implementation="sdpa",
    ).eval()
    return critic, tokenizer, cfg


def _score_rows(
    critic: Any,
    tokenizer: Any,
    cfg: Any,
    rows: list[dict[str, Any]],
    *,
    batch_size: int,
    key_fn=lambda row: row["text_id"],
) -> list[float]:
    import torch
    import torch.nn.functional as F

    from nla.schema import normalize_activation
    from nla.utils import critic_predict

    if not rows:
        return []
    prepared = []
    for row in rows:
        token_ids = tokenizer.encode(
            cfg.critic_prompt_template.format(explanation=row["text"]),
            add_special_tokens=False,
        )
        if not token_ids:
            raise RuntimeError("critic tokenization produced an empty row")
        prepared.append((row, token_ids))
    keys = [key_fn(row) for row in rows]
    if len(set(keys)) != len(keys):
        raise RuntimeError("score input keys are not unique")
    sorted_prepared = sorted(
        prepared,
        key=lambda item: (len(item[1]), key_fn(item[0])),
    )
    device = torch.device("cuda:0")
    score_by_key: dict[Any, float] = {}
    for start in range(0, len(sorted_prepared), batch_size):
        batch_with_tokens = sorted_prepared[start : start + batch_size]
        batch = [row for row, _ in batch_with_tokens]
        token_rows = [token_ids for _, token_ids in batch_with_tokens]
        if any(not ids for ids in token_rows):
            raise RuntimeError("critic tokenization produced an empty row")
        max_len = max(len(ids) for ids in token_rows)
        pad_id = tokenizer.eos_token_id
        input_ids = torch.full(
            (len(token_rows), max_len), pad_id, dtype=torch.long, device=device
        )
        attention_mask = torch.zeros_like(input_ids)
        for index, ids in enumerate(token_rows):
            input_ids[index, : len(ids)] = torch.tensor(ids, device=device)
            attention_mask[index, : len(ids)] = 1
        gold = torch.tensor(
            [row["activation_vector"] for row in batch],
            dtype=torch.float32,
            device=device,
        )
        if gold.shape != (len(batch), ACTIVATION_WIDTH):
            raise RuntimeError(f"gold activation shape is {tuple(gold.shape)}")
        with torch.inference_mode():
            prediction = critic_predict(
                critic, input_ids, attention_mask, cfg.mse_scale
            )
            pred_norm = normalize_activation(prediction, cfg.mse_scale).float()
            gold_norm = normalize_activation(gold, cfg.mse_scale).float()
            per_row_mse = F.mse_loss(
                pred_norm, gold_norm, reduction="none"
            ).mean(dim=1)
        if per_row_mse.shape != (len(batch),) or not torch.isfinite(per_row_mse).all():
            raise RuntimeError("non-finite or malformed per-row MSE")
        for row, value in zip(batch, per_row_mse.detach().cpu().tolist()):
            score_by_key[key_fn(row)] = float(value)
    scores = [score_by_key[key] for key in keys]
    if len(scores) != len(rows):
        raise RuntimeError(f"scored {len(scores)} rows for {len(rows)} inputs")
    return scores


@app.function(**GPU_FUNCTION_KWARGS)
def validate_batch() -> dict[str, Any]:
    """Run the required batch=32 versus batch=1 equivalence gate."""

    import json as json_module

    sampler = _ResourceSampler("batch_validation")
    started = time.time()
    result: dict[str, Any] = {
        "status": "failed",
        "created_at_unix": started,
        "source_sha256": SOURCE_SHA256,
        "billing_basis": BILLING_BASIS,
        "batch_sizes": [32, 1],
    }
    sampler.start()
    try:
        _assert_remote_predecessors()
        if not Path(REMOTE_PREFLIGHT_PATH).exists():
            raise RuntimeError("G2 preflight evidence is not mounted")
        preflight_evidence = _read_remote_json(REMOTE_PREFLIGHT_PATH)
        if preflight_evidence.get("status") != "passed":
            raise RuntimeError("G2 preflight evidence is not passed")
        smoke = json_module.loads(
            Path(f"{REMOTE_WORKSPACE}/results/smoke_inputs.json").read_text(
                encoding="utf-8"
            )
        )
        rows = []
        for row in smoke["rows"]:
            rows.append(
                {
                    "text_id": f"smoke-{int(row['fixture_index'])}",
                    "text": row["explanation"],
                    "activation_vector": row["activation_vector"],
                }
            )
        if len(rows) != 8:
            raise RuntimeError(f"expected 8 smoke explanations, found {len(rows)}")
        critic, tokenizer, cfg = _load_model_and_config()
        batch_scores = _score_rows(
            critic, tokenizer, cfg, rows, batch_size=32
        )
        unbatched_scores: list[float] = []
        for row in rows:
            unbatched_scores.extend(
                _score_rows(critic, tokenizer, cfg, [row], batch_size=1)
            )
        comparisons = []
        for row, batch_score, unbatched_score in zip(
            rows, batch_scores, unbatched_scores
        ):
            denominator = max(abs(unbatched_score), 1e-12)
            relative_difference = abs(batch_score - unbatched_score) / denominator
            comparisons.append(
                {
                    "text_id": row["text_id"],
                    "fixture_index": int(row["text_id"].split("-")[-1]),
                    "batch_32_mse": batch_score,
                    "batch_1_mse": unbatched_score,
                    "relative_difference": relative_difference,
                    "pass": relative_difference < 0.01,
                }
            )
        result.update(
            {
                "status": "passed"
                if all(row["pass"] for row in comparisons)
                else "failed",
                "duration_seconds": time.time() - started,
                "n_rows": len(rows),
                "relative_difference_threshold": 0.01,
                "per_row": comparisons,
                "all_rows_pass": all(row["pass"] for row in comparisons),
                "model_repo": MODEL_REPO,
                "mse_dtype": "fp32",
            }
        )
    except Exception as exc:
        result.update(
            {
                "error": f"{type(exc).__name__}: {exc}",
                "duration_seconds": time.time() - started,
            }
        )
    result["resource_metrics"] = sampler.stop()
    _write_remote_json(
        f"{REMOTE_ARTIFACT_ROOT}/ar_batch_validation.json", result
    )
    if result["status"] != "passed":
        raise RuntimeError(json.dumps(result))
    return result


def _load_primary_scoring_rows(activation_map: dict[tuple[str, int], list[float]]):
    import pyarrow.parquet as pq

    rows = pq.read_table(
        f"{REMOTE_WORKSPACE}/data/texts_to_score.parquet"
    ).to_pylist()
    seen: set[str] = set()
    scoring_rows = []
    for row in rows:
        text_id = str(row["text_id"])
        if text_id in seen:
            raise RuntimeError(f"duplicate text_id {text_id}")
        seen.add(text_id)
        context_id = str(row["context_id"])
        key = (context_id, 0)
        if key not in activation_map:
            raise RuntimeError(f"no primary activation for context {context_id}")
        scoring_rows.append(
            {
                "text_id": text_id,
                "context_id": context_id,
                "text": row["text"],
                "activation_vector": activation_map[key],
            }
        )
    if len(scoring_rows) != EXPECTED_TEXT_ROWS:
        raise RuntimeError(
            f"expected {EXPECTED_TEXT_ROWS} primary scoring rows, found {len(scoring_rows)}"
        )
    scoring_rows.sort(key=lambda row: row["text_id"])
    return scoring_rows


def _load_sibling_scoring_rows(
    activation_map: dict[tuple[str, int], list[float]],
):
    import pyarrow.parquet as pq

    recurrence = _recurrence_inventory()
    recurrence_by_claim = recurrence["recurrence_by_claim"]
    selected = recurrence["selected_delete_rows"]
    rows = []
    for source_row in selected:
        text_id = str(source_row["text_id"])
        context_id = str(source_row["context_id"])
        count = recurrence_by_claim[str(source_row["claim_id"])]
        for offset in range(1, min(RECURRENCE_POSITION_CAP, count) + 1):
            key = (context_id, offset)
            if key not in activation_map:
                raise RuntimeError(
                    f"no sibling activation for {context_id} offset {offset}"
                )
            rows.append(
                {
                    "text_id": text_id,
                    "context_id": context_id,
                    "position_offset": offset,
                    "text": source_row["text"],
                    "activation_vector": activation_map[key],
                }
            )
    expected = int(recurrence["expanded_sibling_score_rows"])
    if len(rows) != expected:
        raise RuntimeError(f"expected {expected} sibling rows, found {len(rows)}")
    if len({(row["text_id"], row["position_offset"]) for row in rows}) != len(rows):
        raise RuntimeError("duplicate sibling score key")
    rows.sort(key=lambda row: (row["text_id"], row["position_offset"]))
    return rows, recurrence


def _read_checkpoint(path: Path, expected_keys: set[Any], key_fn) -> list[dict[str, Any]]:
    import pyarrow.parquet as pq

    rows = pq.read_table(path).to_pylist()
    actual_keys = {key_fn(row) for row in rows}
    if actual_keys != expected_keys:
        raise RuntimeError(
            f"checkpoint {path} keys differ: expected {len(expected_keys)}, "
            f"found {len(actual_keys)}"
        )
    if any(not isinstance(row.get("mse"), (int, float)) for row in rows):
        raise RuntimeError(f"checkpoint {path} has a non-numeric MSE")
    return rows


def _billing_reported_total(snapshot: dict[str, Any]):
    from decimal import Decimal

    return Decimal(str(snapshot["summary"]["reported_cost"]))


def _checkpoint_rows(
    *,
    rows: list[dict[str, Any]],
    scores: list[float],
    checkpoint_dir: str,
    evidence_dir: str,
    label: str,
    key_fn,
    output_schema: Any,
    billing_start_total=None,
) -> dict[str, Any]:
    if len(rows) != len(scores):
        raise RuntimeError(f"{label} rows/scores length mismatch")
    checkpoint_dir_path = Path(checkpoint_dir)
    evidence_dir_path = Path(evidence_dir)
    checkpoint_dir_path.mkdir(parents=True, exist_ok=True)
    evidence_dir_path.mkdir(parents=True, exist_ok=True)
    chunks = [
        (start, rows[start : start + CHECKPOINT_ROWS], scores[start : start + CHECKPOINT_ROWS])
        for start in range(0, len(rows), CHECKPOINT_ROWS)
    ]
    completed = 0
    skipped = 0
    manifests = []
    for part_index, (start, chunk, chunk_scores) in enumerate(chunks):
        checkpoint_path = checkpoint_dir_path / f"part_{part_index:04d}.parquet"
        expected_keys = {key_fn(row) for row in chunk}
        if checkpoint_path.exists():
            checkpoint_rows = _read_checkpoint(
                checkpoint_path, expected_keys, key_fn
            )
            if any(not (float(row["mse"]) == float(row["mse"])) for row in checkpoint_rows):
                raise RuntimeError(f"checkpoint {checkpoint_path} has NaN MSE")
            skipped += 1
            checkpoint_count = len(checkpoint_rows)
        else:
            output_rows = []
            for row, score in zip(chunk, chunk_scores):
                output = {
                    "text_id": str(row["text_id"]),
                    "mse": float(score),
                }
                if "position_offset" in row:
                    output["position_offset"] = int(row["position_offset"])
                output_rows.append(output)
            _atomic_parquet(checkpoint_path, output_rows, output_schema)
            artifact_volume.commit()
            checkpoint_count = len(output_rows)
        checkpoint_billing = None
        checkpoint_error = None
        if billing_start_total is not None:
            try:
                checkpoint_snapshot = _workspace_billing_snapshot()
                checkpoint_total = _billing_reported_total(checkpoint_snapshot)
                checkpoint_delta = checkpoint_total - billing_start_total
                checkpoint_billing = {
                    "status": "passed",
                    "workspace_reported_total": str(checkpoint_total),
                    "all_in_delta_since_run_start": str(checkpoint_delta),
                    "snapshot": checkpoint_snapshot,
                    "billing_basis": BILLING_BASIS,
                }
                if checkpoint_delta > 30:
                    checkpoint_billing["status"] = "halted_above_30"
                    checkpoint_error = RuntimeError(
                        "G6 workspace all-in delta exceeded $30 at "
                        f"{label} checkpoint {part_index}: {checkpoint_delta}"
                    )
            except Exception as exc:
                if checkpoint_billing is None:
                    checkpoint_billing = {
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {exc}",
                        "billing_basis": BILLING_BASIS,
                    }
                checkpoint_error = exc
        evidence = {
            "status": (
                "passed"
                if checkpoint_billing is None
                else checkpoint_billing.get("status", "failed")
            ),
            "label": label,
            "part_index": part_index,
            "start_row": start,
            "rows": checkpoint_count,
            "checkpoint_path": str(checkpoint_path),
            "atomic_write": "tmp_then_rename",
            "idempotent": True,
            "billing_basis": BILLING_BASIS,
            "billing_checkpoint": checkpoint_billing,
            "created_at_unix": time.time(),
        }
        _atomic_json(
            evidence_dir_path / f"part_{part_index:04d}.json", evidence
        )
        artifact_volume.commit()
        if checkpoint_error is not None:
            raise checkpoint_error
        manifests.append(evidence)
        completed += checkpoint_count
    manifest = {
        "status": "passed",
        "label": label,
        "checkpoint_rows": CHECKPOINT_ROWS,
        "parts": manifests,
        "rows_total": completed,
        "skipped_existing_parts": skipped,
        "billing_basis": BILLING_BASIS,
        "created_at_unix": time.time(),
    }
    _atomic_json(checkpoint_dir_path.parent / "checkpoint_manifest.json", manifest)
    artifact_volume.commit()
    return manifest


def _assemble_final(
    *,
    final_path: str,
    checkpoint_dir: str,
    expected_keys: set[Any],
    key_fn,
    schema: Any,
) -> dict[str, Any]:
    import pyarrow.parquet as pq

    path = Path(final_path)
    if path.exists():
        rows = _read_checkpoint(path, expected_keys, key_fn)
        return {"status": "passed", "rows": len(rows), "skipped_existing": True}
    checkpoint_paths = sorted(Path(checkpoint_dir).glob("part_*.parquet"))
    if not checkpoint_paths:
        raise RuntimeError(f"no checkpoints found under {checkpoint_dir}")
    rows = []
    for checkpoint_path in checkpoint_paths:
        rows.extend(pq.read_table(checkpoint_path).to_pylist())
    if {key_fn(row) for row in rows} != expected_keys:
        raise RuntimeError("assembled checkpoint keys do not match expected keys")
    _atomic_parquet(path, rows, schema)
    artifact_volume.commit()
    return {"status": "passed", "rows": len(rows), "skipped_existing": False}


def _load_smoke_rows() -> list[dict[str, Any]]:
    smoke = json.loads(
        Path(f"{REMOTE_WORKSPACE}/results/smoke_inputs.json").read_text(
            encoding="utf-8"
        )
    )
    rows = [
        {
            "text_id": f"smoke-{int(row['fixture_index'])}",
            "text": row["explanation"],
            "activation_vector": row["activation_vector"],
        }
        for row in smoke["rows"]
    ]
    if len(rows) != 8:
        raise RuntimeError(f"expected 8 smoke explanations, found {len(rows)}")
    return rows


def _run_batch_validation(
    critic: Any,
    tokenizer: Any,
    cfg: Any,
) -> dict[str, Any]:
    rows = _load_smoke_rows()
    batch_scores = _score_rows(critic, tokenizer, cfg, rows, batch_size=32)
    unbatched_scores = [
        _score_rows(critic, tokenizer, cfg, [row], batch_size=1)[0]
        for row in rows
    ]
    comparisons = []
    for row, batch_score, unbatched_score in zip(
        rows, batch_scores, unbatched_scores
    ):
        denominator = max(abs(unbatched_score), 1e-12)
        relative_difference = abs(batch_score - unbatched_score) / denominator
        comparisons.append(
            {
                "text_id": row["text_id"],
                "fixture_index": int(row["text_id"].split("-")[-1]),
                "batch_32_mse": batch_score,
                "batch_1_mse": unbatched_score,
                "relative_difference": relative_difference,
                "pass": relative_difference < 0.01,
            }
        )
    all_rows_pass = all(row["pass"] for row in comparisons)
    return {
        "status": "passed" if all_rows_pass else "failed",
        "created_at_unix": time.time(),
        "source_sha256": SOURCE_SHA256,
        "billing_basis": BILLING_BASIS,
        "batch_sizes": [32, 1],
        "n_rows": len(rows),
        "relative_difference_threshold": 0.01,
        "per_row": comparisons,
        "all_rows_pass": all_rows_pass,
        "model_repo": MODEL_REPO,
        "mse_dtype": "fp32",
        "length_sorted_batching": True,
    }


@app.function(**GPU_FUNCTION_KWARGS)
def run_phase5() -> dict[str, Any]:
    """Run validation, primary scoring, and sibling scoring in one container."""

    import pyarrow as pa

    sampler = _ResourceSampler("score_all")
    started = time.time()
    result: dict[str, Any] = {
        "status": "failed",
        "created_at_unix": started,
        "source_sha256": SOURCE_SHA256,
        "billing_basis": BILLING_BASIS,
        "batch_size": BATCH_SIZE,
        "checkpoint_rows": CHECKPOINT_ROWS,
        "container": {
            "gpu": "A100-80GB",
            "cpu_reserved": 5,
            "memory_reserved_mib": 70_000,
            "max_containers": 1,
        },
    }
    sampler.start()
    try:
        predecessor_assertions = _assert_remote_predecessors()
        paid_predecessors = _assert_paid_predecessors()
        billing_start = _workspace_billing_snapshot()
        billing_start_total = _billing_reported_total(billing_start)
        result["billing_start"] = billing_start
        result["billing_basis"] = BILLING_BASIS
        activation_map = _load_activation_map()
        primary_rows = _load_primary_scoring_rows(activation_map)
        sibling_rows, recurrence = _load_sibling_scoring_rows(activation_map)
        primary_schema = pa.schema(
            [("text_id", pa.string()), ("mse", pa.float64())]
        )
        sibling_schema = pa.schema(
            [
                ("text_id", pa.string()),
                ("position_offset", pa.int32()),
                ("mse", pa.float64()),
            ]
        )
        primary_expected = {row["text_id"] for row in primary_rows}
        sibling_expected = {
            (row["text_id"], row["position_offset"]) for row in sibling_rows
        }
        primary_final = Path(REMOTE_PRIMARY_FINAL)
        sibling_final = Path(REMOTE_SIBLING_FINAL)
        primary_final.parent.mkdir(parents=True, exist_ok=True)
        sibling_final.parent.mkdir(parents=True, exist_ok=True)
        artifact_volume.commit()

        primary_complete = (
            _read_checkpoint(primary_final, primary_expected, lambda row: row["text_id"])
            if primary_final.exists()
            else None
        )
        sibling_complete = (
            _read_checkpoint(
                sibling_final,
                sibling_expected,
                lambda row: (row["text_id"], int(row["position_offset"])),
            )
            if sibling_final.exists()
            else None
        )

        critic = tokenizer = cfg = None
        batch_validation: dict[str, Any]
        existing_validation = None
        validation_path = Path(REMOTE_BATCH_VALIDATION_PATH)
        if validation_path.exists():
            existing_validation = _read_remote_json(str(validation_path))
        if (
            existing_validation is not None
            and existing_validation.get("status") == "passed"
            and existing_validation.get("source_sha256") == SOURCE_SHA256
        ):
            batch_validation = {
                "status": "passed",
                "skipped": True,
                "reason": "passed ar_batch_validation.json already exists",
                "source_sha256": SOURCE_SHA256,
                "billing_basis": BILLING_BASIS,
                "existing_evidence": REMOTE_BATCH_VALIDATION_PATH,
            }
        else:
            if primary_complete is None or sibling_complete is None or existing_validation is None:
                critic, tokenizer, cfg = _load_model_and_config()
            elif critic is None:
                critic, tokenizer, cfg = _load_model_and_config()
            batch_validation = _run_batch_validation(critic, tokenizer, cfg)
            _write_remote_json(
                f"{REMOTE_ARTIFACT_ROOT}/ar_batch_validation.json",
                batch_validation,
            )
            if batch_validation.get("status") != "passed":
                raise RuntimeError(json.dumps(batch_validation))

        if primary_complete is None or sibling_complete is None:
            if critic is None:
                critic, tokenizer, cfg = _load_model_and_config()

        primary_manifest = None
        if primary_complete is None:
            primary_scores = _score_rows(
                critic,
                tokenizer,
                cfg,
                primary_rows,
                batch_size=BATCH_SIZE,
            )
            primary_manifest = _checkpoint_rows(
                rows=primary_rows,
                scores=primary_scores,
                checkpoint_dir=REMOTE_PRIMARY_CHECKPOINT_DIR,
                evidence_dir=REMOTE_PRIMARY_EVIDENCE_DIR,
                label="primary",
                key_fn=lambda row: row["text_id"],
                output_schema=primary_schema,
                billing_start_total=billing_start_total,
            )
            primary_final_result = _assemble_final(
                final_path=REMOTE_PRIMARY_FINAL,
                checkpoint_dir=REMOTE_PRIMARY_CHECKPOINT_DIR,
                expected_keys=primary_expected,
                key_fn=lambda row: row["text_id"],
                schema=primary_schema,
            )
        else:
            primary_manifest = {
                "status": "passed",
                "rows_total": len(primary_complete),
                "skipped_existing_final": True,
                "checkpoint_rows": CHECKPOINT_ROWS,
            }
            primary_final_result = {
                "status": "passed",
                "rows": len(primary_complete),
                "skipped_existing": True,
            }
        primary_gate = {
            "status": "passed"
            if primary_final_result["rows"] == EXPECTED_TEXT_ROWS
            else "failed",
            "created_at_unix": time.time(),
            "rows_expected": EXPECTED_TEXT_ROWS,
            "rows_total": primary_final_result["rows"],
            "text_id_unique": True,
            "activation_target": "primary position_offset=0",
            "batch_size": BATCH_SIZE,
            "checkpoint_rows": CHECKPOINT_ROWS,
            "checkpoint_manifest": primary_manifest,
            "billing_basis": BILLING_BASIS,
        }
        _write_remote_json(REMOTE_PRIMARY_GATE_PATH, primary_gate)
        if primary_gate["status"] != "passed":
            raise RuntimeError(json.dumps(primary_gate))

        sibling_manifest = None
        if sibling_complete is None:
            sibling_scores = _score_rows(
                critic,
                tokenizer,
                cfg,
                sibling_rows,
                batch_size=BATCH_SIZE,
                key_fn=lambda row: (row["text_id"], row["position_offset"]),
            )
            sibling_manifest = _checkpoint_rows(
                rows=sibling_rows,
                scores=sibling_scores,
                checkpoint_dir=REMOTE_SIBLING_CHECKPOINT_DIR,
                evidence_dir=REMOTE_SIBLING_EVIDENCE_DIR,
                label="siblings",
                key_fn=lambda row: (row["text_id"], row["position_offset"]),
                output_schema=sibling_schema,
                billing_start_total=billing_start_total,
            )
            sibling_final_result = _assemble_final(
                final_path=REMOTE_SIBLING_FINAL,
                checkpoint_dir=REMOTE_SIBLING_CHECKPOINT_DIR,
                expected_keys=sibling_expected,
                key_fn=lambda row: (row["text_id"], int(row["position_offset"])),
                schema=sibling_schema,
            )
        else:
            sibling_manifest = {
                "status": "passed",
                "rows_total": len(sibling_complete),
                "skipped_existing_final": True,
                "checkpoint_rows": CHECKPOINT_ROWS,
            }
            sibling_final_result = {
                "status": "passed",
                "rows": len(sibling_complete),
                "skipped_existing": True,
            }
        sibling_gate = {
            "status": "passed"
            if sibling_final_result["rows"] == len(sibling_rows)
            else "failed",
            "created_at_unix": time.time(),
            "rows_expected": len(sibling_rows),
            "rows_total": sibling_final_result["rows"],
            "key_unique": True,
            "activation_target": "nearest sibling offsets 1..min(recurrence_positions, 3)",
            "batch_size": BATCH_SIZE,
            "checkpoint_rows": CHECKPOINT_ROWS,
            "checkpoint_manifest": sibling_manifest,
            "recurrence_inventory": {
                key: value
                for key, value in recurrence.items()
                if key not in {"selected_delete_rows", "recurrence_by_claim"}
            },
            "billing_basis": BILLING_BASIS,
        }
        _write_remote_json(REMOTE_SIBLING_GATE_PATH, sibling_gate)
        if sibling_gate["status"] != "passed":
            raise RuntimeError(json.dumps(sibling_gate))

        billing_completion = _workspace_billing_snapshot()
        billing_completion_total = _billing_reported_total(billing_completion)
        billing_delta = billing_completion_total - billing_start_total
        result["billing_completion"] = billing_completion
        result["workspace_all_in_delta"] = str(billing_delta)
        if billing_delta > 30:
            raise RuntimeError(
                "G6 workspace all-in delta exceeded $30 at completion: "
                f"{billing_delta}"
            )
        result.update(
            {
                "status": "passed",
                "duration_seconds": time.time() - started,
                "predecessor_assertions": predecessor_assertions,
                "paid_predecessors": paid_predecessors,
                "batch_validation": batch_validation,
                "primary": primary_gate,
                "siblings": sibling_gate,
                "outputs": {
                    "scores": REMOTE_PRIMARY_FINAL,
                    "scores_siblings": REMOTE_SIBLING_FINAL,
                },
            }
        )
    except Exception as exc:
        result.update(
            {
                "error": f"{type(exc).__name__}: {exc}",
                "duration_seconds": time.time() - started,
            }
        )
    result["resource_metrics"] = sampler.stop()
    _write_remote_json(REMOTE_SCORE_RESULT_PATH, result)
    if result["status"] != "passed":
        raise RuntimeError(json.dumps(result))
    return result


def _workspace_billing_snapshot() -> dict[str, Any]:
    """Read-only billing snapshot used for G6 accounting."""

    from decimal import Decimal

    from modal.billing import workspace_billing_report

    now = datetime.now(timezone.utc)
    end = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    start = end - timedelta(days=6)
    report = workspace_billing_report(start=start, end=end, resolution="h")
    line_items = [
        {
            "object_id": item["object_id"],
            "description": item["description"],
            "environment_name": item["environment_name"],
            "interval_start": item["interval_start"].isoformat(),
            "cost": str(item["cost"]),
            "tags": item.get("tags", {}),
        }
        for item in report
    ]
    reported_total = sum(
        (Decimal(str(item["cost"])) for item in report), Decimal("0")
    )
    return {
        "captured_at_unix": time.time(),
        "summary": {
            "reported_cost": str(reported_total),
            "billed_cost": None,
            "metered_cost": None,
            "billing_semantics": (
                "Modal public workspace billing report line-item total over a "
                "rolling six-day hourly window through the next hour boundary; "
                "public SDK exposes no credit-adjusted summary"
            ),
            "billing_basis": BILLING_BASIS,
        },
        "app_line_items": line_items,
    }


@app.local_entrypoint()
def main(mode: str = "preflight", label: str = "") -> None:
    """Run a phase step or capture a local G6 billing snapshot."""

    if mode == "preflight":
        result = preflight.remote()
        _atomic_json(PREFLIGHT_RESULT_PATH, result)
        print(json.dumps(result, indent=2), flush=True)
        return
    if mode in {"validate", "batch_validation"}:
        result = validate_batch.remote()
        _atomic_json(BATCH_VALIDATION_RESULT_PATH, result)
        print(json.dumps(result, indent=2), flush=True)
        return
    if mode == "billing":
        snapshot = _workspace_billing_snapshot()
        destination = RESULTS_DIR / (
            f"phase5_billing_{label or int(snapshot['captured_at_unix'])}.json"
        )
        _atomic_json(destination, snapshot)
        print(json.dumps(snapshot, indent=2), flush=True)
        return
    if mode == "score":
        result = run_phase5.remote()
        _atomic_json(SCORE_RESULT_PATH, result)
        print(json.dumps(result, indent=2), flush=True)
        return
    raise ValueError("mode must be preflight, validate, billing, or score")
