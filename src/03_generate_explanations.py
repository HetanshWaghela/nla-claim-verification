"""Generate AV explanations for the Phase 2b manifest."""

from __future__ import annotations

import json
import hashlib
import importlib
import importlib.metadata
import math
import os
import re
import shutil
import subprocess
import statistics
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import modal


ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "nla-verifier-phase2b"
MODEL_REPO = "ceselder/qwen3.6-27b-nla-rl"
AV_ADAPTER = "av_rl_adapters/iter_000300"
AR_FILES = [
    "ar_reconstructor/*",
    "av_base/chat_template.jinja",
    "av_base/tokenizer.json",
    "av_base/tokenizer_config.json",
    "data/example_activations.parquet",
    "nla_meta.yaml",
]
ACTIVATION_DIR = "/artifacts/phase2a/activations"
EXPLANATION_DIR = "/artifacts/phase2b/explanations"
OPTIMIZED_EXPLANATION_DIR = "/artifacts/phase2b_optimized/explanations"
OPTIMIZED_GATE_DIR = "/artifacts/phase2b_optimized/gates"
RESOURCE_METRICS_DIR = "/artifacts/phase2b/resource_metrics"
QUALIFICATION_PATH = "/artifacts/phase2b/batch_qualification.json"
BATCH_QUALIFICATION_FIX2_PATH = "/artifacts/phase2b/batch_qualification_fix2.json"
OPTIONC_QUALIFICATION_PATH = "/artifacts/phase2b/batch_qualification_optionc.json"
FVE_RESULT_REMOTE_PATH = "/artifacts/phase2b/batch_fve_equivalence.json"
SMOKE_INPUTS_REMOTE_PATH = "/workspace/data/smoke_inputs.json"
OPTIONC_PREFLIGHT_REMOTE_PATH = "/workspace/results/optionc_preflight.json"
MAX_NEW_TOKENS = 320
INJECTION_TOKEN_ID = 158983
QUALIFICATION_FIXTURE_INDICES = [48, 4, 1, 30]
PHASE2B_COST_CAP = 120.0
BILLING_BASIS = (
    "public per-cycle line-item report: Modal 1.4.3 workspace_billing_report "
    "at hourly resolution; the public SDK exposes no credit-adjusted summary"
)
ESCALATION_FLOOR_PER_300 = "3.00"
MANIFEST_ROWS = 3_900
SHARD_ROWS = 100
SHARD_COUNT = 39
OPTIMIZED_MANIFEST_PATH = ROOT / "data" / "generation_manifest_300.parquet"
OPTIMIZED_SHARD_ROWS = 300
OPTIMIZED_SHARD_COUNT = 13
CHECKPOINT_ROWS = 100

CONTEXTS_PATH = ROOT / "data" / "contexts.parquet"
SMOKE_INPUTS_PATH = ROOT / "results" / "smoke_inputs.json"
MANIFEST_PATH = ROOT / "data" / "generation_manifest.parquet"
SHARD0_RESULT_PATH = ROOT / "results" / "phase2b_shard0.json"
SHARD0_GATE_PATH = ROOT / "results" / "phase2b_shard0_gate.json"
OPTIMIZED_SHARD2_RESULT_PATH = ROOT / "results" / "phase2b_optimized_shard2.json"
OPTIMIZED_SHARD2_GATE_PATH = ROOT / "results" / "phase2b_optimized_shard2_gate.json"
OPTIONC_PREFLIGHT_PATH = ROOT / "results" / "optionc_preflight.json"
OPTIONC_QUALIFICATION_RESULT_PATH = ROOT / "results" / "batch_qualification_optionc.json"
FVE_RESULT_PATH = ROOT / "results" / "batch_fve_equivalence.json"
RIGHTSIZING_RESULT_PATH = ROOT / "results" / "container_rightsizing.json"
PROJECTION_RESULT_PATH = ROOT / "results" / "phase2b_final_projection.json"
FANOUT_RESULT_PATH = ROOT / "results" / "phase2b_optimized_fanout.json"
MERGE_RESULT_PATH = ROOT / "results" / "phase2_merge_gate.json"
PREVIEW_PATH = ROOT / "results" / "phase2_preview.md"

PREDECESSOR_EVIDENCE = [
    ROOT / "results" / "contexts_gate.json",
    ROOT / "results" / "activation_calibration.json",
    ROOT / "results" / "activation_gate.json",
    ROOT / "results" / "norm_outlier_investigation.md",
    ROOT / "results" / "fix1_kernel_gate.json",
    ROOT / "results" / "batch_qualification_fix2.json",
    ROOT / "results" / "fix2_batch_gate.json",
    ROOT / "results" / "phase2b_rebaseline_guard.json",
    ROOT / "results" / "phase2b_rebaseline_projection.json",
    OPTIMIZED_SHARD2_RESULT_PATH,
    OPTIMIZED_SHARD2_GATE_PATH,
]

cache_volume = modal.Volume.from_name("nla-verifier-cache", create_if_missing=True)
artifact_volume = modal.Volume.from_name(
    "nla-verifier-artifacts", create_if_missing=True
)


AV_FILES = [
    "av_base/*",
    f"{AV_ADAPTER}/*",
    "data/example_activations.parquet",
    "nla_meta.yaml",
]


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
if SMOKE_INPUTS_PATH.exists():
    image = image.add_local_file(str(SMOKE_INPUTS_PATH), SMOKE_INPUTS_REMOTE_PATH)
if OPTIONC_PREFLIGHT_PATH.exists():
    image = image.add_local_file(
        str(OPTIONC_PREFLIGHT_PATH), OPTIONC_PREFLIGHT_REMOTE_PATH
    )


GPU_FUNCTION_KWARGS_BATCH4 = {
    "image": image,
    "gpu": "A100-80GB",
    "cpu": 8,
    "memory": 128_000,
    "timeout": 24 * 60 * 60,
    "max_containers": 4,
    "volumes": {"/cache": cache_volume, "/artifacts": artifact_volume},
    "secrets": [modal.Secret.from_name("amnesiac-hf-auth")],
}

GPU_FUNCTION_KWARGS_BATCH1 = {
    **GPU_FUNCTION_KWARGS_BATCH4,
    "max_containers": 6,
}


app = modal.App(APP_NAME)


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    os.replace(temporary, path)


class _WorkerResourceSampler:
    """Best-effort worker telemetry required by the 2026-08-16b amendment."""

    def __init__(self, label: str, interval_seconds: float = 5.0) -> None:
        safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "_", label)
        self.interval_seconds = interval_seconds
        self.artifact_path = Path(RESOURCE_METRICS_DIR) / (
            f"{safe_label}_{int(time.time())}_{os.getpid()}.json"
        )
        self._process: Any = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._samples: list[dict[str, Any]] = []
        self._errors: list[str] = []
        self._stopped = False
        self._summary: dict[str, Any] | None = None

    def _record_error(self, exc: Exception) -> None:
        message = f"{type(exc).__name__}: {exc}"
        if message not in self._errors:
            self._errors.append(message)

    def _sample(self) -> None:
        if self._process is None:
            return
        try:
            rss_bytes = int(self._process.memory_info().rss)
            cpu_percent = float(self._process.cpu_percent(interval=None))
            self._samples.append(
                {
                    "captured_at_unix": time.time(),
                    "rss_bytes": rss_bytes,
                    "rss_mb": rss_bytes / (1024 * 1024),
                    "cpu_percent": cpu_percent,
                    "cpu_cores": cpu_percent / 100.0,
                }
            )
        except Exception as exc:
            self._record_error(exc)

    def _run(self) -> None:
        while not self._stop_event.wait(self.interval_seconds):
            self._sample()

    def start(self) -> None:
        try:
            import psutil

            self._process = psutil.Process(os.getpid())
            self._process.cpu_percent(interval=None)
            self._sample()
            self._thread = threading.Thread(
                target=self._run,
                name="phase2b-resource-sampler",
                daemon=True,
            )
            self._thread.start()
        except Exception as exc:
            self._record_error(exc)
            self._process = None

    def stop(self) -> dict[str, Any]:
        if self._stopped and self._summary is not None:
            return self._summary
        self._stopped = True
        if self._thread is not None:
            self._stop_event.set()
            self._thread.join(timeout=max(15.0, self.interval_seconds + 5.0))
        self._sample()
        peak_rss_bytes = max(
            (int(sample["rss_bytes"]) for sample in self._samples),
            default=None,
        )
        peak_cpu_percent = max(
            (float(sample["cpu_percent"]) for sample in self._samples),
            default=None,
        )
        summary: dict[str, Any] = {
            "measurement_status": (
                "passed" if self._process is not None and not self._errors else "unavailable"
            ),
            "sample_interval_seconds": self.interval_seconds,
            "sample_count": len(self._samples),
            "peak_rss_bytes": peak_rss_bytes,
            "peak_rss_mb": (
                peak_rss_bytes / (1024 * 1024)
                if peak_rss_bytes is not None
                else None
            ),
            "peak_cpu_percent": peak_cpu_percent,
            "peak_cpu_cores": (
                peak_cpu_percent / 100.0
                if peak_cpu_percent is not None
                else None
            ),
            "errors": list(self._errors),
            "artifact_path": str(self.artifact_path),
        }
        payload = {
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "worker_pid": os.getpid(),
            "label": self.artifact_path.stem,
            "sample_interval_seconds": self.interval_seconds,
            "summary": summary,
            "samples": self._samples,
        }
        try:
            self.artifact_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.artifact_path.with_suffix(
                self.artifact_path.suffix + ".tmp"
            )
            temporary.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(temporary, self.artifact_path)
            artifact_volume.commit()
        except Exception as exc:
            self._record_error(exc)
            summary["measurement_status"] = "unavailable"
            summary["errors"] = list(self._errors)
        self._summary = summary
        return summary


def _source_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _assert_predecessor_evidence() -> None:
    missing = [str(path) for path in PREDECESSOR_EVIDENCE if not path.exists()]
    if missing:
        raise RuntimeError(
            "missing predecessor evidence; refusing to continue: "
            + json.dumps(missing)
        )


def _assert_local_preflight() -> dict[str, Any]:
    if not OPTIONC_PREFLIGHT_PATH.exists():
        raise RuntimeError(f"missing required preflight evidence {OPTIONC_PREFLIGHT_PATH}")
    evidence = json.loads(OPTIONC_PREFLIGHT_PATH.read_text(encoding="utf-8"))
    if evidence.get("status") != "passed":
        raise RuntimeError("Option C preflight did not pass")
    if evidence.get("source_sha256") != _source_sha256():
        raise RuntimeError("Option C preflight was created for different source code")
    if OPTIONC_PREFLIGHT_PATH.stat().st_mtime <= Path(__file__).stat().st_mtime:
        raise RuntimeError("Option C preflight is not newer than the generation code")
    return evidence


def _assert_remote_preflight() -> dict[str, Any]:
    path = Path(OPTIONC_PREFLIGHT_REMOTE_PATH)
    if not path.exists():
        raise RuntimeError(f"missing mounted preflight evidence {path}")
    evidence = json.loads(path.read_text(encoding="utf-8"))
    if evidence.get("status") != "passed":
        raise RuntimeError("mounted Option C preflight did not pass")
    if evidence.get("source_sha256") != _source_sha256():
        raise RuntimeError("mounted preflight was created for different source code")
    if evidence.get("created_at_unix", 0) <= evidence.get("source_mtime_unix", 0):
        raise RuntimeError("mounted preflight is not newer than the generation code")
    return evidence


def _volume_listing(volume_name: str, path: str) -> list[dict[str, Any]]:
    modal_cli = shutil.which("modal")
    if modal_cli is None:
        raise RuntimeError("modal CLI is not available for the volume preflight")
    command = [modal_cli, "volume", "ls", volume_name]
    if path:
        command.append(path)
    command.append("--json")
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"volume listing failed for {path!r}: {completed.stderr.strip()}"
        )
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"volume listing was not JSON for {path!r}: {completed.stdout[:500]!r}"
        ) from exc
    if not isinstance(value, list):
        raise RuntimeError(f"volume listing for {path!r} was not a list")
    return value


def _workspace_billing_snapshot() -> dict[str, Any]:
    """Read-only billing snapshot used for G6 accounting."""

    from datetime import datetime, timedelta
    from decimal import Decimal

    from modal.billing import workspace_billing_report

    now = datetime.now(timezone.utc)
    start = datetime(2026, 8, 15, tzinfo=timezone.utc)
    end = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    if end <= start:
        end = start + timedelta(hours=1)
    report = workspace_billing_report(
        start=start,
        end=end,
        resolution="h",
    )
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
        (Decimal(str(item["cost"])) for item in report),
        Decimal("0"),
    )
    return {
        "captured_at_unix": time.time(),
        "summary": {
            "reported_cost": str(reported_total),
            "billed_cost": None,
            "metered_cost": None,
            "billing_semantics": (
                "Modal 1.4.3 public workspace billing report line-item total through "
                "the next hour boundary; the public SDK exposes no credit-adjusted "
                "summary."
            ),
            "billing_basis": BILLING_BASIS,
        },
        "app_line_items": line_items,
    }


def _billing_reported_total(snapshot: dict[str, Any]) -> "Decimal":
    from decimal import Decimal

    summary = snapshot.get("summary", {})
    value = summary.get("reported_cost")
    if value is None:
        value = summary.get("billed_cost")
    if value is None:
        raise RuntimeError("billing snapshot has no public reported cost total")
    return Decimal(str(value))


def _corrected_escalation_threshold(canonical_per_300: "Decimal") -> "Decimal":
    from decimal import Decimal

    return max(
        canonical_per_300 * Decimal("1.40"),
        Decimal(ESCALATION_FLOOR_PER_300),
    )


