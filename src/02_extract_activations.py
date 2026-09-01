"""Extract target-model layer-42 activations for the Phase 2a runbook."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import modal


ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "nla-verifier-phase2a"
TARGET_MODEL_REPO = "Qwen/Qwen3.6-27B"
NLA_MODEL_REPO = "ceselder/qwen3.6-27b-nla-rl"
TARGET_LAYER = 42
VECTOR_WIDTH = 5120
CONTEXTS_REMOTE_PATH = "/workspace/data/contexts.parquet"
FIXTURE_INDICES = [1, 2, 16, 30, 48]
ACTIVATION_DIR = "/artifacts/phase2a/activations"
CALIBRATION_ARTIFACT = "/artifacts/phase2a/activation_calibration.json"

CONTEXTS_PATH = ROOT / "data" / "contexts.parquet"
CALIBRATION_RESULT_PATH = ROOT / "results" / "activation_calibration.json"
ACTIVATION_GATE_PATH = ROOT / "results" / "activation_gate.json"

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
        "pyarrow",
        "pyyaml",
        "safetensors",
        "numpy",
        "huggingface_hub",
    )
    .uv_pip_install(
        "git+https://github.com/asherps/EasyNLA.git@4d728477960c18cdfa36dc04ec738d7f55af9f0b",
        extra_options="--no-deps",
    )
)
if CONTEXTS_PATH.exists():
    image = image.add_local_file(str(CONTEXTS_PATH), CONTEXTS_REMOTE_PATH)


GPU_FUNCTION_KWARGS = {
    "image": image,
    "gpu": "A100-80GB",
    "cpu": 8,
    "memory": 128_000,
    "timeout": 24 * 60 * 60,
    "max_containers": 1,
    "volumes": {"/cache": cache_volume, "/artifacts": artifact_volume},
    "secrets": [modal.Secret.from_name("amnesiac-hf-auth")],
}


app = modal.App(APP_NAME)


class _CaptureComplete(Exception):
    pass


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    temporary.replace(path)


def _load_target_model():
    import torch
    from huggingface_hub import snapshot_download
    from transformers import AutoModelForCausalLM, AutoTokenizer

    repo_dir = snapshot_download(
        TARGET_MODEL_REPO,
        cache_dir="/cache/huggingface/hub",
        token=True,
    )
    cache_volume.commit()
    tokenizer = AutoTokenizer.from_pretrained(repo_dir)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "left"
    tokenizer.truncation_side = "right"
    model = AutoModelForCausalLM.from_pretrained(
        repo_dir,
        torch_dtype=torch.bfloat16,
        device_map={"": "cuda:0"},
        attn_implementation="sdpa",
        low_cpu_mem_usage=True,
    ).eval()
    return model, tokenizer


def _load_fixture_rows() -> list[dict[str, Any]]:
    import pyarrow.parquet as pq
    from huggingface_hub import snapshot_download

    repo_dir = snapshot_download(
        NLA_MODEL_REPO,
        allow_patterns=["data/example_activations.parquet", "nla_meta.yaml"],
        cache_dir="/cache/huggingface/hub",
        token=True,
    )
    cache_volume.commit()
    table = pq.read_table(Path(repo_dir) / "data/example_activations.parquet")
    rows = table.to_pylist()
    if len(rows) != 64:
        raise RuntimeError(f"expected 64 fixture rows, found {len(rows)}")
    for row in rows:
        if int(row["activation_layer"]) != TARGET_LAYER:
            raise RuntimeError(
                "fixture activation layer contradicts the runbook: "
                f"{row['activation_layer']}"
            )
        if len(row["activation_vector"]) != VECTOR_WIDTH:
            raise RuntimeError(
                "fixture activation width contradicts the runbook: "
                f"{len(row['activation_vector'])}"
            )
    return rows


def _decoder_layers(model: Any):
    from nla.utils.arch_adapters import resolve_decoder_layers

    return resolve_decoder_layers(model)


def _capture_batch(
    model: Any,
    tokenizer: Any,
    texts: list[str],
    layer_index: int,
    variant: str,
) -> tuple[Any, Any, Any]:
    """Run one left-padded batch and return hidden states, ids, and mask."""

    import torch

    encoded = tokenizer(
        texts,
        return_tensors="pt",
        padding=True,
        truncation=True,
        max_length=4096,
        add_special_tokens=True,
    )
    input_ids = encoded["input_ids"].to("cuda:0")
    attention_mask = encoded["attention_mask"].to("cuda:0")
    lengths = attention_mask.sum(dim=1)
    for length, mask in zip(lengths.tolist(), attention_mask):
        length = int(length)
        first_one = int(torch.nonzero(mask, as_tuple=False)[0].item())
        last_one = int(torch.nonzero(mask, as_tuple=False)[-1].item())
        assert first_one == mask.shape[0] - length
        assert last_one == mask.shape[0] - 1
        assert int(mask[first_one:].sum().item()) == length

    captured: dict[str, Any] = {"value": None}
    layers = _decoder_layers(model)
    if not 0 <= layer_index < len(layers):
        raise RuntimeError(
            f"layer index {layer_index} is outside the target model's {len(layers)} layers"
        )
    layer = layers[layer_index]

    def capture_output(_module: Any, _inputs: Any, output: Any) -> None:
        hidden = output[0] if isinstance(output, tuple) else output
        captured["value"] = hidden.detach().clone()
        raise _CaptureComplete

    def capture_input(_module: Any, inputs: Any) -> None:
        hidden = inputs[0]
        captured["value"] = hidden.detach().clone()
        raise _CaptureComplete

    if variant == "block_output":
        handle = layer.register_forward_hook(capture_output)
    elif variant == "block_input":
        handle = layer.register_forward_pre_hook(capture_input)
    elif variant == "input_norm":
        if not hasattr(layer, "input_layernorm"):
            raise RuntimeError("target layer has no input_layernorm for calibration")
        handle = layer.input_layernorm.register_forward_hook(capture_output)
    elif variant == "post_attention_norm":
        if not hasattr(layer, "post_attention_layernorm"):
            raise RuntimeError(
                "target layer has no post_attention_layernorm for calibration"
            )
        handle = layer.post_attention_layernorm.register_forward_hook(capture_output)
    else:
        raise ValueError(f"unknown capture variant {variant}")

    try:
        with torch.inference_mode():
            try:
                model(input_ids=input_ids, attention_mask=attention_mask, use_cache=False)
            except _CaptureComplete:
                pass
    finally:
        handle.remove()

    if captured["value"] is None:
        raise RuntimeError(
            f"capture hook did not fire for layer {layer_index}, variant {variant}"
        )
    hidden = captured["value"].float().cpu()
    if hidden.shape[-1] != VECTOR_WIDTH:
        raise RuntimeError(
            f"captured width {hidden.shape[-1]} does not equal {VECTOR_WIDTH}"
        )
    return hidden, input_ids.cpu(), attention_mask.cpu()


def _final_vectors(
    model: Any,
    tokenizer: Any,
    texts: list[str],
    layer_index: int,
    variant: str,
) -> list[Any]:
    hidden, _input_ids, attention_mask = _capture_batch(
        model, tokenizer, texts, layer_index, variant
    )
    vectors = []
    for row_index, mask in enumerate(attention_mask):
        final_index = int(torch_nonzero_last(mask))
        assert int(mask[final_index].item()) == 1
        vectors.append(hidden[row_index, final_index])
    return vectors


def torch_nonzero_last(mask: Any) -> int:
    import torch

    positions = torch.nonzero(mask, as_tuple=False).flatten()
    if positions.numel() == 0:
        raise RuntimeError("attention mask contains no true token positions")
    return int(positions[-1].item())


def _calibration(model: Any, tokenizer: Any, fixture_rows: list[dict[str, Any]]) -> dict[str, Any]:
    import torch
    import torch.nn.functional as F

    selected_rows = [fixture_rows[index] for index in FIXTURE_INDICES]
    texts = [row["detokenized_text_truncated"] for row in selected_rows]
    candidates = [
        {"layer_index": TARGET_LAYER, "variant": "block_output"},
        {"layer_index": TARGET_LAYER - 1, "variant": "block_output"},
        {"layer_index": TARGET_LAYER + 1, "variant": "block_output"},
        {"layer_index": TARGET_LAYER, "variant": "input_norm"},
        {"layer_index": TARGET_LAYER, "variant": "post_attention_norm"},
        {"layer_index": TARGET_LAYER, "variant": "block_input"},
    ]
    table: list[dict[str, Any]] = []
    selected: dict[str, Any] | None = None
    for candidate in candidates:
        try:
            vectors = _final_vectors(
                model,
                tokenizer,
                texts,
                candidate["layer_index"],
                candidate["variant"],
            )
        except Exception as exc:
            table.append({**candidate, "error": str(exc), "cosines": []})
            continue

        cosines = []
        for vector, row, fixture_index in zip(vectors, selected_rows, FIXTURE_INDICES):
            reference = torch.tensor(
                row["activation_vector"], dtype=torch.float32
            )
            cosine = float(F.cosine_similarity(vector, reference, dim=0).item())
            cosines.append(
                {"fixture_index": fixture_index, "cosine_similarity": cosine}
            )
        passing = sum(item["cosine_similarity"] >= 0.98 for item in cosines)
        entry = {
            **candidate,
            "cosines": cosines,
            "passing_fixtures": passing,
            "pass": passing >= 4,
        }
        table.append(entry)
        if selected is None and entry["pass"]:
            selected = candidate

    result = {
        "fixture_indices": FIXTURE_INDICES,
        "threshold": 0.98,
        "required_passing_fixtures": 4,
        "candidates": table,
        "selected_convention": selected,
        "pass": selected is not None,
    }
    return result


def _read_contexts() -> list[dict[str, Any]]:
    import pyarrow.parquet as pq

    table = pq.read_table(CONTEXTS_REMOTE_PATH)
    rows = table.to_pylist()
    if len(rows) != 300:
        raise RuntimeError(f"expected 300 contexts, found {len(rows)}")
    return rows


def _write_activation_shard(
    shard_index: int,
    contexts: list[dict[str, Any]],
    model: Any,
    tokenizer: Any,
    layer_index: int,
    variant: str,
) -> dict[str, Any]:
    import pyarrow as pa
    import pyarrow.parquet as pq

    output_path = Path(ACTIVATION_DIR) / f"shard_{shard_index:03d}.parquet"
    if output_path.exists():
        return {"shard": shard_index, "rows": 100, "skipped": True}

    rows: list[dict[str, Any]] = []
    batch_size = 8
    for start in range(0, len(contexts), batch_size):
        batch = contexts[start : start + batch_size]
        hidden, _input_ids, attention_mask = _capture_batch(
            model,
            tokenizer,
            [row["text"] for row in batch],
            layer_index,
            variant,
        )
        for row_index, context in enumerate(batch):
            true_length = int(attention_mask[row_index].sum().item())
            final_index = torch_nonzero_last(attention_mask[row_index])
            assert final_index == attention_mask.shape[1] - 1
            for position_offset in range(10):
                padded_index = final_index - position_offset
                assert int(attention_mask[row_index, padded_index].item()) == 1
                vector = hidden[row_index, padded_index].tolist()
                rows.append(
                    {
                        "context_id": context["context_id"],
                        "position_offset": position_offset,
                        "abs_position": true_length - 1 - position_offset,
                        "activation_vector": vector,
                    }
                )

    if len(rows) != 100:
        raise RuntimeError(f"shard {shard_index} produced {len(rows)} rows instead of 100")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    schema = pa.schema(
        [
            ("context_id", pa.string()),
            ("position_offset", pa.int32()),
            ("abs_position", pa.int32()),
            ("activation_vector", pa.list_(pa.float32(), VECTOR_WIDTH)),
        ]
    )
    temporary = Path(str(output_path) + ".tmp")
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), temporary)
    os.replace(temporary, output_path)
    artifact_volume.commit()
    return {"shard": shard_index, "rows": len(rows), "skipped": False}


def _activation_gate(contexts: list[dict[str, Any]]) -> dict[str, Any]:
    import math
    import numpy as np
    import pyarrow.parquet as pq

    context_strata = {row["context_id"]: row["stratum"] for row in contexts}
    files = [Path(ACTIVATION_DIR) / f"shard_{index:03d}.parquet" for index in range(30)]
    missing = [str(path) for path in files if not path.exists()]
    rows_total = 0
    vector_lengths: set[int] = set()
    norms_by_stratum: dict[str, list[float]] = {"A": [], "B": [], "C": []}
    nan_rows: list[str] = []
    join_errors: list[str] = []
    rows_by_shard: dict[str, int] = {}

    for path in files:
        if not path.exists():
            continue
        table = pq.read_table(path)
        rows_by_shard[path.name] = table.num_rows
        rows_total += table.num_rows
        for row in table.to_pylist():
            vector = row["activation_vector"]
            vector_lengths.add(len(vector))
            if any(not math.isfinite(value) for value in vector):
                nan_rows.append(row["context_id"])
            if row["context_id"] not in context_strata:
                join_errors.append(row["context_id"])
            else:
                norms_by_stratum[context_strata[row["context_id"]]].append(
                    float(np.linalg.norm(np.asarray(vector, dtype=np.float32)))
                )

    norm_summary = {}
    for stratum, norms in norms_by_stratum.items():
        values = np.asarray(norms, dtype=np.float64)
        norm_summary[stratum] = {
            "count": int(values.size),
            "mean": float(values.mean()) if values.size else None,
            "std": float(values.std()) if values.size else None,
            "min": float(values.min()) if values.size else None,
            "max": float(values.max()) if values.size else None,
        }

    gates = {
        "all_30_shards_present": not missing,
        "row_count_3000": rows_total == 3000,
        "vector_width_5120": vector_lengths == {VECTOR_WIDTH},
        "norms_40_to_160": all(
            40.0 <= norm <= 160.0
            for norms in norms_by_stratum.values()
            for norm in norms
        ),
        "no_nans": not nan_rows,
        "joinable_contexts": not join_errors,
    }
    return {
        "created_at_unix": time.time(),
        "rows_total": rows_total,
        "rows_by_shard": rows_by_shard,
        "missing_shards": missing,
        "vector_lengths": sorted(vector_lengths),
        "norm_summary_by_stratum": norm_summary,
        "nan_rows": nan_rows,
        "join_errors": join_errors,
        "gates": gates,
        "all_gates_pass": all(gates.values()),
    }


@app.function(**GPU_FUNCTION_KWARGS)
def phase2a() -> dict[str, Any]:
    """Run calibration first, then resumable extraction and its gates."""

    artifact_volume.reload()
    model, tokenizer = _load_target_model()
    fixture_rows = _load_fixture_rows()
    calibration = _calibration(model, tokenizer, fixture_rows)
    calibration_path = Path(CALIBRATION_ARTIFACT)
    calibration_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json(calibration_path, calibration)
    artifact_volume.commit()
    if not calibration["pass"]:
        return {"calibration": calibration, "extraction": None}

    contexts = _read_contexts()
    selected = calibration["selected_convention"]
    assert selected is not None
    extraction_rows = []
    for shard_index in range(30):
        shard_contexts = contexts[shard_index * 10 : (shard_index + 1) * 10]
        extraction_rows.append(
            _write_activation_shard(
                shard_index,
                shard_contexts,
                model,
                tokenizer,
                int(selected["layer_index"]),
                str(selected["variant"]),
            )
        )
    gate = _activation_gate(contexts)
    return {
        "calibration": calibration,
        "extraction_shards": extraction_rows,
        "extraction": gate,
    }


@app.local_entrypoint()
def main() -> None:
    if not CONTEXTS_PATH.exists():
        raise RuntimeError(
            f"missing {CONTEXTS_PATH}; Phase 1 must pass before Phase 2a"
        )
    started = time.time()
    result = phase2a.remote()
    _atomic_json(CALIBRATION_RESULT_PATH, result["calibration"])
    if not result["calibration"]["pass"]:
        raise RuntimeError(
            "activation calibration failed; see " f"{CALIBRATION_RESULT_PATH}"
        )
    if result["extraction"] is None:
        raise RuntimeError("Phase 2a returned no extraction gate after calibration")
    _atomic_json(ACTIVATION_GATE_PATH, result["extraction"])
    if not result["extraction"]["all_gates_pass"]:
        raise RuntimeError(f"activation gates failed; see {ACTIVATION_GATE_PATH}")
    print(
        json.dumps(
            {
                "calibration": result["calibration"],
                "extraction": result["extraction"],
                "wall_time_seconds": round(time.time() - started, 1),
            },
            indent=2,
        ),
        flush=True,
    )