def _cold_start_excluded_wave_diagnostic(
    wave_results: list[dict[str, Any]],
    workspace_delta: "Decimal",
    actual_rows: int,
) -> dict[str, Any]:
    """Report the amendment's cold-start-excluded diagnostic only."""

    from decimal import Decimal

    metric_paths = sorted(
        {
            str(result.get("resource_metrics", {}).get("artifact_path"))
            for result in wave_results
            if result.get("resource_metrics", {}).get("artifact_path")
        }
    )
    fresh_container_count = len(metric_paths)
    excluded_rows = fresh_container_count * CHECKPOINT_ROWS
    diagnostic_rows = max(actual_rows - excluded_rows, 0)
    if diagnostic_rows > 0:
        cost_per_row = workspace_delta / Decimal(diagnostic_rows)
        cost_per_300 = cost_per_row * Decimal(OPTIMIZED_SHARD_ROWS)
        status = (
            "passed"
            if fresh_container_count == len(wave_results)
            else "partial_resource_evidence"
        )
    else:
        cost_per_row = None
        cost_per_300 = None
        status = "unavailable"
    return {
        "status": status,
        "billing_basis": BILLING_BASIS,
        "fresh_container_count": fresh_container_count,
        "fresh_container_metric_paths": metric_paths,
        "excluded_first_checkpoint_rows": excluded_rows,
        "diagnostic_rows_after_exclusion": diagnostic_rows,
        "wave_cost_per_row_excluding_first_checkpoint_of_each_fresh_container": (
            str(cost_per_row) if cost_per_row is not None else None
        ),
        "wave_cost_per_300_rows_excluding_first_checkpoint_of_each_fresh_container": (
            str(cost_per_300) if cost_per_300 is not None else None
        ),
        "used_for_escalation_gate": False,
        "note": (
            "Diagnostic only. The escalation gate uses the completed-wave "
            "per-cycle line-item delta divided by full 300-row shard count."
        ),
    }


def _retroactively_clear_wave1(
    projection: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], int]:
    """Apply Amendment 2026-08-16c without regenerating completed shards."""

    from decimal import Decimal

    wave_path = ROOT / "results" / "phase2b_optimized_wave_01.json"
    correction_path = ROOT / "results" / "phase2b_wave_01_correction.json"
    corrected_wave_path = ROOT / "results" / "phase2b_optimized_wave_01_corrected.json"
    if not wave_path.exists():
        raise RuntimeError(f"missing predecessor wave evidence {wave_path}")
    wave = json.loads(wave_path.read_text(encoding="utf-8"))
    canonical_per_300 = Decimal(
        str(projection["canonical_unit_cost_per_300_rows"])
    )
    corrected_threshold = _corrected_escalation_threshold(canonical_per_300)
    wave_cost = Decimal(str(wave["wave_cost_per_300_rows"]))
    diagnostic = _cold_start_excluded_wave_diagnostic(
        wave.get("results", []),
        Decimal(str(wave["workspace_billed_delta"])),
        int(wave["actual_rows"]),
    )
    cleared = (
        wave.get("gates_pass") is True
        and int(wave.get("actual_rows", 0)) == int(wave.get("expected_rows", -1))
        and wave_cost <= corrected_threshold
        and wave.get("projection_within_cap") is True
    )
    correction = {
        "status": "passed" if cleared else "failed_gate",
        "created_at_unix": time.time(),
        "directive": "AMENDMENT 2026-08-16c",
        "predecessor_wave": str(wave_path),
        "prior_wave_status": wave.get("status"),
        "shard_indices": wave.get("shard_indices", []),
        "actual_rows": wave.get("actual_rows"),
        "gates_pass": wave.get("gates_pass"),
        "canonical_cost_per_300_rows": str(canonical_per_300),
        "relative_escalation_threshold_per_300_rows": str(
            canonical_per_300 * Decimal("1.40")
        ),
        "absolute_escalation_floor_per_300_rows": ESCALATION_FLOOR_PER_300,
        "corrected_escalation_threshold_per_300_rows": str(corrected_threshold),
        "wave_cost_per_300_rows": str(wave_cost),
        "cost_escalated_under_corrected_rule": wave_cost > corrected_threshold,
        "billing_basis": BILLING_BASIS,
        "cold_start_excluded_diagnostic": diagnostic,
        "decision": "retroactively_cleared" if cleared else "halt",
        "anomalies": [] if cleared else ["wave-1 evidence did not satisfy the corrected rule"],
    }
    _atomic_json(correction_path, correction)
    if not cleared:
        raise RuntimeError(
            "Amendment 2026-08-16c correction gate failed; see "
            f"{correction_path}"
        )

    corrected_wave = dict(wave)
    corrected_wave.update(
        {
            "status": "passed",
            "amendment_2026_08_16c": str(correction_path),
            "billing_basis": BILLING_BASIS,
            "relative_escalation_threshold_per_300_rows": str(
                canonical_per_300 * Decimal("1.40")
            ),
            "absolute_escalation_floor_per_300_rows": ESCALATION_FLOOR_PER_300,
            "escalation_threshold_per_300_rows": str(corrected_threshold),
            "cost_escalated": False,
            "cold_start_excluded_diagnostic": diagnostic,
        }
    )
    _atomic_json(corrected_wave_path, corrected_wave)
    corrected_projection = dict(projection)
    corrected_projection.pop("error", None)
    corrected_projection.update(
        {
            "status": "proceed",
            "amendment_2026_08_16c": str(correction_path),
            "billing_basis": BILLING_BASIS,
            "relative_escalation_threshold_per_300_rows": str(
                canonical_per_300 * Decimal("1.40")
            ),
            "absolute_escalation_floor_per_300_rows": ESCALATION_FLOOR_PER_300,
            "escalation_threshold_per_300_rows": str(corrected_threshold),
        }
    )
    boundaries = corrected_projection.setdefault("completed_boundaries", [])
    boundary = next(
        (
            item
            for item in boundaries
            if item.get("boundary") == "wave_01"
        ),
        None,
    )
    if boundary is None:
        boundary = {"boundary": "wave_01"}
        boundaries.append(boundary)
    boundary.update(
        {
            "billing_basis": BILLING_BASIS,
            "corrected_escalation_threshold_per_300_rows": str(corrected_threshold),
            "cold_start_excluded_diagnostic": diagnostic,
        }
    )
    _atomic_json(PROJECTION_RESULT_PATH, corrected_projection)
    return corrected_projection, corrected_wave, 2


def _run_optionc_preflight() -> dict[str, Any]:
    started = time.time()
    errors: list[str] = []
    imports: dict[str, Any] = {}
    for module_name in (
        "modal",
        "torch",
        "transformers",
        "accelerate",
        "peft",
        "pyarrow",
        "yaml",
        "safetensors",
        "numpy",
        "huggingface_hub",
        "psutil",
        "nla.config",
        "nla.schema",
        "nla.utils",
        "fla",
    ):
        try:
            module = importlib.import_module(module_name)
            imports[module_name] = {
                "status": "imported",
                "version": getattr(module, "__version__", None),
            }
        except Exception as exc:  # evidence must still be written on failure
            imports[module_name] = {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            }
            errors.append(f"import {module_name}: {type(exc).__name__}: {exc}")

    distribution_versions: dict[str, str | None] = {}
    for distribution in (
        "flash-linear-attention",
        "fla-core",
        "transformers",
        "psutil",
    ):
        try:
            distribution_versions[distribution] = importlib.metadata.version(
                distribution
            )
        except importlib.metadata.PackageNotFoundError:
            distribution_versions[distribution] = None

    output_dirs = [ROOT / "results", ROOT / "data", ROOT / "data" / "explanations"]
    for directory in output_dirs:
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            errors.append(f"mkdir {directory}: {type(exc).__name__}: {exc}")

    config_paths = {
        "contexts": CONTEXTS_PATH,
        "smoke_inputs": SMOKE_INPUTS_PATH,
        "generation_manifest_300": OPTIMIZED_MANIFEST_PATH,
        "activation_dir": ROOT / "data" / "activations",
        "results_dir": ROOT / "results",
    }
    config_status = {
        name: {"path": str(path), "exists": path.exists()}
        for name, path in config_paths.items()
    }
    errors.extend(
        f"missing config path {item['path']}"
        for item in config_status.values()
        if not item["exists"]
    )

    predecessor_status = {
        str(path): path.exists() for path in PREDECESSOR_EVIDENCE
    }
    errors.extend(
        f"missing predecessor evidence {path}"
        for path, exists in predecessor_status.items()
        if not exists
    )

    volume_checks: dict[str, Any] = {}
    required_volume_files = {
        "phase2a/activations": ["shard_000.parquet", "shard_029.parquet"],
        "phase2b_optimized/explanations": ["shard_002.parquet"],
        "phase2b_optimized/gates": ["shard_002.json"],
    }
    for volume_path, required_files in required_volume_files.items():
        try:
            listing = _volume_listing("nla-verifier-artifacts", volume_path)
            names = {
                str(item.get("filename", item.get("Filename", ""))).split("/")[-1]
                for item in listing
            }
            missing = sorted(set(required_files) - names)
            volume_checks[volume_path] = {
                "status": "passed" if not missing else "failed",
                "required_files": required_files,
                "missing_files": missing,
                "listing": listing,
            }
            errors.extend(
                f"missing Volume file {volume_path}/{name}" for name in missing
            )
        except Exception as exc:
            volume_checks[volume_path] = {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            }
            errors.append(f"volume {volume_path}: {type(exc).__name__}: {exc}")

    dummy_input_ids = [
        [0, 0, 101, INJECTION_TOKEN_ID, 102, 103],
        [0, 101, INJECTION_TOKEN_ID, 102, 103, 104],
        [101, INJECTION_TOKEN_ID, 102, 103, 104, 105],
    ]
    dummy_attention_mask = [
        [0, 0, 1, 1, 1, 1],
        [0, 1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1, 1],
    ]
    dummy_positions: list[int] | None = None
    try:
        dummy_positions = _marker_positions_from_batch(
            dummy_input_ids,
            dummy_attention_mask,
        )
        if dummy_positions != [3, 2, 1]:
            raise AssertionError(
                f"dummy marker positions did not reflect left padding: {dummy_positions}"
            )
    except Exception as exc:
        errors.append(f"dummy marker-position dry-run: {type(exc).__name__}: {exc}")

    try:
        billing = _workspace_billing_snapshot()
    except Exception as exc:
        billing = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
        errors.append(f"billing snapshot: {type(exc).__name__}: {exc}")

    evidence = {
        "status": "passed" if not errors else "failed",
        "created_at_unix": time.time(),
        "elapsed_seconds": round(time.time() - started, 3),
        "source_path": str(Path(__file__).resolve()),
        "source_mtime_unix": Path(__file__).stat().st_mtime,
        "source_sha256": _source_sha256(),
        "predecessor_evidence": predecessor_status,
        "imports": imports,
        "distribution_versions": distribution_versions,
        "output_dirs": [str(directory) for directory in output_dirs],
        "config_paths": config_status,
        "volume_checks": volume_checks,
        "dummy_marker_positions": dummy_positions,
        "billing_snapshot": billing,
        "errors": errors,
    }
    _atomic_json(OPTIONC_PREFLIGHT_PATH, evidence)
    if errors:
        raise RuntimeError(
            "Option C preflight failed; see "
            f"{OPTIONC_PREFLIGHT_PATH}: {json.dumps(errors)}"
        )
    return evidence


def _manifest_seed(context_id: str, position_offset: int, sample_idx: int) -> int:
    # Context IDs are c000..c299. Hash the stable numeric ID so the required
    # tuple-hash seed is identical across Python processes (string hashes are
    # intentionally randomized unless PYTHONHASHSEED is fixed).
    return hash((int(context_id[1:]), position_offset, sample_idx)) % (2**31)


def _interleaved_contexts() -> list[dict[str, Any]]:
    import pyarrow.parquet as pq

    contexts = pq.read_table(CONTEXTS_PATH).to_pylist()
    if len(contexts) != 300:
        raise RuntimeError(f"expected 300 contexts, found {len(contexts)}")
    by_stratum: dict[str, list[dict[str, Any]]] = {"A": [], "B": [], "C": []}
    for row in contexts:
        by_stratum[str(row["stratum"])].append(row)
    if any(len(rows) != 100 for rows in by_stratum.values()):
        raise RuntimeError(
            "context strata contradict Phase 1: "
            + json.dumps({key: len(value) for key, value in by_stratum.items()})
        )
    for rows in by_stratum.values():
        rows.sort(key=lambda row: str(row["context_id"]))
    return [
        by_stratum[stratum][index]
        for index in range(100)
        for stratum in ("A", "B", "C")
    ]


def _build_manifest(shard_rows: int, shard_count: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for context in _interleaved_contexts():
        context_id = str(context["context_id"])
        context_number = int(context_id[1:])
        for position_offset in range(10):
            sample_count = 4 if position_offset == 0 else 1
            for sample_idx in range(sample_count):
                rows.append(
                    {
                        "generation_index": len(rows),
                        "shard_index": len(rows) // shard_rows,
                        "context_id": context_id,
                        "stratum": str(context["stratum"]),
                        "position_offset": position_offset,
                        "sample_idx": sample_idx,
                        "activation_shard": context_number // 10,
                        "seed": _manifest_seed(
                            context_id, position_offset, sample_idx
                        ),
                    }
                )
    if len(rows) != MANIFEST_ROWS:
        raise RuntimeError(f"expected {MANIFEST_ROWS} manifest rows, found {len(rows)}")
    if any(row["shard_index"] >= shard_count for row in rows):
        raise RuntimeError(
            f"manifest contains a shard outside 000..{shard_count - 1:03d}"
        )
    if any(
        sum(row["shard_index"] == shard_index for row in rows) != shard_rows
        for shard_index in range(shard_count)
    ):
        raise RuntimeError(f"manifest shards are not exactly {shard_rows} rows each")
    return rows


def _expected_manifest() -> list[dict[str, Any]]:
    return _build_manifest(SHARD_ROWS, SHARD_COUNT)


def _expected_optimized_manifest() -> list[dict[str, Any]]:
    return _build_manifest(OPTIMIZED_SHARD_ROWS, OPTIMIZED_SHARD_COUNT)


def _ensure_manifest() -> list[dict[str, Any]]:
    import pyarrow as pa
    import pyarrow.parquet as pq

    expected = _expected_manifest()
    if MANIFEST_PATH.exists():
        existing = pq.read_table(MANIFEST_PATH).to_pylist()
        if existing != expected:
            raise RuntimeError(
                f"existing {MANIFEST_PATH} does not match the deterministic manifest"
            )
        return existing

    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = MANIFEST_PATH.with_suffix(MANIFEST_PATH.suffix + ".tmp")
    schema = pa.schema(
        [
            ("generation_index", pa.int32()),
            ("shard_index", pa.int32()),
            ("context_id", pa.string()),
            ("stratum", pa.string()),
            ("position_offset", pa.int32()),
            ("sample_idx", pa.int32()),
            ("activation_shard", pa.int32()),
            ("seed", pa.int64()),
        ]
    )
    pq.write_table(pa.Table.from_pylist(expected, schema=schema), temporary)
    os.replace(temporary, MANIFEST_PATH)
    return expected


def _ensure_optimized_manifest() -> list[dict[str, Any]]:
    import pyarrow as pa
    import pyarrow.parquet as pq

    expected = _expected_optimized_manifest()
    if OPTIMIZED_MANIFEST_PATH.exists():
        existing = pq.read_table(OPTIMIZED_MANIFEST_PATH).to_pylist()
        if existing != expected:
            raise RuntimeError(
                f"existing {OPTIMIZED_MANIFEST_PATH} does not match the "
                "deterministic 300-row manifest"
            )
        return existing

    OPTIMIZED_MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = OPTIMIZED_MANIFEST_PATH.with_suffix(
        OPTIMIZED_MANIFEST_PATH.suffix + ".tmp"
    )
    schema = pa.schema(
        [
            ("generation_index", pa.int32()),
            ("shard_index", pa.int32()),
            ("context_id", pa.string()),
            ("stratum", pa.string()),
            ("position_offset", pa.int32()),
            ("sample_idx", pa.int32()),
            ("activation_shard", pa.int32()),
            ("seed", pa.int64()),
        ]
    )
    pq.write_table(pa.Table.from_pylist(expected, schema=schema), temporary)
    os.replace(temporary, OPTIMIZED_MANIFEST_PATH)
    return expected


def _group_manifest(
    rows: list[dict[str, Any]],
    *,
    shard_rows: int = SHARD_ROWS,
    shard_count: int = SHARD_COUNT,
) -> dict[int, list[dict[str, Any]]]:
    grouped = {shard_index: [] for shard_index in range(shard_count)}
    for row in rows:
        grouped[int(row["shard_index"])].append(row)
    for shard_index, rows_in_shard in grouped.items():
        if len(rows_in_shard) != shard_rows:
            raise RuntimeError(
                f"manifest shard {shard_index} contains {len(rows_in_shard)} rows; "
                f"expected {shard_rows}"
            )
    return grouped


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


def _actor_inputs(tokenizer: Any, cfg: Any):
    content = cfg.actor_prompt_template.format(injection_char=cfg.injection_char)
    encoded = tokenizer.apply_chat_template(
        [{"role": "user", "content": content}],
        tokenize=True,
        add_generation_prompt=True,
        enable_thinking=False,
        return_tensors="pt",
    )
    if hasattr(encoded, "keys"):
        input_ids = encoded["input_ids"]
        attention_mask = encoded.get("attention_mask")
    else:
        input_ids = encoded
        attention_mask = None
    if attention_mask is None:
        attention_mask = input_ids.new_ones(input_ids.shape)
    return input_ids, attention_mask


def _marker_positions_from_batch(
    input_ids: Any,
    attention_mask: Any,
    marker_id: int = INJECTION_TOKEN_ID,
) -> list[int]:
    """Return each row's absolute marker column under left padding.

    The scan intentionally uses the row's masked token stream instead of a
    single prompt length.  This is the data-boundary invariant for Option C:
    every row has one marker, and left-padding offsets are not shared across
    rows.
    """

    ids_rows = (
        input_ids.detach().cpu().tolist()
        if hasattr(input_ids, "detach")
        else input_ids.tolist()
        if hasattr(input_ids, "tolist")
        else input_ids
    )
    mask_rows = (
        attention_mask.detach().cpu().tolist()
        if hasattr(attention_mask, "detach")
        else attention_mask.tolist()
        if hasattr(attention_mask, "tolist")
        else attention_mask
    )
    if len(ids_rows) != len(mask_rows):
        raise AssertionError(
            f"input/mask row count mismatch: {len(ids_rows)} != {len(mask_rows)}"
        )
    positions: list[int] = []
    left_padding: list[int] = []
    for row_index, (ids, mask) in enumerate(zip(ids_rows, mask_rows)):
        if len(ids) != len(mask):
            raise AssertionError(
                f"row {row_index} input/mask width mismatch: {len(ids)} != {len(mask)}"
            )
        all_matches = [column for column, token in enumerate(ids) if int(token) == marker_id]
        active_matches = [
            column
            for column, (token, active) in enumerate(zip(ids, mask))
            if int(active) == 1 and int(token) == marker_id
        ]
        assert len(all_matches) == 1 and len(active_matches) == 1, (
            f"row {row_index} must contain exactly one active marker token "
            f"{marker_id}; all_matches={all_matches}, active_matches={active_matches}"
        )
        active_columns = [column for column, active in enumerate(mask) if int(active) == 1]
        assert active_columns, f"row {row_index} has an empty attention mask"
        left_padding.append(active_columns[0])
        positions.append(active_matches[0])
    if len(set(left_padding)) > 1:
        assert len(set(positions)) > 1, (
            "rows have different left-padding offsets but share one absolute "
            f"marker column: padding={left_padding}, positions={positions}"
        )
    return positions


def _trim_generated_token_ids(
    token_ids: list[int],
    *,
    eos_token_id: int | None,
    pad_token_id: int | None,
) -> list[int]:
    """Remove batch padding while retaining the first EOS token."""

    normalized = [int(token) for token in token_ids]
    if eos_token_id is not None and eos_token_id in normalized:
        return normalized[: normalized.index(eos_token_id) + 1]
    if pad_token_id is not None:
        while normalized and normalized[-1] == pad_token_id:
            normalized.pop()
    return normalized


def _load_actor():
    import pyarrow.parquet as pq
    import torch
    from huggingface_hub import snapshot_download
    from peft import PeftModel
    from transformers import AutoModelForCausalLM

    from nla.config import load_nla_config
    from nla.utils import register_karvonen_hook

    repo_dir = snapshot_download(
        MODEL_REPO,
        allow_patterns=AV_FILES,
        cache_dir="/cache/huggingface/hub",
        token=True,
    )
    cache_volume.commit()
    tokenizer = _load_tokenizer(repo_dir)
    cfg = load_nla_config(repo_dir, tokenizer)
    device = torch.device("cuda:0")
    base = AutoModelForCausalLM.from_pretrained(
        Path(repo_dir) / "av_base",
        torch_dtype=torch.bfloat16,
        device_map={"": device},
        attn_implementation="sdpa",
        low_cpu_mem_usage=True,
    )
    actor = PeftModel.from_pretrained(
        base, Path(repo_dir) / AV_ADAPTER
    ).eval()
    vectors_ref: list[torch.Tensor | None] = [None]
    register_karvonen_hook(
        actor,
        vectors_ref,
        cfg.injection_token_id,
        cfg.injection_left_neighbor_id,
        cfg.injection_right_neighbor_id,
        layer_idx=1,
    )
    fixture_rows = pq.read_table(
        Path(repo_dir) / "data/example_activations.parquet"
    ).to_pylist()
    if len(fixture_rows) != 64:
        raise RuntimeError(f"expected 64 fixture rows, found {len(fixture_rows)}")
    return actor, tokenizer, cfg, device, vectors_ref, fixture_rows


def _seeded_batched_generate(
    actor: Any,
    tokenizer: Any,
    cfg: Any,
    device: Any,
    vectors_ref: list[Any],
    activations: list[list[float]],
    seeds: list[int],
    *,
    sample: bool,
    position_log: list[dict[str, Any]] | None = None,
) -> list[tuple[str, list[int]]]:
    import torch

    assert int(cfg.injection_token_id) == INJECTION_TOKEN_ID, (
        "configured marker token differs from the amended runbook: "
        f"{cfg.injection_token_id} != {INJECTION_TOKEN_ID}"
    )
    tokenizer.padding_side = "left"
    input_ids, attention_mask = _actor_inputs(tokenizer, cfg)
    input_ids = input_ids.repeat(len(activations), 1)
    attention_mask = attention_mask.repeat(len(activations), 1)
    marker_positions = _marker_positions_from_batch(input_ids, attention_mask)
    assert len(marker_positions) == len(activations), (
        "marker/vector row mismatch: "
        f"positions={len(marker_positions)}, vectors={len(activations)}"
    )
    position_records = [
        {
            "row_index": row_index,
            "marker_column": int(marker_position),
            "left_padding": next(
                column
                for column, active in enumerate(
                    attention_mask[row_index].tolist()
                    if hasattr(attention_mask[row_index], "tolist")
                    else attention_mask[row_index]
                )
                if int(active) == 1
            ),
        }
        for row_index, marker_position in enumerate(marker_positions)
    ]
    if position_log is not None:
        position_log.extend(position_records)
    print(
        json.dumps(
            {
                "event": "optionc_marker_positions",
                "marker_token_id": INJECTION_TOKEN_ID,
                "positions": position_records,
            }
        ),
        flush=True,
    )
    prompt_length = int(input_ids.shape[1])
    input_ids = input_ids.to(device)
    attention_mask = attention_mask.to(device)
    vectors_ref[0] = torch.tensor(activations, dtype=torch.float32, device=device)
    try:
        if sample:
            generators = [
                torch.Generator(device=device).manual_seed(int(seed))
                for seed in seeds
            ]
            original_multinomial = torch.multinomial
            batch_size = len(generators)

            def seeded_multinomial(
                probabilities,
                num_samples,
                replacement=False,
                *,
                generator=None,
                out=None,
            ):
                if (
                    probabilities.ndim == 2
                    and probabilities.shape[0] == batch_size
                    and num_samples == 1
                ):
                    sampled = torch.cat(
                        [
                            original_multinomial(
                                probabilities[index : index + 1],
                                num_samples,
                                replacement,
                                generator=generators[index],
                            )
                            for index in range(batch_size)
                        ],
                        dim=0,
                    )
                    if out is not None:
                        out.copy_(sampled)
                        return out
                    return sampled
                return original_multinomial(
                    probabilities,
                    num_samples,
                    replacement,
                    generator=generator,
                    out=out,
                )

            torch.multinomial = seeded_multinomial
        output = actor.generate(
            input_ids=input_ids,
            attention_mask=attention_mask,
            max_new_tokens=MAX_NEW_TOKENS,
            do_sample=sample,
            temperature=1.0,
            top_p=1.0,
            pad_token_id=tokenizer.eos_token_id,
            return_dict_in_generate=True,
        )
    finally:
        vectors_ref[0] = None
        if sample:
            torch.multinomial = original_multinomial

    generated_ids = output.sequences[:, prompt_length:]
    trimmed_ids = [
        _trim_generated_token_ids(
            token_ids.tolist(),
            eos_token_id=tokenizer.eos_token_id,
            pad_token_id=tokenizer.pad_token_id,
        )
        for token_ids in generated_ids
    ]
    responses = tokenizer.batch_decode(trimmed_ids, skip_special_tokens=True)
    return [
        (response, token_ids)
        for response, token_ids in zip(responses, trimmed_ids)
    ]


def _score_ar_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Reuse the smoke-test AR scoring path for the 16-row FVE sample."""

    import pyarrow.parquet as pq
    import torch
    import torch.nn.functional as F
    from huggingface_hub import snapshot_download

    from nla.config import load_nla_config
    from nla.models import NLACriticModel
    from nla.schema import normalize_activation
    from nla.utils import critic_predict

    if len(rows) != 16:
        raise RuntimeError(f"FVE AR scorer expected 16 rows, found {len(rows)}")
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

    device = torch.device("cuda:0")
    critic = NLACriticModel.from_pretrained(
        Path(repo_dir) / "ar_reconstructor",
        torch_dtype=torch.bfloat16,
        device_map={"": device},
        attn_implementation="sdpa",
    ).eval()
    token_rows = [
        tokenizer.encode(
            cfg.critic_prompt_template.format(explanation=row["explanation"]),
            add_special_tokens=False,
        )
        for row in rows
    ]
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
        [row["activation_vector"] for row in rows],
        dtype=torch.float32,
        device=device,
    )
    mse_scale = cfg.mse_scale
    with torch.inference_mode():
        prediction = critic_predict(critic, input_ids, attention_mask, mse_scale)
        pred_norm = normalize_activation(prediction, mse_scale)
        gold_norm = normalize_activation(gold, mse_scale)
        per_row_mse = F.mse_loss(pred_norm, gold_norm, reduction="none").mean(dim=1)

    table = pq.read_table(Path(repo_dir) / "data/example_activations.parquet")
    all_gold = torch.tensor(
        table.column("activation_vector").to_pylist(),
        dtype=torch.float32,
        device=device,
    )
    all_norm = normalize_activation(all_gold, mse_scale)
    mean_activation = all_norm.mean(dim=0, keepdim=True)
    baseline_mse = ((all_norm - mean_activation) ** 2).mean().item()
    mean_mse = per_row_mse.mean().item()
    sampled_fve = 1.0 - mean_mse / baseline_mse
    return {
        "mse_scale": mse_scale,
        "baseline_mse_all_64": baseline_mse,
        "mean_mse_scored_sample": mean_mse,
        "sampled_fve": sampled_fve,
        "per_row_scores": [
            {
                "mse": float(mse),
                "fve_against_all_64_baseline": 1.0
                - float(mse) / baseline_mse,
            }
            for mse in per_row_mse.tolist()
        ],
    }


def _generate_in_batches(
    actor: Any,
    tokenizer: Any,
    cfg: Any,
    device: Any,
    vectors_ref: list[Any],
    rows: list[dict[str, Any]],
    activations: dict[tuple[str, int], list[float]],
    batch_size: int,
    *,
    expected_rows: int = SHARD_ROWS,
) -> list[dict[str, Any]]:
    generated: list[dict[str, Any]] = []
    for start in range(0, len(rows), batch_size):
        batch_rows = rows[start : start + batch_size]
        batch_activations = [
            activations[(str(row["context_id"]), int(row["position_offset"]))]
            for row in batch_rows
        ]
        batch_seeds = [int(row["seed"]) for row in batch_rows]
        batch_outputs = _seeded_batched_generate(
            actor,
            tokenizer,
            cfg,
            device,
            vectors_ref,
            batch_activations,
            batch_seeds,
            sample=True,
        )
        for row, (response, token_ids) in zip(batch_rows, batch_outputs):
            from nla.schema import EXPLANATION_RE

            match = EXPLANATION_RE.search(response)
            explanation = match.group(1).strip() if match else ""
            generated.append(
                {
                    **row,
                    "text": explanation,
                    "full_response": response,
                    "n_tokens": len(
                        tokenizer.encode(explanation, add_special_tokens=False)
                    ),
                    "batch_size": len(batch_rows),
                    "generated_token_ids": token_ids,
                }
            )
    if len(generated) != expected_rows:
        raise RuntimeError(
            f"generated {len(generated)} rows instead of {expected_rows}"
        )
    return generated


def _load_activation_vectors(
    manifest_rows: list[dict[str, Any]],
) -> dict[tuple[str, int], list[float]]:
    import pyarrow.parquet as pq

    activation_shards = sorted(
        {int(row["activation_shard"]) for row in manifest_rows}
    )
    vectors: dict[tuple[str, int], list[float]] = {}
    for shard_index in activation_shards:
        path = Path(ACTIVATION_DIR) / f"shard_{shard_index:03d}.parquet"
        if not path.exists():
            raise RuntimeError(f"missing activation shard {path}")
        for row in pq.read_table(path).to_pylist():
            key = (str(row["context_id"]), int(row["position_offset"]))
            vectors[key] = row["activation_vector"]
    expected = {
        (str(row["context_id"]), int(row["position_offset"]))
        for row in manifest_rows
    }
    missing = sorted(expected - vectors.keys())
    if missing:
        raise RuntimeError(f"missing {len(missing)} activation keys, first={missing[:3]}")
    return vectors


def _smoke_mean_tokens(tokenizer: Any) -> float:
    if not Path(SMOKE_INPUTS_REMOTE_PATH).exists():
        raise RuntimeError(f"missing mounted smoke artifact {SMOKE_INPUTS_REMOTE_PATH}")
    artifact = json.loads(Path(SMOKE_INPUTS_REMOTE_PATH).read_text(encoding="utf-8"))
    lengths = [
        len(tokenizer.encode(row["explanation"], add_special_tokens=False))
        for row in artifact["rows"]
    ]
    if len(lengths) != 8:
        raise RuntimeError(f"expected 8 smoke explanations, found {len(lengths)}")
    return float(statistics.mean(lengths))


def _qualification(
    actor: Any,
    tokenizer: Any,
    cfg: Any,
    device: Any,
    vectors_ref: list[Any],
    fixture_rows: list[dict[str, Any]],
    attempted_batch_size: int = 8,
) -> dict[str, Any]:
    fixtures = [fixture_rows[index] for index in QUALIFICATION_FIXTURE_INDICES]
    activations = [row["activation_vector"] for row in fixtures]
    if attempted_batch_size < len(activations):
        raise ValueError(
            f"qualification batch must be at least {len(activations)}, "
            f"got {attempted_batch_size}"
        )
    batched_activations = (
        activations * ((attempted_batch_size + len(activations) - 1) // len(activations))
    )[:attempted_batch_size]
    batched_position_log: list[dict[str, Any]] = []
    batched = _seeded_batched_generate(
        actor,
        tokenizer,
        cfg,
        device,
        vectors_ref,
        batched_activations,
        [0] * attempted_batch_size,
        sample=False,
        position_log=batched_position_log,
    )
    unbatched = []
    unbatched_position_log: list[dict[str, Any]] = []
    for fixture_index, activation in zip(QUALIFICATION_FIXTURE_INDICES, activations):
        call_position_log: list[dict[str, Any]] = []
        unbatched.extend(
            _seeded_batched_generate(
                actor,
                tokenizer,
                cfg,
                device,
                vectors_ref,
                [activation],
                [0],
                sample=False,
                position_log=call_position_log,
            )
        )
        for record in call_position_log:
            unbatched_position_log.append(
                {"fixture_index": fixture_index, **record}
            )
    identical = [batched[index][1] == unbatched[index][1] for index in range(4)]
    result = {
        "created_at_unix": time.time(),
        "fixture_indices": QUALIFICATION_FIXTURE_INDICES,
        "attempted_batch_size": attempted_batch_size,
        "padding_side": tokenizer.padding_side,
        "qualification": "pass" if all(identical) else "fail",
        "batch_size": attempted_batch_size if all(identical) else 1,
        "token_identical_by_fixture": identical,
        "batched_token_lengths": [len(batched[index][1]) for index in range(4)],
        "unbatched_token_lengths": [len(item[1]) for item in unbatched],
        "batched_marker_positions": batched_position_log,
        "unbatched_marker_positions": unbatched_position_log,
        "batched_outputs": [
            {
                "fixture_index": QUALIFICATION_FIXTURE_INDICES[index % 4],
                "batch_row": index,
                "full_response": response,
                "token_ids": token_ids,
            }
            for index, (response, token_ids) in enumerate(batched)
        ],
        "unbatched_outputs": [
            {
                "fixture_index": fixture_index,
                "full_response": response,
                "token_ids": token_ids,
            }
            for fixture_index, (response, token_ids) in zip(
                QUALIFICATION_FIXTURE_INDICES, unbatched
            )
        ],
        "fallback_reason": None
        if all(identical)
        else "batched and unbatched greedy token sequences differed",
    }
    return result


@app.function(**GPU_FUNCTION_KWARGS_BATCH4)
def qualify_batching() -> dict[str, Any]:
    """Run the amendment's batch-8, then batch-4 qualification."""

    import gc

    import torch

    actor, tokenizer, cfg, device, vectors_ref, fixture_rows = _load_actor()
    attempts = [_qualification(
        actor,
        tokenizer,
        cfg,
        device,
        vectors_ref,
        fixture_rows,
        attempted_batch_size=8,
    )]
    if attempts[0]["qualification"] != "pass":
        attempts.append(_qualification(
            actor,
            tokenizer,
            cfg,
            device,
            vectors_ref,
            fixture_rows,
            attempted_batch_size=4,
        ))
    selected_batch_size = next(
        (
            attempt["attempted_batch_size"]
            for attempt in attempts
            if attempt["qualification"] == "pass"
        ),
        1,
    )
    result = {
        "created_at_unix": time.time(),
        "attempts": attempts,
        "selected_batch_size": selected_batch_size,
        "fallback_to_batch_1": selected_batch_size == 1,
    }
    _atomic_json(Path(BATCH_QUALIFICATION_FIX2_PATH), result)
    artifact_volume.commit()
    del actor
    gc.collect()
    torch.cuda.empty_cache()
    return result


@app.function(**GPU_FUNCTION_KWARGS_BATCH4)
def qualify_batching_optionc() -> dict[str, Any]:
    """Run Option C's only permitted paid qualification: batch 8 vs single-row."""

    import gc

    import torch

    _assert_remote_preflight()
    result: dict[str, Any]
    try:
        actor, tokenizer, cfg, device, vectors_ref, fixture_rows = _load_actor()
        if int(cfg.injection_token_id) != INJECTION_TOKEN_ID:
            raise RuntimeError(
                "checkpoint injection token contradicts the amended runbook: "
                f"{cfg.injection_token_id} != {INJECTION_TOKEN_ID}"
            )
        result = _qualification(
            actor,
            tokenizer,
            cfg,
            device,
            vectors_ref,
            fixture_rows,
            attempted_batch_size=8,
        )
        result = {
            "status": "passed" if result["qualification"] == "pass" else "failed_gate",
            "option": "C",
            **result,
        }
        _atomic_json(Path(OPTIONC_QUALIFICATION_PATH), result)
        artifact_volume.commit()
        return result
    except Exception as exc:
        failure = {
            "status": "error",
            "option": "C",
            "created_at_unix": time.time(),
            "error": f"{type(exc).__name__}: {exc}",
        }
        _atomic_json(Path(OPTIONC_QUALIFICATION_PATH), failure)
        artifact_volume.commit()
        raise
    finally:
        if "actor" in locals():
            del actor
        gc.collect()
        torch.cuda.empty_cache()


@app.function(**GPU_FUNCTION_KWARGS_BATCH4)
def run_batch_fve_equivalence() -> dict[str, Any]:
    """Run the amendment's 16-row batch-8 FVE gate with worker telemetry."""

    import gc

    import torch

    started = time.time()
    sampler = _WorkerResourceSampler("batch_fve_equivalence")
    sampler.start()
    actor = None
    result: dict[str, Any]
    try:
        _assert_remote_preflight()
        artifact_volume.reload()
        smoke_artifact = json.loads(
            Path(SMOKE_INPUTS_REMOTE_PATH).read_text(encoding="utf-8")
        )
        smoke_rows = list(smoke_artifact.get("rows", []))
        if len(smoke_rows) != 8:
            raise RuntimeError(
                f"FVE expected the eight smoke fixtures, found {len(smoke_rows)}"
            )

        actor, tokenizer, cfg, device, vectors_ref, _ = _load_actor()
        if int(cfg.injection_token_id) != INJECTION_TOKEN_ID:
            raise RuntimeError(
                "checkpoint injection token contradicts the amended runbook: "
                f"{cfg.injection_token_id} != {INJECTION_TOKEN_ID}"
            )
        tokenizer.padding_side = "left"
        prompt_input_ids, prompt_attention_mask = _actor_inputs(tokenizer, cfg)
        prompt_lengths = [int(prompt_input_ids.shape[1])] * len(smoke_rows)
        prompt_positions = _marker_positions_from_batch(
            prompt_input_ids.repeat(len(smoke_rows), 1),
            prompt_attention_mask.repeat(len(smoke_rows), 1),
        )
        prompt_length_uniform = len(set(prompt_lengths)) == 1

        generated_rows: list[dict[str, Any]] = []
        position_logs: list[dict[str, Any]] = []
        seeds_logged: list[int] = []
        from nla.schema import EXPLANATION_RE

        for repeat_index in range(2):
            batch_seeds = [repeat_index * 8 + row_index for row_index in range(8)]
            seeds_logged.extend(batch_seeds)
            batch_outputs = _seeded_batched_generate(
                actor,
                tokenizer,
                cfg,
                device,
                vectors_ref,
                [row["activation_vector"] for row in smoke_rows],
                batch_seeds,
                sample=True,
                position_log=position_logs,
            )
            for row_index, (response, token_ids) in enumerate(batch_outputs):
                smoke_row = smoke_rows[row_index]
                match = EXPLANATION_RE.search(response)
                explanation = match.group(1).strip() if match else ""
                generated_rows.append(
                    {
                        "row_index": len(generated_rows),
                        "fixture_index": int(smoke_row["fixture_index"]),
                        "repeat_index": repeat_index,
                        "batch_row": row_index,
                        "seed": batch_seeds[row_index],
                        "batch_size": 8,
                        "full_response": response,
                        "explanation": explanation,
                        "token_ids": token_ids,
                        "n_tokens": len(
                            tokenizer.encode(
                                explanation,
                                add_special_tokens=False,
                            )
                        ),
                        "activation_vector": smoke_row["activation_vector"],
                    }
                )

        actor = None
        gc.collect()
        torch.cuda.empty_cache()
        ar_scores = _score_ar_rows(generated_rows)
        refusal_re = re.compile(r"as an AI|I cannot|I'm sorry", re.IGNORECASE)
        per_row: list[dict[str, Any]] = []
        degenerate_rows: list[int] = []
        for generated, score in zip(
            generated_rows,
            ar_scores["per_row_scores"],
        ):
            reasons: list[str] = []
            if not generated["explanation"].strip():
                reasons.append("empty")
            if "㈜" in generated["full_response"] or "㈜" in generated["explanation"]:
                reasons.append("marker")
            if refusal_re.search(generated["explanation"]):
                reasons.append("refusal")
            if not 60 <= int(generated["n_tokens"]) <= 320:
                reasons.append("length_outside_60_320")
            if reasons:
                degenerate_rows.append(int(generated["row_index"]))
            per_row.append(
                {
                    "row_index": generated["row_index"],
                    "fixture_index": generated["fixture_index"],
                    "repeat_index": generated["repeat_index"],
                    "seed": generated["seed"],
                    "batch_size": generated["batch_size"],
                    "n_tokens": generated["n_tokens"],
                    "mse": score["mse"],
                    "fve_against_all_64_baseline": score[
                        "fve_against_all_64_baseline"
                    ],
                    "degenerate_reasons": reasons,
                    "full_response": generated["full_response"],
                    "explanation": generated["explanation"],
                    "token_ids": generated["token_ids"],
                }
            )

        sampled_fve = float(ar_scores["sampled_fve"])
        fve_pass = abs(sampled_fve - 0.782) <= 0.05
        no_degenerate_rows = not degenerate_rows
        result = {
            "status": "passed" if fve_pass and no_degenerate_rows else "failed_gate",
            "created_at_unix": time.time(),
            "elapsed_seconds": round(time.time() - started, 1),
            "fixture_indices": [int(row["fixture_index"]) for row in smoke_rows],
            "prompt_length_gate": {
                "lengths": prompt_lengths,
                "min": min(prompt_lengths),
                "max": max(prompt_lengths),
                "spread": max(prompt_lengths) - min(prompt_lengths),
                "uniform": prompt_length_uniform,
                "marker_positions": prompt_positions,
            },
            "generation": {
                "total_rows": len(generated_rows),
                "explanations_per_fixture": 2,
                "batch_size": 8,
                "temperature": 1.0,
                "top_p": 1.0,
                "max_new_tokens": MAX_NEW_TOKENS,
                "seeds": seeds_logged,
                "marker_position_log": position_logs,
            },
            "mse_scale": ar_scores["mse_scale"],
            "baseline_mse_all_64": ar_scores["baseline_mse_all_64"],
            "mean_mse_scored_sample": ar_scores["mean_mse_scored_sample"],
            "sampled_fve": sampled_fve,
            "target_fve": 0.782,
            "fve_tolerance": 0.05,
            "fve_gate_pass": fve_pass,
            "degenerate_rows": degenerate_rows,
            "zero_degenerate_rows": no_degenerate_rows,
            "selected_batch_size": 8 if fve_pass and no_degenerate_rows else 1,
            "per_row": per_row,
        }
    except Exception as exc:
        result = {
            "status": "error",
            "created_at_unix": time.time(),
            "elapsed_seconds": round(time.time() - started, 1),
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        actor = None
        gc.collect()
        try:
            torch.cuda.empty_cache()
        except Exception:
            pass
        result["resource_metrics"] = sampler.stop()
        try:
            _atomic_json(Path(FVE_RESULT_REMOTE_PATH), result)
            artifact_volume.commit()
        except Exception as exc:
            result["artifact_write_error"] = f"{type(exc).__name__}: {exc}"
    return result


def _shard_gate(
    rows: list[dict[str, Any]],
    manifest_rows: list[dict[str, Any]],
    smoke_mean_tokens: float,
    marker: str,
    *,
    expected_rows: int = SHARD_ROWS,
) -> dict[str, Any]:
    expected_keys = {
        (
            str(row["context_id"]),
            int(row["position_offset"]),
            int(row["sample_idx"]),
        )
        for row in manifest_rows
    }
    actual_keys = {
        (
            str(row["context_id"]),
            int(row["position_offset"]),
            int(row["sample_idx"]),
        )
        for row in rows
    }
    empty_rows = [row["generation_index"] for row in rows if not row["text"].strip()]
    marker_rows = [
        row["generation_index"]
        for row in rows
        if marker in row["text"] or marker in row["full_response"]
    ]
    refusal_re = re.compile(r"as an AI|I cannot|I'm sorry", re.IGNORECASE)
    refusal_rows = [
        row["generation_index"]
        for row in rows
        if refusal_re.search(row["text"])
    ]
    lengths = [int(row["n_tokens"]) for row in rows]
    batch_sizes = sorted({int(row.get("batch_size", 1)) for row in rows})
    means: dict[str, float] = {}
    distribution_ok = True
    for stratum in ("A", "B", "C"):
        values = [
            int(row["n_tokens"])
            for row in rows
            if str(row["stratum"]) == stratum
        ]
        if not values:
            continue
        means[stratum] = float(statistics.mean(values))
        distribution_ok = distribution_ok and (
            smoke_mean_tokens / 2.0 <= means[stratum] <= smoke_mean_tokens * 2.0
        )
    gates = {
        f"exactly_{expected_rows}_rows": len(rows) == expected_rows,
        "manifest_joinable": actual_keys == expected_keys,
        "empty_or_degenerate_rate_lt_1_percent": len(empty_rows) / expected_rows < 0.01,
        "median_length_120_to_300": 120 <= statistics.median(lengths) <= 300
        if lengths
        else False,
        "no_marker_char": not marker_rows,
        "refusal_rate_lt_2_percent": len(refusal_rows) / expected_rows < 0.02,
        "stratum_mean_within_2x_smoke": distribution_ok,
        "batch_size_values_recorded": all(
            int(row.get("batch_size", 1)) in (1, 4, 8) for row in rows
        ),
    }
    return {
        "rows_total": len(rows),
        "smoke_mean_tokens": smoke_mean_tokens,
        "length_median": statistics.median(lengths) if lengths else None,
        "length_mean_by_stratum": means,
        "empty_or_degenerate_rows": empty_rows,
        "marker_rows": marker_rows,
        "refusal_rows": refusal_rows,
        "batch_size_values": batch_sizes,
        "gates": gates,
        "all_gates_pass": all(gates.values()),
    }


def _write_parquet_atomic(output_path: Path, rows: list[dict[str, Any]]) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(str(output_path) + ".tmp")
    schema = pa.schema(
        [
            ("generation_index", pa.int32()),
            ("shard_index", pa.int32()),
            ("context_id", pa.string()),
            ("stratum", pa.string()),
            ("position_offset", pa.int32()),
            ("sample_idx", pa.int32()),
            ("activation_shard", pa.int32()),
            ("seed", pa.int64()),
            ("text", pa.string()),
            ("full_response", pa.string()),
            ("n_tokens", pa.int32()),
            ("batch_size", pa.int32()),
        ]
    )
    stored_rows = []
    for row in rows:
        stored_row = {
            key: value for key, value in row.items() if key != "generated_token_ids"
        }
        stored_row.setdefault("batch_size", 1)
        stored_rows.append(stored_row)
    pq.write_table(pa.Table.from_pylist(stored_rows, schema=schema), temporary)
    os.replace(temporary, output_path)
    artifact_volume.commit()


def _write_shard(shard_index: int, rows: list[dict[str, Any]]) -> None:
    output_path = Path(EXPLANATION_DIR) / f"shard_{shard_index:03d}.parquet"
    _write_parquet_atomic(output_path, rows)


def _run_shard(
    shard_index: int,
    manifest_rows: list[dict[str, Any]],
    *,
    qualify: bool,
    default_batch_size: int,
) -> dict[str, Any]:
    import gc

    _assert_remote_preflight()
    artifact_volume.reload()
    output_path = Path(EXPLANATION_DIR) / f"shard_{shard_index:03d}.parquet"
    if output_path.exists():
        import pyarrow.parquet as pq

        existing_rows = pq.read_table(output_path).to_pylist()
        qualification = None
        qualification_path = Path(QUALIFICATION_PATH)
        if qualification_path.exists():
            qualification = json.loads(qualification_path.read_text(encoding="utf-8"))
        return {
            "shard_index": shard_index,
            "skipped": True,
            "rows_total": len(existing_rows),
            "batch_size": (
                int(qualification["batch_size"]) if qualification else default_batch_size
            ),
            "qualification": qualification,
        }

    started = time.time()
    actor, tokenizer, cfg, device, vectors_ref, fixture_rows = _load_actor()
    qualification = None
    batch_size = default_batch_size
    if qualify:
        qualification = _qualification(
            actor, tokenizer, cfg, device, vectors_ref, fixture_rows
        )
        batch_size = int(qualification["batch_size"])
        qualification_path = Path(QUALIFICATION_PATH)
        qualification_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_json(qualification_path, qualification)
        artifact_volume.commit()

    activations = _load_activation_vectors(manifest_rows)
    rows = _generate_in_batches(
        actor,
        tokenizer,
        cfg,
        device,
        vectors_ref,
        manifest_rows,
        activations,
        batch_size,
    )
    _write_shard(shard_index, rows)
    shard_gate = _shard_gate(
        rows,
        manifest_rows,
        _smoke_mean_tokens(tokenizer),
        cfg.injection_char,
    )
    del actor
    gc.collect()
    import torch

    torch.cuda.empty_cache()
    return {
        "shard_index": shard_index,
        "skipped": False,
        "rows_total": len(rows),
        "batch_size": batch_size,
        "qualification": qualification,
        "shard_gate": shard_gate,
        "elapsed_seconds": round(time.time() - started, 1),
    }


def _run_optimized_shard_body(
    shard_index: int,
    manifest_rows: list[dict[str, Any]],
    batch_size: int,
) -> dict[str, Any]:
    import gc
    import pyarrow.parquet as pq
    import torch

    if len(manifest_rows) != OPTIMIZED_SHARD_ROWS:
        raise RuntimeError(
            f"optimized shard {shard_index} has {len(manifest_rows)} rows; "
            f"expected {OPTIMIZED_SHARD_ROWS}"
        )
    if batch_size not in (1, 4, 8):
        raise RuntimeError(f"unexpected selected batch size {batch_size}")

    _assert_remote_preflight()
    artifact_volume.reload()
    output_path = Path(OPTIMIZED_EXPLANATION_DIR) / (
        f"shard_{shard_index:03d}.parquet"
    )
    gate_path = Path(OPTIMIZED_GATE_DIR) / f"shard_{shard_index:03d}.json"
    if output_path.exists():
        existing_rows = pq.read_table(output_path).to_pylist()
        if not gate_path.exists():
            raise RuntimeError(
                f"optimized shard {shard_index} output exists without gate evidence"
            )
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        if len(existing_rows) != OPTIMIZED_SHARD_ROWS:
            raise RuntimeError(
                f"optimized shard {shard_index} existing output has "
                f"{len(existing_rows)} rows"
            )
        if gate.get("all_gates_pass") is not True:
            raise RuntimeError(
                f"optimized shard {shard_index} existing gate is not green"
            )
        return {
            "shard_index": shard_index,
            "skipped": True,
            "rows_total": len(existing_rows),
            "batch_size": batch_size,
            "checkpoint_rows": CHECKPOINT_ROWS,
            "shard_gate": gate,
        }

    started = time.time()
    actor, tokenizer, cfg, device, vectors_ref, _ = _load_actor()
    activations = _load_activation_vectors(manifest_rows)
    smoke_mean_tokens = _smoke_mean_tokens(tokenizer)
    generated_rows: list[dict[str, Any]] = []
    checkpoint_paths: list[str] = []

    for start in range(0, OPTIMIZED_SHARD_ROWS, CHECKPOINT_ROWS):
        chunk_rows = manifest_rows[start : start + CHECKPOINT_ROWS]
        part_index = start // CHECKPOINT_ROWS
        checkpoint_path = Path(OPTIMIZED_EXPLANATION_DIR) / (
            f"shard_{shard_index:03d}.part_{part_index:03d}.parquet"
        )
        if checkpoint_path.exists():
            rows = pq.read_table(checkpoint_path).to_pylist()
            expected_generation_indices = {
                int(row["generation_index"]) for row in chunk_rows
            }
            actual_generation_indices = {
                int(row["generation_index"]) for row in rows
            }
            if len(rows) != len(chunk_rows) or (
                actual_generation_indices != expected_generation_indices
            ):
                raise RuntimeError(
                    f"optimized shard {shard_index} checkpoint {part_index} "
                    "does not match its manifest chunk"
                )
        else:
            rows = _generate_in_batches(
                actor,
                tokenizer,
                cfg,
                device,
                vectors_ref,
                chunk_rows,
                activations,
                batch_size,
                expected_rows=len(chunk_rows),
            )
            _write_parquet_atomic(checkpoint_path, rows)
        generated_rows.extend(rows)
        checkpoint_paths.append(str(checkpoint_path))

    shard_gate = _shard_gate(
        generated_rows,
        manifest_rows,
        smoke_mean_tokens,
        cfg.injection_char,
        expected_rows=OPTIMIZED_SHARD_ROWS,
    )
    _atomic_json(gate_path, shard_gate)
    artifact_volume.commit()
    result = {
        "shard_index": shard_index,
        "skipped": False,
        "rows_total": len(generated_rows),
        "batch_size": batch_size,
        "checkpoint_rows": CHECKPOINT_ROWS,
        "checkpoint_paths": checkpoint_paths,
        "shard_gate": shard_gate,
        "elapsed_seconds": round(time.time() - started, 1),
    }
    if shard_gate["all_gates_pass"]:
        _write_parquet_atomic(output_path, generated_rows)
    del actor
    gc.collect()
    torch.cuda.empty_cache()
    return result


def _run_optimized_shard(
    shard_index: int,
    manifest_rows: list[dict[str, Any]],
    batch_size: int,
) -> dict[str, Any]:
    sampler = _WorkerResourceSampler(f"optimized_shard_{shard_index:03d}")
    sampler.start()
    result: dict[str, Any] | None = None
    try:
        result = _run_optimized_shard_body(
            shard_index,
            manifest_rows,
            batch_size,
        )
        return result
    finally:
        metrics = sampler.stop()
        if result is not None:
            result["resource_metrics"] = metrics


@app.function(**GPU_FUNCTION_KWARGS_BATCH4)
def generate_shard_batch4(
    shard_index: int,
    manifest_rows: list[dict[str, Any]],
    qualify: bool = False,
) -> dict[str, Any]:
    return _run_shard(
        shard_index,
        manifest_rows,
        qualify=qualify,
        default_batch_size=4,
    )


@app.function(**GPU_FUNCTION_KWARGS_BATCH1)
def generate_shard_batch1(
    shard_index: int,
    manifest_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    return _run_shard(
        shard_index,
        manifest_rows,
        qualify=False,
        default_batch_size=1,
    )


@app.function(**GPU_FUNCTION_KWARGS_BATCH4)
def generate_optimized_shard(
    shard_index: int,
    manifest_rows: list[dict[str, Any]],
    batch_size: int,
) -> dict[str, Any]:
    return _run_optimized_shard(shard_index, manifest_rows, batch_size)


def _selected_optionc_batch_size() -> int:
    _assert_local_preflight()
    if not FVE_RESULT_PATH.exists():
        raise RuntimeError(
            f"missing FVE equivalence evidence {FVE_RESULT_PATH}"
        )
    fve = json.loads(
        FVE_RESULT_PATH.read_text(encoding="utf-8")
    )
    if fve.get("status") not in {"passed", "failed_gate"}:
        raise RuntimeError("FVE equivalence did not produce a usable gate")
    selected = int(fve.get("selected_batch_size", 1))
    if selected not in (1, 8):
        raise RuntimeError(f"unexpected FVE selected batch size {selected}")
    return selected


def _write_rightsizing_from_fve(fve: dict[str, Any]) -> dict[str, Any]:
    before = {
        "cpu_cores": float(GPU_FUNCTION_KWARGS_BATCH4["cpu"]),
        "memory_mb": int(GPU_FUNCTION_KWARGS_BATCH4["memory"]),
        "source": "GPU_FUNCTION_KWARGS_BATCH4",
    }
    metrics = fve.get("resource_metrics") or {}
    peak_cpu = metrics.get("peak_cpu_cores")
    peak_rss_mb = metrics.get("peak_rss_mb")
    usable = (
        metrics.get("measurement_status") == "passed"
        and isinstance(peak_cpu, (int, float))
        and float(peak_cpu) > 0
        and isinstance(peak_rss_mb, (int, float))
        and float(peak_rss_mb) > 0
    )
    anomalies: list[str] = []
    if usable:
        after = {
            "cpu_cores": math.ceil(float(peak_cpu) * 1.25 * 100) / 100,
            "memory_mb": math.ceil(float(peak_rss_mb) * 1.25),
            "source": "first instrumented FVE worker peak plus 25 percent",
        }
        status = "passed"
        GPU_FUNCTION_KWARGS_BATCH4["cpu"] = after["cpu_cores"]
        GPU_FUNCTION_KWARGS_BATCH4["memory"] = after["memory_mb"]
        GPU_FUNCTION_KWARGS_BATCH1["cpu"] = after["cpu_cores"]
        GPU_FUNCTION_KWARGS_BATCH1["memory"] = after["memory_mb"]
    else:
        after = dict(before)
        status = "instrumentation_failed_defaults"
        anomalies.append(
            "FVE worker telemetry did not provide positive CPU and RSS peaks; "
            "current reservations were retained as required by the non-blocking rule."
        )
        if metrics.get("errors"):
            anomalies.extend(str(error) for error in metrics["errors"])

    evidence = {
        "status": status,
        "created_at_unix": time.time(),
        "directive": "AMENDMENT 2026-08-16b container right-sizing",
        "non_blocking": True,
        "fve_result": str(FVE_RESULT_PATH),
        "resource_metrics": metrics,
        "reservations_before": before,
        "reservations_after": after,
        "applied_to": [
            "generate_optimized_shard",
            "generate_shard_batch4",
            "generate_shard_batch1",
        ],
        "anomalies": anomalies,
    }
    _atomic_json(RIGHTSIZING_RESULT_PATH, evidence)
    return evidence


def _configured_optimized_worker() -> Any:
    if not RIGHTSIZING_RESULT_PATH.exists():
        raise RuntimeError(
            f"missing required right-sizing evidence {RIGHTSIZING_RESULT_PATH}"
        )
    rightsizing = json.loads(
        RIGHTSIZING_RESULT_PATH.read_text(encoding="utf-8")
    )
    if rightsizing.get("status") not in {
        "passed",
        "instrumentation_failed_defaults",
    }:
        raise RuntimeError("right-sizing evidence is not usable")
    if rightsizing.get("status") == "passed":
        reservations = rightsizing["reservations_after"]
        return generate_optimized_shard.with_options(
            cpu=float(reservations["cpu_cores"]),
            memory=int(reservations["memory_mb"]),
        )
    return generate_optimized_shard


def _optimized_volume_inventory() -> dict[str, Any]:
    listing = _volume_listing(
        "nla-verifier-artifacts",
        "phase2b_optimized/explanations",
    )
    names = {
        Path(str(item.get("filename", item.get("Filename", "")))).name
        for item in listing
    }
    shards: dict[str, Any] = {}
    rows_total = 0
    for shard_index in range(OPTIMIZED_SHARD_COUNT):
        final_name = f"shard_{shard_index:03d}.parquet"
        if final_name in names:
            shard_rows = OPTIMIZED_SHARD_ROWS
            files = [final_name]
        else:
            files = sorted(
                name
                for name in names
                if re.fullmatch(
                    rf"shard_{shard_index:03d}\.part_\d{{3}}\.parquet",
                    name,
                )
            )
            shard_rows = len(files) * CHECKPOINT_ROWS
        if shard_rows > OPTIMIZED_SHARD_ROWS:
            raise RuntimeError(
                f"Volume inventory reports too many rows for shard {shard_index}: "
                f"{shard_rows}"
            )
        shards[str(shard_index)] = {
            "rows": shard_rows,
            "files": files,
            "complete": shard_rows == OPTIMIZED_SHARD_ROWS,
        }
        rows_total += shard_rows
    if rows_total > MANIFEST_ROWS:
        raise RuntimeError(
            f"Volume inventory reports {rows_total} rows above {MANIFEST_ROWS}"
        )
    return {
        "rows_total": rows_total,
        "rows_remaining": MANIFEST_ROWS - rows_total,
        "shards": shards,
    }


def _local_green_optimized_shards(inventory: dict[str, Any]) -> list[int]:
    """Return complete shards with locally recorded green gate evidence."""

    completed: list[int] = []
    for shard_key, shard in inventory["shards"].items():
        if not shard.get("complete"):
            continue
        gate_path = ROOT / "results" / (
            f"phase2b_optimized_shard_{int(shard_key):03d}_gate.json"
        )
        if not gate_path.exists():
            continue
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        if gate.get("all_gates_pass") is True:
            completed.append(int(shard_key))
    return completed


def _write_batched_projection(
    benchmark_result: dict[str, Any],
    billing_before: dict[str, Any],
    billing_after: dict[str, Any],
    inventory_before: dict[str, Any],
) -> dict[str, Any]:
    from decimal import Decimal

    try:
        before = _billing_reported_total(billing_before)
        after = _billing_reported_total(billing_after)
        workspace_delta = after - before
        if workspace_delta <= 0:
            raise RuntimeError(
                f"first batched shard workspace billed delta is not positive: "
                f"{workspace_delta}"
            )
        measured_rows = Decimal(OPTIMIZED_SHARD_ROWS)
        unit_cost_per_row = workspace_delta / measured_rows
        inventory_after = _optimized_volume_inventory()
        remaining_rows = Decimal(inventory_after["rows_remaining"])
        projected_remaining = unit_cost_per_row * remaining_rows
        status = (
            "proceed"
            if projected_remaining <= Decimal(str(PHASE2B_COST_CAP))
            else "halted_above_120"
        )
        evidence = {
            "status": status,
            "created_at_unix": time.time(),
            "cost_cap": f"{PHASE2B_COST_CAP:.8f}",
            "selected_batch_size": 8,
            "projection_basis": (
                "first completed batched shard, full 300-row shard-boundary "
                "workspace billed delta"
            ),
            "benchmark": {
                "shard_index": 0,
                "rows": OPTIMIZED_SHARD_ROWS,
                "result": benchmark_result,
                "inventory_before": inventory_before,
                "inventory_after": inventory_after,
                "workspace_billed_before": str(before),
                "workspace_billed_after": str(after),
                "workspace_billed_delta": str(workspace_delta),
                "unit_cost_per_row": str(unit_cost_per_row),
                "unit_cost_per_300_rows": str(workspace_delta),
                "billing_before": billing_before,
                "billing_after": billing_after,
            },
            "remaining_generation_rows": int(remaining_rows),
            "total_generation_rows": MANIFEST_ROWS,
            "canonical_unit_cost_per_row": str(unit_cost_per_row),
            "canonical_unit_cost_per_300_rows": str(workspace_delta),
            "projected_remaining_cost": str(projected_remaining),
            "projection_within_cap": projected_remaining
            <= Decimal(str(PHASE2B_COST_CAP)),
            "billing_basis": BILLING_BASIS,
            "relative_escalation_threshold_per_300_rows": str(
                workspace_delta * Decimal("1.40")
            ),
            "absolute_escalation_floor_per_300_rows": ESCALATION_FLOOR_PER_300,
            "escalation_threshold_per_300_rows": str(
                _corrected_escalation_threshold(workspace_delta)
            ),
            "cold_start_accounting": (
                "The measured first completed batched shard includes its cold start; "
                "no unmeasured allowance was added."
            ),
            "anomalies": [],
        }
    except Exception as exc:
        evidence = {
            "status": "error",
            "created_at_unix": time.time(),
            "cost_cap": f"{PHASE2B_COST_CAP:.8f}",
            "selected_batch_size": 8,
            "benchmark": benchmark_result,
            "inventory_before": inventory_before,
            "billing_before": billing_before,
            "billing_after": billing_after,
            "error": f"{type(exc).__name__}: {exc}",
        }
    _atomic_json(PROJECTION_RESULT_PATH, evidence)
    return evidence


def _write_batch1_projection() -> dict[str, Any]:
    from decimal import Decimal

    try:
        source_path = ROOT / "results" / "phase2b_rebaseline_projection.json"
        source = json.loads(source_path.read_text(encoding="utf-8"))
        completed_shard_cost = Decimal(str(source["completed_shard_cost"]))
        completed_shard_rows = Decimal(str(source["completed_shard_rows"]))
        inventory = _optimized_volume_inventory()
        remaining_rows = Decimal(str(inventory["rows_remaining"]))
        unit_cost_per_row = completed_shard_cost / completed_shard_rows
        projected_remaining = unit_cost_per_row * remaining_rows
        evidence = {
            "status": (
                "proceed"
                if projected_remaining <= Decimal(str(PHASE2B_COST_CAP))
                else "halted_above_120"
            ),
            "created_at_unix": time.time(),
            "cost_cap": f"{PHASE2B_COST_CAP:.8f}",
            "selected_batch_size": 1,
            "projection_basis": (
                "completed shard-2 batch-1 benchmark from the amended run, "
                "full shard-boundary workspace billed cost"
            ),
            "canonical_source": str(source_path),
            "canonical_completed_shard_cost": str(completed_shard_cost),
            "canonical_completed_shard_rows": int(completed_shard_rows),
            "canonical_unit_cost_per_row": str(unit_cost_per_row),
            "inventory": inventory,
            "remaining_generation_rows": int(remaining_rows),
            "total_generation_rows": MANIFEST_ROWS,
            "projected_remaining_cost": str(projected_remaining),
            "projection_within_cap": projected_remaining
            <= Decimal(str(PHASE2B_COST_CAP)),
            "escalation_threshold_per_300_rows": str(completed_shard_cost * Decimal("1.40")),
            "anomalies": [
                "The FVE gate selected batch=1, so the existing completed batch-1 shard-2 benchmark is retained as the canonical cost."
            ],
        }
    except Exception as exc:
        evidence = {
            "status": "error",
            "created_at_unix": time.time(),
            "cost_cap": f"{PHASE2B_COST_CAP:.8f}",
            "selected_batch_size": 1,
            "error": f"{type(exc).__name__}: {exc}",
        }
    _atomic_json(PROJECTION_RESULT_PATH, evidence)
    return evidence


def _run_projection() -> dict[str, Any]:
    from decimal import Decimal

    _assert_predecessor_evidence()
    preflight = _assert_local_preflight()
    selected_batch_size = _selected_optionc_batch_size()
    if not OPTIMIZED_SHARD2_GATE_PATH.exists():
        raise RuntimeError("shard 2 gate evidence is required for G6 projection")
    shard2_gate = json.loads(OPTIMIZED_SHARD2_GATE_PATH.read_text(encoding="utf-8"))
    if shard2_gate.get("all_gates_pass") is not True:
        raise RuntimeError("shard 2 gate is not green; projection is forbidden")

    try:
        guard = json.loads(
            (ROOT / "results" / "phase2b_rebaseline_guard.json").read_text(
                encoding="utf-8"
            )
        )
        before = Decimal(
            str(guard["workspace_billing_summary_at_check"]["billed_cost"])
        )
        billing = preflight["billing_snapshot"]
        after = _billing_reported_total(billing)
        workspace_delta = after - before
        measured_rows = Decimal(OPTIMIZED_SHARD_ROWS)
        if workspace_delta <= 0:
            raise RuntimeError(
                f"workspace billed delta is not positive: {workspace_delta}"
            )
        unit_cost_per_row = workspace_delta / measured_rows
        remaining_indices = [
            index for index in range(OPTIMIZED_SHARD_COUNT) if index != 2
        ]
        remaining_rows = measured_rows * Decimal(len(remaining_indices))
        projected_remaining = unit_cost_per_row * remaining_rows
        app_items = [
            item
            for item in billing.get("app_line_items", [])
            if item.get("description") == APP_NAME
        ]
        evidence = {
            "status": (
                "proceed"
                if projected_remaining <= Decimal(str(PHASE2B_COST_CAP))
                else "halted_above_120"
            ),
            "created_at_unix": time.time(),
            "cost_cap": f"{PHASE2B_COST_CAP:.8f}",
            "selected_batch_size": selected_batch_size,
            "qualification_result": str(OPTIONC_QUALIFICATION_RESULT_PATH),
            "rebaseline": {
                "shard_index": 2,
                "rows": int(measured_rows),
                "workspace_billed_before": str(before),
                "workspace_billed_after": str(after),
                "workspace_billed_delta": str(workspace_delta),
                "unit_cost_per_row": str(unit_cost_per_row),
                "unit_cost_per_300_rows": str(workspace_delta),
                "source_guard": str(ROOT / "results" / "phase2b_rebaseline_guard.json"),
                "source_preflight": str(OPTIONC_PREFLIGHT_PATH),
            },
            "regenerate_shards": [0, 1],
            "kept_shard": 2,
            "remaining_shard_indices": remaining_indices,
            "remaining_generation_rows": int(remaining_rows),
            "total_generation_rows": MANIFEST_ROWS,
            "projected_remaining_cost": str(projected_remaining),
            "projection_within_cap": projected_remaining
            <= Decimal(str(PHASE2B_COST_CAP)),
            "workspace_billing_snapshot": billing,
            "phase2b_app_line_items_at_projection": app_items,
            "anomalies": [
                "The pre-retry workspace billed baseline is the exact snapshot recorded in phase2b_rebaseline_guard.json; no paid NLA app appeared between that check and the preflight snapshot."
            ],
        }
    except Exception as exc:
        evidence = {
            "status": "error",
            "created_at_unix": time.time(),
            "cost_cap": f"{PHASE2B_COST_CAP:.8f}",
            "error": f"{type(exc).__name__}: {exc}",
        }
        _atomic_json(PROJECTION_RESULT_PATH, evidence)
        raise

    _atomic_json(PROJECTION_RESULT_PATH, evidence)
    if evidence["status"] != "proceed":
        raise RuntimeError(
            "G6 projection exceeds the authorized $120 cap; see "
            f"{PROJECTION_RESULT_PATH}"
        )
    return evidence


def _write_optimized_shard_evidence(result: dict[str, Any]) -> None:
    shard_index = int(result["shard_index"])
    _atomic_json(
        ROOT / "results" / f"phase2b_optimized_shard_{shard_index:03d}.json",
        result,
    )
    if result.get("shard_gate") is not None:
        _atomic_json(
            ROOT
            / "results"
            / f"phase2b_optimized_shard_{shard_index:03d}_gate.json",
            result["shard_gate"],
        )


def _write_fanout_failure(
    selected_batch_size: int,
    error: str,
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "status": "error",
        "created_at_unix": time.time(),
        "selected_batch_size": selected_batch_size,
        "error": error,
    }
    if extra:
        evidence.update(extra)
    _atomic_json(FANOUT_RESULT_PATH, evidence)
    return evidence


def _run_optimized_fanout() -> dict[str, Any]:
    from decimal import Decimal

    _assert_predecessor_evidence()
    _assert_local_preflight()
    selected_batch_size = _selected_optionc_batch_size()
    rightsizing = json.loads(
        RIGHTSIZING_RESULT_PATH.read_text(encoding="utf-8")
    )
    if rightsizing.get("status") not in {
        "passed",
        "instrumentation_failed_defaults",
    }:
        raise RuntimeError("right-sizing evidence is not usable for fan-out")

    optimized_rows = _ensure_optimized_manifest()
    optimized_grouped = _group_manifest(
        optimized_rows,
        shard_rows=OPTIMIZED_SHARD_ROWS,
        shard_count=OPTIMIZED_SHARD_COUNT,
    )
    if not OPTIMIZED_SHARD2_RESULT_PATH.exists():
        raise RuntimeError("valid shard-2 evidence is required before fan-out")
    shard2 = json.loads(OPTIMIZED_SHARD2_RESULT_PATH.read_text(encoding="utf-8"))
    if not shard2.get("shard_gate", {}).get("all_gates_pass"):
        raise RuntimeError("optimized shard 2 gate is not green")

    worker = _configured_optimized_worker()
    benchmark: dict[str, Any] | None = None
    projection: dict[str, Any]
    completed_results: list[dict[str, Any]] = []
    prior_waves: list[dict[str, Any]] = []
    wave_start_index = 1
    try:
        if selected_batch_size == 8:
            inventory_before = _optimized_volume_inventory()
            existing_projection = None
            existing_benchmark_path = (
                ROOT / "results" / "phase2b_optimized_shard_000.json"
            )
            if PROJECTION_RESULT_PATH.exists() and existing_benchmark_path.exists():
                candidate_projection = json.loads(
                    PROJECTION_RESULT_PATH.read_text(encoding="utf-8")
                )
                candidate_benchmark = json.loads(
                    existing_benchmark_path.read_text(encoding="utf-8")
                )
                candidate_result = candidate_projection.get("benchmark", {}).get(
                    "result", {}
                )
                candidate_wave_path = (
                    ROOT / "results" / "phase2b_optimized_wave_01.json"
                )
                candidate_wave = (
                    json.loads(candidate_wave_path.read_text(encoding="utf-8"))
                    if candidate_wave_path.exists()
                    else {}
                )
                candidate_projection_usable = candidate_projection.get("status") == (
                    "proceed"
                ) or (
                    candidate_projection.get("status") == "halted_cost_escalation"
                    and candidate_wave.get("wave_index") == 1
                    and candidate_wave.get("gates_pass") is True
                )
                if (
                    candidate_projection_usable
                    and candidate_projection.get("selected_batch_size") == 8
                    and candidate_projection.get("canonical_unit_cost_per_row")
                    and candidate_projection.get("canonical_unit_cost_per_300_rows")
                    and candidate_result.get("shard_index") == 0
                    and candidate_result.get("rows_total") == OPTIMIZED_SHARD_ROWS
                    and candidate_result.get("shard_gate", {}).get("all_gates_pass")
                    is True
                    and candidate_benchmark.get("shard_index") == 0
                    and candidate_benchmark.get("rows_total") == OPTIMIZED_SHARD_ROWS
                    and candidate_benchmark.get("shard_gate", {}).get(
                        "all_gates_pass"
                    )
                    is True
                ):
                    existing_projection = candidate_projection
                    benchmark = candidate_benchmark

            if existing_projection is not None:
                projection = existing_projection
                completed_results.append(benchmark)
                completed_shards = _local_green_optimized_shards(inventory_before)
                remaining_indices = [
                    index
                    for index in range(OPTIMIZED_SHARD_COUNT)
                    if index not in {0, 2} and index not in completed_shards
                ]
                if projection.get("status") == "halted_cost_escalation":
                    projection, corrected_wave, wave_start_index = (
                        _retroactively_clear_wave1(projection)
                    )
                    prior_waves.append(corrected_wave)
                    completed_results.extend(corrected_wave.get("results", []))
                elif (
                    ROOT / "results" / "phase2b_optimized_wave_01_corrected.json"
                ).exists():
                    corrected_wave = json.loads(
                        (
                            ROOT
                            / "results"
                            / "phase2b_optimized_wave_01_corrected.json"
                        ).read_text(encoding="utf-8")
                    )
                    prior_waves.append(corrected_wave)
                    completed_results.extend(corrected_wave.get("results", []))
                    wave_start_index = 2
            else:
                billing_before = _workspace_billing_snapshot()
                benchmark = worker.remote(0, optimized_grouped[0], 8)
                _write_optimized_shard_evidence(benchmark)
                completed_results.append(benchmark)
                billing_after = _workspace_billing_snapshot()
                if not (
                    benchmark.get("rows_total") == OPTIMIZED_SHARD_ROWS
                    and benchmark.get("shard_gate", {}).get("all_gates_pass") is True
                ):
                    projection = {
                        "status": "failed_gate",
                        "created_at_unix": time.time(),
                        "cost_cap": f"{PHASE2B_COST_CAP:.8f}",
                        "selected_batch_size": 8,
                        "benchmark": benchmark,
                        "billing_before": billing_before,
                        "billing_after": billing_after,
                        "error": "first batched shard gate failed",
                    }
                    _atomic_json(PROJECTION_RESULT_PATH, projection)
                    raise RuntimeError("first batched shard gate failed")
                projection = _write_batched_projection(
                    benchmark,
                    billing_before,
                    billing_after,
                    inventory_before,
                )
                remaining_indices = [
                    index
                    for index in range(OPTIMIZED_SHARD_COUNT)
                    if index not in {0, 2}
                ]
        else:
            projection = _write_batch1_projection()
            inventory = _optimized_volume_inventory()
            completed_shards = _local_green_optimized_shards(inventory)
            remaining_indices = [
                index
                for index in range(OPTIMIZED_SHARD_COUNT)
                if index != 2 and index not in completed_shards
            ]

        if projection.get("status") != "proceed":
            raise RuntimeError(
                "G6 projection did not clear the $120 cap; no new wave launched"
            )

        canonical_per_300 = Decimal(
            str(projection["canonical_unit_cost_per_300_rows"])
        )
        canonical_per_row = Decimal(
            str(projection["canonical_unit_cost_per_row"])
        )
        waves: list[dict[str, Any]] = list(prior_waves)
        for wave_index, start in enumerate(
            range(0, len(remaining_indices), 4),
            start=wave_start_index,
        ):
            wave_indices = remaining_indices[start : start + 4]
            wave_rows = [optimized_grouped[index] for index in wave_indices]
            billing_before = _workspace_billing_snapshot()
            try:
                wave_results = list(
                    worker.map(
                        wave_indices,
                        wave_rows,
                        [selected_batch_size] * len(wave_indices),
                    )
                )
            except Exception as exc:
                wave_error = _write_fanout_failure(
                    selected_batch_size,
                    f"{type(exc).__name__}: {exc}",
                    extra={
                        "completed_results": completed_results,
                        "wave_index": wave_index,
                        "wave_shards": wave_indices,
                    },
                )
                raise RuntimeError(json.dumps(wave_error)) from exc
            billing_after = _workspace_billing_snapshot()
            for result in wave_results:
                _write_optimized_shard_evidence(result)
            completed_results.extend(wave_results)
            expected_wave_rows = OPTIMIZED_SHARD_ROWS * len(wave_indices)
            actual_wave_rows = sum(
                int(result.get("rows_total", 0)) for result in wave_results
            )
            gates_pass = all(
                result.get("rows_total") == OPTIMIZED_SHARD_ROWS
                and result.get("shard_gate", {}).get("all_gates_pass") is True
                for result in wave_results
            )
            before = _billing_reported_total(billing_before)
            after = _billing_reported_total(billing_after)
            workspace_delta = after - before
            wave_cost_per_300 = (
                workspace_delta / Decimal(len(wave_indices))
                if wave_indices
                else Decimal("0")
            )
            cold_start_diagnostic = _cold_start_excluded_wave_diagnostic(
                wave_results,
                workspace_delta,
                actual_wave_rows,
            )
            inventory = _optimized_volume_inventory()
            remaining_rows = Decimal(str(inventory["rows_remaining"]))
            projected_remaining = canonical_per_row * remaining_rows
            relative_escalation_threshold = canonical_per_300 * Decimal("1.40")
            escalation_threshold = _corrected_escalation_threshold(canonical_per_300)
            cost_escalated = wave_cost_per_300 > escalation_threshold
            wave_evidence = {
                "status": (
                    "passed"
                    if gates_pass
                    and workspace_delta > 0
                    and not cost_escalated
                    and projected_remaining <= Decimal(str(PHASE2B_COST_CAP))
                    else "failed_gate"
                ),
                "created_at_unix": time.time(),
                "wave_index": wave_index,
                "shard_indices": wave_indices,
                "selected_batch_size": selected_batch_size,
                "expected_rows": expected_wave_rows,
                "actual_rows": actual_wave_rows,
                "gates_pass": gates_pass,
                "workspace_billed_before": str(before),
                "workspace_billed_after": str(after),
                "workspace_billed_delta": str(workspace_delta),
                "wave_cost_per_300_rows": str(wave_cost_per_300),
                "canonical_cost_per_300_rows": str(canonical_per_300),
                "billing_basis": BILLING_BASIS,
                "relative_escalation_threshold_per_300_rows": str(
                    relative_escalation_threshold
                ),
                "absolute_escalation_floor_per_300_rows": ESCALATION_FLOOR_PER_300,
                "escalation_threshold_per_300_rows": str(
                    escalation_threshold
                ),
                "cost_escalated": cost_escalated,
                "cold_start_excluded_diagnostic": cold_start_diagnostic,
                "inventory": inventory,
                "projected_remaining_cost": str(projected_remaining),
                "projection_within_cap": projected_remaining
                <= Decimal(str(PHASE2B_COST_CAP)),
                "billing_before": billing_before,
                "billing_after": billing_after,
                "results": wave_results,
            }
            wave_path = ROOT / "results" / f"phase2b_optimized_wave_{wave_index:02d}.json"
            _atomic_json(wave_path, wave_evidence)
            waves.append(wave_evidence)
            projection.setdefault("completed_boundaries", []).append(
                {
                    "boundary": f"wave_{wave_index:02d}",
                    "shard_indices": wave_indices,
                    "workspace_billed_delta": str(workspace_delta),
                    "wave_cost_per_300_rows": str(wave_cost_per_300),
                    "billing_basis": BILLING_BASIS,
                    "cold_start_excluded_diagnostic": cold_start_diagnostic,
                    "inventory": inventory,
                    "projected_remaining_cost": str(projected_remaining),
                }
            )
            projection["latest_inventory"] = inventory
            projection["latest_projected_remaining_cost"] = str(projected_remaining)
            projection["billing_basis"] = BILLING_BASIS
            projection["escalation_rule"] = (
                "max(canonical cost x 1.4, $3.00) per 300 rows"
            )
            if not gates_pass:
                projection["status"] = "failed_gate"
            elif workspace_delta <= 0:
                projection["status"] = "error"
                projection["error"] = "wave workspace billed delta was not positive"
            elif cost_escalated:
                projection["status"] = "halted_cost_escalation"
                projection["error"] = (
                    "completed wave cost exceeded max(canonical cost plus 40 percent, $3.00)"
                )
            elif projected_remaining > Decimal(str(PHASE2B_COST_CAP)):
                projection["status"] = "halted_above_120"
                projection["error"] = "completed-boundary projection exceeded $120"
            _atomic_json(PROJECTION_RESULT_PATH, projection)
            if projection.get("status") != "proceed":
                raise RuntimeError(
                    f"Phase 2b stopped at wave {wave_index}: {projection.get('error', projection.get('status'))}"
                )

        final_inventory = _optimized_volume_inventory()
        if final_inventory["rows_total"] != MANIFEST_ROWS:
            raise RuntimeError(
                f"fan-out ended with {final_inventory['rows_total']} persisted rows, "
                f"expected {MANIFEST_ROWS}"
            )
        fanout_evidence = {
            "status": "passed",
            "created_at_unix": time.time(),
            "selected_batch_size": selected_batch_size,
            "billing_basis": BILLING_BASIS,
            "escalation_rule": "max(canonical cost x 1.4, $3.00) per 300 rows",
            "max_containers": 4,
            "shard_rows": OPTIMIZED_SHARD_ROWS,
            "checkpoint_rows": CHECKPOINT_ROWS,
            "fve_result": str(FVE_RESULT_PATH),
            "right_sizing": str(RIGHTSIZING_RESULT_PATH),
            "kept_shard_2": shard2,
            "benchmark": benchmark,
            "shards_completed_this_run": completed_results,
            "waves": waves,
            "final_inventory": final_inventory,
            "projection": projection,
        }
        _atomic_json(FANOUT_RESULT_PATH, fanout_evidence)
        return fanout_evidence
    except Exception as exc:
        _write_fanout_failure(
            selected_batch_size,
            f"{type(exc).__name__}: {exc}",
            extra={
                "benchmark": benchmark,
                "completed_results": completed_results,
                "projection": projection if "projection" in locals() else None,
            },
        )
        raise


def _download_volume_directory(remote_path: str, local_path: Path) -> None:
    modal_cli = shutil.which("modal")
    if modal_cli is None:
        raise RuntimeError("modal CLI is not available for merge download")
    local_path.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [
            modal_cli,
            "volume",
            "get",
            "nla-verifier-artifacts",
            remote_path,
            str(local_path.parent),
            "--force",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"download failed for {remote_path}: {completed.stderr.strip()}"
        )


def _write_local_parquet_atomic(path: Path, rows: list[dict[str, Any]]) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(str(path) + ".tmp")
    schema = pa.schema(
        [
            ("generation_index", pa.int32()),
            ("shard_index", pa.int32()),
            ("context_id", pa.string()),
            ("stratum", pa.string()),
            ("position_offset", pa.int32()),
            ("sample_idx", pa.int32()),
            ("activation_shard", pa.int32()),
            ("seed", pa.int64()),
            ("text", pa.string()),
            ("full_response", pa.string()),
            ("n_tokens", pa.int32()),
            ("batch_size", pa.int32()),
        ]
    )
    normalized_rows = []
    for row in rows:
        normalized = dict(row)
        normalized.setdefault("batch_size", 1)
        normalized_rows.append(normalized)
    pq.write_table(pa.Table.from_pylist(normalized_rows, schema=schema), temporary)
    os.replace(temporary, path)


def _run_merge() -> dict[str, Any]:
    import random

    import pyarrow.parquet as pq

    _assert_predecessor_evidence()
    _assert_local_preflight()
    if not PROJECTION_RESULT_PATH.exists():
        raise RuntimeError("missing final projection evidence")
    projection = json.loads(PROJECTION_RESULT_PATH.read_text(encoding="utf-8"))
    if projection.get("status") != "proceed":
        raise RuntimeError("projection gate is not green; merge is forbidden")
    if not FANOUT_RESULT_PATH.exists():
        raise RuntimeError("missing fan-out evidence")
    fanout = json.loads(FANOUT_RESULT_PATH.read_text(encoding="utf-8"))
    if fanout.get("status") != "passed":
        raise RuntimeError("fan-out evidence is not green; merge is forbidden")

    staging_root = ROOT / "results" / "phase2b_optimized_download"
    try:
        _download_volume_directory(
            "phase2b_optimized/explanations",
            staging_root / "explanations",
        )
        _download_volume_directory(
            "phase2b_optimized/gates",
            staging_root / "gates",
        )
        expected_manifest = _expected_optimized_manifest()
        expected_by_key = {
            (
                str(row["context_id"]),
                int(row["position_offset"]),
                int(row["sample_idx"]),
            ): row
            for row in expected_manifest
        }
        final_paths = sorted(
            path
            for path in (staging_root / "explanations").rglob("shard_*.parquet")
            if re.fullmatch(r"shard_\d{3}\.parquet", path.name)
        )
        expected_shard_names = {
            f"shard_{index:03d}.parquet" for index in range(OPTIMIZED_SHARD_COUNT)
        }
        actual_shard_names = {path.name for path in final_paths}
        shard_files_ok = actual_shard_names == expected_shard_names
        if not shard_files_ok:
            raise RuntimeError(
                "final shard file set mismatch: "
                f"expected={sorted(expected_shard_names)}, "
                f"actual={sorted(actual_shard_names)}"
            )

        rows: list[dict[str, Any]] = []
        shard_gate_status: dict[str, Any] = {}
        for shard_index in range(OPTIMIZED_SHARD_COUNT):
            shard_name = f"shard_{shard_index:03d}"
            shard_path = staging_root / "explanations" / f"{shard_name}.parquet"
            gate_path = staging_root / "gates" / f"{shard_name}.json"
            if not gate_path.exists():
                raise RuntimeError(f"missing gate evidence for {shard_name}")
            gate = json.loads(gate_path.read_text(encoding="utf-8"))
            shard_gate_status[shard_name] = gate
            if gate.get("all_gates_pass") is not True:
                raise RuntimeError(f"shard gate failed for {shard_name}")
            shard_rows = pq.read_table(shard_path).to_pylist()
            if len(shard_rows) != OPTIMIZED_SHARD_ROWS:
                raise RuntimeError(
                    f"{shard_name} has {len(shard_rows)} rows instead of "
                    f"{OPTIMIZED_SHARD_ROWS}"
                )
            for row in shard_rows:
                row.setdefault("batch_size", 1)
            rows.extend(shard_rows)

        actual_generation_indices = [int(row["generation_index"]) for row in rows]
        expected_generation_indices = list(range(MANIFEST_ROWS))
        actual_keys = {
            (
                str(row["context_id"]),
                int(row["position_offset"]),
                int(row["sample_idx"]),
            )
            for row in rows
        }
        duplicate_generation_indices = sorted(
            index
            for index in set(actual_generation_indices)
            if actual_generation_indices.count(index) > 1
        )
        duplicate_keys = len(rows) - len(actual_keys)

        activation_keys: set[tuple[str, int]] = set()
        for activation_path in sorted(
            (ROOT / "data" / "activations").glob("shard_*.parquet")
        ):
            for activation in pq.read_table(activation_path).to_pylist():
                activation_keys.add(
                    (str(activation["context_id"]), int(activation["position_offset"]))
                )
        missing_activation_keys = sorted(
            {
                (str(row["context_id"]), int(row["position_offset"]))
                for row in rows
            }
            - activation_keys
        )
        marker_rows = [
            int(row["generation_index"])
            for row in rows
            if "㈜" in str(row["text"]) or "㈜" in str(row["full_response"])
        ]
        refusal_re = re.compile(r"as an AI|I cannot|I'm sorry", re.IGNORECASE)
        refusal_rows = [
            int(row["generation_index"])
            for row in rows
            if refusal_re.search(str(row["text"]))
        ]
        degenerate_rows = [
            int(row["generation_index"])
            for row in rows
            if not str(row["text"]).strip() or int(row["n_tokens"]) < 2
        ]
        lengths = [int(row["n_tokens"]) for row in rows]
        smoke_mean = float(
            json.loads(
                OPTIMIZED_SHARD2_GATE_PATH.read_text(encoding="utf-8")
            )["smoke_mean_tokens"]
        )
        mean_by_stratum = {
            stratum: float(
                statistics.mean(
                    int(row["n_tokens"])
                    for row in rows
                    if str(row["stratum"]) == stratum
                )
            )
            for stratum in ("A", "B", "C")
        }
        gates = {
            "exactly_3900_rows": len(rows) == MANIFEST_ROWS,
            "generation_indices_exact": actual_generation_indices
            == expected_generation_indices,
            "unique_generation_indices": not duplicate_generation_indices,
            "unique_manifest_keys": duplicate_keys == 0,
            "manifest_joinable": actual_keys == set(expected_by_key),
            "joinable_to_activations": not missing_activation_keys,
            "empty_or_degenerate_rate_lt_1_percent": len(degenerate_rows)
            / MANIFEST_ROWS
            < 0.01,
            "median_length_120_to_300": 120 <= statistics.median(lengths) <= 300,
            "no_marker_char": not marker_rows,
            "refusal_rate_lt_2_percent": len(refusal_rows) / MANIFEST_ROWS < 0.02,
            "stratum_mean_within_2x_smoke": all(
                smoke_mean / 2.0 <= value <= smoke_mean * 2.0
                for value in mean_by_stratum.values()
            ),
            "batch_size_column_present": all("batch_size" in row for row in rows),
            "all_shard_gates_pass": all(
                gate.get("all_gates_pass") is True
                for gate in shard_gate_status.values()
            ),
        }
        gate_payload = {
            "status": "passed" if all(gates.values()) else "failed_gate",
            "created_at_unix": time.time(),
            "rows_total": len(rows),
            "length_median": statistics.median(lengths) if lengths else None,
            "length_mean_by_stratum": mean_by_stratum,
            "smoke_mean_tokens": smoke_mean,
            "empty_or_degenerate_rows": degenerate_rows,
            "marker_rows": marker_rows,
            "refusal_rows": refusal_rows,
            "missing_activation_keys": missing_activation_keys,
            "duplicate_generation_indices": duplicate_generation_indices,
            "duplicate_manifest_key_count": duplicate_keys,
            "shard_gate_status": shard_gate_status,
            "gates": gates,
            "all_gates_pass": all(gates.values()),
        }
        if not gate_payload["all_gates_pass"]:
            _atomic_json(MERGE_RESULT_PATH, gate_payload)
            raise RuntimeError(f"Phase 2 merge gate failed: {json.dumps(gates)}")

        _write_local_parquet_atomic(ROOT / "data" / "explanations.parquet", rows)
        contexts = {
            str(row["context_id"]): str(row["text"])
            for row in pq.read_table(CONTEXTS_PATH).to_pylist()
        }
        random_rows = random.Random(0).sample(
            sorted(rows, key=lambda row: int(row["generation_index"])),
            10,
        )
        preview_lines = [
            "# Phase 2 explanation preview",
            "",
            "Ten deterministic seed-0 random (context, explanation) pairs.",
            "",
        ]
        for number, row in enumerate(random_rows, start=1):
            preview_lines.extend(
                [
                    f"## Pair {number} — {row['context_id']} / generation {row['generation_index']}",
                    "",
                    "### Context",
                    "",
                    str(contexts[str(row["context_id"])]),
                    "",
                    "### Explanation",
                    "",
                    str(row["text"]),
                    "",
                ]
            )
        temporary_preview = Path(str(PREVIEW_PATH) + ".tmp")
        temporary_preview.write_text("\n".join(preview_lines), encoding="utf-8")
        os.replace(temporary_preview, PREVIEW_PATH)
        gate_payload["output_path"] = str(ROOT / "data" / "explanations.parquet")
        gate_payload["preview_path"] = str(PREVIEW_PATH)
        _atomic_json(MERGE_RESULT_PATH, gate_payload)
        return gate_payload
    except Exception as exc:
        if not MERGE_RESULT_PATH.exists():
            _atomic_json(
                MERGE_RESULT_PATH,
                {
                    "status": "error",
                    "created_at_unix": time.time(),
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
        raise


@app.local_entrypoint()
def main(mode: str = "shard0") -> None:
    if mode == "optionc_preflight":
        result = _run_optionc_preflight()
        print(json.dumps(result, indent=2), flush=True)
        return

    _assert_predecessor_evidence()

    if mode == "optionc_qualification":
        _assert_local_preflight()
        try:
            result = qualify_batching_optionc.remote()
        except Exception as exc:
            failure = {
                "status": "error",
                "option": "C",
                "created_at_unix": time.time(),
                "error": f"{type(exc).__name__}: {exc}",
            }
            _atomic_json(OPTIONC_QUALIFICATION_RESULT_PATH, failure)
            raise
        _atomic_json(OPTIONC_QUALIFICATION_RESULT_PATH, result)
        if result.get("status") == "error":
            raise RuntimeError(
                f"Option C qualification errored; see {OPTIONC_QUALIFICATION_RESULT_PATH}"
            )
        print(json.dumps(result, indent=2), flush=True)
        return

    if mode in {"fve_equivalence", "batch_fve_equivalence"}:
        _assert_local_preflight()
        try:
            result = run_batch_fve_equivalence.remote()
        except Exception as exc:
            result = {
                "status": "error",
                "created_at_unix": time.time(),
                "error": f"{type(exc).__name__}: {exc}",
            }
        _atomic_json(FVE_RESULT_PATH, result)
        rightsizing = _write_rightsizing_from_fve(result)
        result["right_sizing_evidence"] = str(RIGHTSIZING_RESULT_PATH)
        _atomic_json(FVE_RESULT_PATH, result)
        if result.get("status") == "error":
            raise RuntimeError(
                f"FVE equivalence errored; see {FVE_RESULT_PATH}"
            )
        print(json.dumps({"fve": result, "right_sizing": rightsizing}, indent=2), flush=True)
        return

    if mode == "projection":
        result = _run_projection()
        print(json.dumps(result, indent=2), flush=True)
        return

    if mode == "merge":
        result = _run_merge()
        print(json.dumps(result, indent=2), flush=True)
        return

    _assert_local_preflight()
    rows = _ensure_manifest()
    grouped = _group_manifest(rows)

    if mode == "shard0":
        result = generate_shard_batch4.remote(0, grouped[0], True)
        _atomic_json(SHARD0_RESULT_PATH, result)
        if result.get("shard_gate", {}).get("all_gates_pass") is not True:
            raise RuntimeError(
                f"Phase 2b shard 0 gate failed; see {SHARD0_RESULT_PATH}"
            )
        _atomic_json(SHARD0_GATE_PATH, result["shard_gate"])
        print(json.dumps(result, indent=2), flush=True)
        return

    if mode == "shard1":
        result = generate_shard_batch1.remote(1, grouped[1])
        shard1_result_path = ROOT / "results" / "phase2b_shard1.json"
        shard1_gate_path = ROOT / "results" / "phase2b_shard1_gate.json"
        _atomic_json(shard1_result_path, result)
        if result.get("shard_gate", {}).get("all_gates_pass") is not True:
            raise RuntimeError(
                f"Phase 2b shard 1 gate failed; see {shard1_result_path}"
            )
        _atomic_json(shard1_gate_path, result["shard_gate"])
        print(json.dumps(result, indent=2), flush=True)
        return

    if mode == "optimized_shard2":
        optimized_rows = _ensure_optimized_manifest()
        optimized_grouped = _group_manifest(
            optimized_rows,
            shard_rows=OPTIMIZED_SHARD_ROWS,
            shard_count=OPTIMIZED_SHARD_COUNT,
        )
        qualification_path = ROOT / "results" / "batch_qualification_fix2.json"
        if not qualification_path.exists():
            raise RuntimeError(
                f"missing Fix 2 qualification result {qualification_path}"
            )
        qualification = json.loads(qualification_path.read_text(encoding="utf-8"))
        selected_batch_size = int(qualification["selected_batch_size"])
        result = generate_optimized_shard.remote(
            2,
            optimized_grouped[2],
            selected_batch_size,
        )
        _atomic_json(OPTIMIZED_SHARD2_RESULT_PATH, result)
        if result.get("shard_gate", {}).get("all_gates_pass") is not True:
            raise RuntimeError(
                "optimized shard 2 gate failed; see "
                f"{OPTIMIZED_SHARD2_RESULT_PATH}"
            )
        _atomic_json(OPTIMIZED_SHARD2_GATE_PATH, result["shard_gate"])
        print(json.dumps(result, indent=2), flush=True)
        return

    if mode == "optimized_fanout":
        fanout_evidence = _run_optimized_fanout()
        print(json.dumps(fanout_evidence, indent=2), flush=True)
        return

    if mode == "fanout":
        if not SHARD0_RESULT_PATH.exists():
            raise RuntimeError("run mode=shard0 and pass its gate before fan-out")
        shard0 = json.loads(SHARD0_RESULT_PATH.read_text(encoding="utf-8"))
        if not shard0.get("shard_gate", {}).get("all_gates_pass"):
            raise RuntimeError("shard 0 gate is not green; fan-out is forbidden")
        selected_batch_size = int(shard0["batch_size"])
        shard_indices = list(range(1, SHARD_COUNT))
        shard_rows = [grouped[index] for index in shard_indices]
        if selected_batch_size == 4:
            results = list(
                generate_shard_batch4.map(
                    shard_indices, shard_rows, [False] * len(shard_indices)
                )
            )
        elif selected_batch_size == 1:
            results = list(generate_shard_batch1.map(shard_indices, shard_rows))
        else:
            raise RuntimeError(f"unexpected selected batch size {selected_batch_size}")
        _atomic_json(ROOT / "results" / "phase2b_fanout.json", results)
        if not all(result.get("rows_total") == SHARD_ROWS for result in results):
            raise RuntimeError("one or more fan-out shards did not return 100 rows")
        print(json.dumps(results, indent=2), flush=True)
        return

    raise ValueError(
        f"unknown mode {mode!r}; expected optionc_preflight, "
        "optionc_qualification, fve_equivalence, projection, optimized_fanout, merge, "
        "shard0, shard1, optimized_shard2, or fanout"
    )
