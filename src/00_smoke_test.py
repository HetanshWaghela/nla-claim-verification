"""Small, two-phase Modal smoke test for the Qwen3.6-27B NLA.

This deliberately generates only eight AV explanations.  The fixture contains
64 activations, but the first checkpoint is about validating the injection,
generation, and AR scoring path—not about spending GPU time on a full eval.

Run the phases separately so an 80 GB GPU never has to hold AV and AR together:

    modal run nla-verifier/src/00_smoke_test.py::generate_smoke --n 8
    modal run nla-verifier/src/00_smoke_test.py::score_smoke

The first command writes the explanations to the artifact Volume.  The human
checkpoint is to read those eight explanations before running the second
command.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import modal


APP_NAME = "nla-verifier-smoke"
MODEL_REPO = "ceselder/qwen3.6-27b-nla-rl"
AV_ADAPTER = "av_rl_adapters/iter_000300"
ARTIFACT_PATH = "/artifacts/smoke/smoke_inputs.json"
SCORE_PATH = "/artifacts/smoke/smoke_scores.json"
KERNEL_VALIDATION_PATH = "/artifacts/smoke/kernel_validation.json"
KERNEL_FIXTURE_INDICES = [48, 4, 1, 30]

# Keep the two large model families in separate cached stages.  This avoids
# downloading every historical adapter and AR checkpoint in the Hub repo.
AV_FILES = [
    "av_base/*",
    f"{AV_ADAPTER}/*",
    "data/example_activations.parquet",
    "nla_meta.yaml",
]
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
        # The Qwen3.5 checkpoint uses the qwen3_5_text architecture, which is
        # supported by the native Transformers version recorded in its config.
        "transformers==5.5.4",
        "peft",
        "pyarrow",
        "pyyaml",
        "safetensors",
        "numpy",
        "huggingface_hub",
    )
    .uv_pip_install("flash-linear-attention")
    # EasyNLA's pyproject still pins Transformers 4.57.1 even though its
    # current checkpoint is a Qwen3.5/Transformers-5 model. Install the same
    # pinned source revision without re-solving its stale dependency metadata.
    .uv_pip_install(
        "git+https://github.com/asherps/EasyNLA.git@4d728477960c18cdfa36dc04ec738d7f55af9f0b",
        extra_options="--no-deps",
    )
)


GPU_FUNCTION_KWARGS = {
    "image": image,
    # A100-80GB is enough for either 27B AV or 43-layer AR and is cheaper than
    # H100.  The phases are intentionally separate.
    "gpu": "A100-80GB",
    "cpu": 8,
    "memory": 128_000,
    "timeout": 24 * 60 * 60,
    "volumes": {"/cache": cache_volume, "/artifacts": artifact_volume},
    "secrets": [modal.Secret.from_name("amnesiac-hf-auth")],
}

CPU_FUNCTION_KWARGS = {
    "image": image,
    "cpu": 2,
    "memory": 8_000,
    "timeout": 10 * 60,
    "volumes": {"/cache": cache_volume, "/artifacts": artifact_volume},
    "secrets": [modal.Secret.from_name("amnesiac-hf-auth")],
}


app = modal.App(APP_NAME)


def _load_fixture(repo_dir: str, *, n: int, seed: int = 0) -> list[dict]:
    """Read a deterministic random subset of the 64 shipped activations."""

    import numpy as np
    import pyarrow.parquet as pq

    table = pq.read_table(Path(repo_dir) / "data/example_activations.parquet")
    rows = table.to_pylist()
    if not rows:
        raise RuntimeError("the shipped activation fixture is empty")
    if n < 1 or n > len(rows):
        raise ValueError(f"n must be between 1 and {len(rows)}, got {n}")
    indices = np.random.default_rng(seed).choice(len(rows), size=n, replace=False)
    return [{"fixture_index": int(i), **rows[int(i)]} for i in indices]


def _load_tokenizer(repo_dir: str):
    """Load the checkpoint tokenizer across Transformers 4/5 metadata drift."""

    from transformers import AutoTokenizer, PreTrainedTokenizerFast

    tokenizer_dir = Path(repo_dir) / "av_base"
    try:
        return AutoTokenizer.from_pretrained(tokenizer_dir)
    except ValueError as exc:
        # The public checkpoint was saved with Transformers 5 metadata and
        # names its generic fast tokenizer ``TokenizersBackend``. EasyNLA's
        # current dependency pin (4.57.1) does not expose that registry name,
        # but the underlying tokenizer.json remains fully compatible.
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


def _actor_inputs(tokenizer, cfg):
    """Build the exact actor prompt with thinking disabled and one marker."""

    content = cfg.actor_prompt_template.format(injection_char=cfg.injection_char)
    messages = [{"role": "user", "content": content}]
    encoded = tokenizer.apply_chat_template(
        messages,
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


def _load_fixture_indices(repo_dir: str, indices: list[int]) -> list[dict]:
    import pyarrow.parquet as pq

    rows = pq.read_table(Path(repo_dir) / "data/example_activations.parquet").to_pylist()
    if any(index < 0 or index >= len(rows) for index in indices):
        raise ValueError(f"fixture indices are outside 0..{len(rows) - 1}")
    return [{"fixture_index": index, **rows[index]} for index in indices]


def _configure_kernel_mode(kernels_on: bool) -> dict:
    import importlib.metadata
    import importlib.util

    import transformers.models.qwen3_5.modeling_qwen3_5 as qwen_modeling

    fla_available = importlib.util.find_spec("fla") is not None
    try:
        fla_version = importlib.metadata.version("fla-core")
    except importlib.metadata.PackageNotFoundError:
        fla_version = None

    if not kernels_on:
        qwen_modeling.causal_conv1d_fn = None
        qwen_modeling.causal_conv1d_update = None
        qwen_modeling.chunk_gated_delta_rule = None
        qwen_modeling.fused_recurrent_gated_delta_rule = None
        qwen_modeling.FusedRMSNormGated = None
        qwen_modeling.is_fast_path_available = False

    return {
        "requested": "on" if kernels_on else "off",
        "fla_module_available": fla_available,
        "fla_core_version": fla_version,
        "fast_path_available": bool(qwen_modeling.is_fast_path_available),
        "chunk_delta_kernel_available": qwen_modeling.chunk_gated_delta_rule
        is not None,
        "recurrent_delta_kernel_available": qwen_modeling.fused_recurrent_gated_delta_rule
        is not None,
        "causal_conv_kernel_available": qwen_modeling.causal_conv1d_fn is not None,
    }


def _generate_kernel_branch(repo_dir: str, *, kernels_on: bool) -> dict:
    import gc

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM

    from nla.config import load_nla_config
    from nla.schema import EXPLANATION_RE
    from nla.utils import register_karvonen_hook

    kernel_status = _configure_kernel_mode(kernels_on)
    tokenizer = _load_tokenizer(repo_dir)
    cfg = load_nla_config(repo_dir, tokenizer)
    rows = _load_fixture_indices(repo_dir, KERNEL_FIXTURE_INDICES)
    device = torch.device("cuda:0")
    base = AutoModelForCausalLM.from_pretrained(
        Path(repo_dir) / "av_base",
        torch_dtype=torch.bfloat16,
        device_map={"": device},
        attn_implementation="sdpa",
        low_cpu_mem_usage=True,
    )
    actor = PeftModel.from_pretrained(base, Path(repo_dir) / AV_ADAPTER).eval()
    vectors_ref: list[torch.Tensor | None] = [None]
    register_karvonen_hook(
        actor,
        vectors_ref,
        cfg.injection_token_id,
        cfg.injection_left_neighbor_id,
        cfg.injection_right_neighbor_id,
        layer_idx=1,
    )

    generated = []
    for row in rows:
        input_ids, attention_mask = _actor_inputs(tokenizer, cfg)
        input_ids = input_ids.to(device)
        attention_mask = attention_mask.to(device)
        vectors_ref[0] = torch.tensor(
            row["activation_vector"], dtype=torch.float32, device=device
        ).unsqueeze(0)
        try:
            with torch.inference_mode():
                output = actor.generate(
                    input_ids=input_ids,
                    attention_mask=attention_mask,
                    max_new_tokens=256,
                    do_sample=False,
                    temperature=1.0,
                    top_p=1.0,
                    pad_token_id=tokenizer.eos_token_id,
                    return_dict_in_generate=True,
                )
        finally:
            vectors_ref[0] = None
        token_ids = output.sequences[0, input_ids.shape[1] :].tolist()
        response = tokenizer.decode(token_ids, skip_special_tokens=True)
        match = EXPLANATION_RE.search(response)
        explanation = match.group(1).strip() if match else ""
        generated.append(
            {
                "fixture_index": row["fixture_index"],
                "tokens": token_ids,
                "n_tokens": len(token_ids),
                "full_response": response,
                "explanation": explanation,
            }
        )

    del actor, base
    gc.collect()
    torch.cuda.empty_cache()
    return {"kernel_status": kernel_status, "rows": generated}


@app.function(**GPU_FUNCTION_KWARGS)
def validate_kernel_branches() -> dict:
    """Run the greedy kernel ON/OFF smoke validation."""

    import gc

    import torch
    from huggingface_hub import snapshot_download

    started = time.time()
    repo_dir = snapshot_download(
        MODEL_REPO,
        allow_patterns=AV_FILES,
        cache_dir="/cache/huggingface/hub",
    )
    cache_volume.commit()
    kernels_on = _generate_kernel_branch(repo_dir, kernels_on=True)
    gc.collect()
    torch.cuda.empty_cache()
    kernels_off = _generate_kernel_branch(repo_dir, kernels_on=False)

    on_by_index = {row["fixture_index"]: row for row in kernels_on["rows"]}
    off_by_index = {row["fixture_index"]: row for row in kernels_off["rows"]}
    comparisons = []
    for fixture_index in KERNEL_FIXTURE_INDICES:
        on_row = on_by_index[fixture_index]
        off_row = off_by_index[fixture_index]
        comparisons.append(
            {
                "fixture_index": fixture_index,
                "token_identical": on_row["tokens"] == off_row["tokens"],
                "on_n_tokens": on_row["n_tokens"],
                "off_n_tokens": off_row["n_tokens"],
                "on_explanation": on_row["explanation"],
                "off_explanation": off_row["explanation"],
            }
        )
    result = {
        "created_at_unix": time.time(),
        "fixture_indices": KERNEL_FIXTURE_INDICES,
        "kernels_on": kernels_on["kernel_status"],
        "kernels_off": kernels_off["kernel_status"],
        "comparisons": comparisons,
        "all_token_identical": all(item["token_identical"] for item in comparisons),
        "coherent_nonempty_on": all(
            item["on_explanation"].strip() for item in comparisons
        ),
        "coherent_nonempty_off": all(
            item["off_explanation"].strip() for item in comparisons
        ),
        "elapsed_seconds": round(time.time() - started, 1),
    }
    output_path = Path(KERNEL_VALIDATION_PATH)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    artifact_volume.commit()
    return result


@app.function(**CPU_FUNCTION_KWARGS)
def preflight() -> dict:
    """Validate metadata and dependencies without model weights or a GPU."""

    import pyarrow.parquet as pq
    from huggingface_hub import snapshot_download

    from nla.config import load_nla_config

    repo_dir = snapshot_download(
        MODEL_REPO,
        allow_patterns=PREFLIGHT_FILES,
        cache_dir="/cache/huggingface/hub",
    )
    tokenizer = _load_tokenizer(repo_dir)
    cfg = load_nla_config(repo_dir, tokenizer)
    table = pq.read_table(Path(repo_dir) / "data/example_activations.parquet")
    if table.num_rows != 64:
        raise RuntimeError(f"expected 64 fixture rows, found {table.num_rows}")
    if len(table.column("activation_vector")[0].as_py()) != cfg.d_model:
        raise RuntimeError(
            "activation width does not match metadata: "
            f"{len(table.column('activation_vector')[0].as_py())} vs {cfg.d_model}"
        )
    return {
        "model_repo": MODEL_REPO,
        "fixture_rows": table.num_rows,
        "activation_width": cfg.d_model,
        "activation_layer": int(table.column("activation_layer")[0].as_py()),
        "injection_char": cfg.injection_char,
        "injection_token_id": cfg.injection_token_id,
        "critic_template_present": cfg.critic_prompt_template is not None,
        "transformers": __import__("transformers").__version__,
    }


@app.function(**GPU_FUNCTION_KWARGS)
def generate_smoke(n: int = 8) -> dict:
    """Generate a small, human-readable AV sample and persist it."""

    import gc

    import torch
    from huggingface_hub import snapshot_download
    from peft import PeftModel
    from transformers import AutoModelForCausalLM

    from nla.config import load_nla_config
    from nla.schema import EXPLANATION_RE
    from nla.utils import register_karvonen_hook

    started = time.time()
    repo_dir = snapshot_download(
        MODEL_REPO,
        allow_patterns=AV_FILES,
        cache_dir="/cache/huggingface/hub",
    )
    # Persist the downloaded AV weights before doing any GPU work so a later
    # AR phase can reuse the same Hub cache after this container exits.
    cache_volume.commit()
    tokenizer = _load_tokenizer(repo_dir)
    cfg = load_nla_config(repo_dir, tokenizer)
    rows = _load_fixture(repo_dir, n=n)

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

    generated = []
    torch.manual_seed(0)
    for row in rows:
        input_ids, attention_mask = _actor_inputs(tokenizer, cfg)
        input_ids = input_ids.to(device)
        attention_mask = attention_mask.to(device)
        activation = torch.tensor(
            row["activation_vector"], dtype=torch.float32, device=device
        ).unsqueeze(0)
        vectors_ref[0] = activation
        try:
            with torch.inference_mode():
                output = actor.generate(
                    input_ids=input_ids,
                    attention_mask=attention_mask,
                    max_new_tokens=256,
                    do_sample=True,
                    temperature=1.0,
                    top_k=20,
                    top_p=0.95,
                    pad_token_id=tokenizer.eos_token_id,
                    return_dict_in_generate=True,
                )
        finally:
            vectors_ref[0] = None

        response = tokenizer.decode(
            output.sequences[0, input_ids.shape[1] :], skip_special_tokens=True
        )
        match = EXPLANATION_RE.search(response)
        explanation = match.group(1).strip() if match else None
        generated.append(
            {
                "fixture_index": row["fixture_index"],
                "doc_id": row["doc_id"],
                "source": row["detokenized_text_truncated"],
                "activation_vector": row["activation_vector"],
                "full_response": response,
                "explanation": explanation,
            }
        )

    if not all(item["explanation"] for item in generated):
        missing = [
            item["fixture_index"] for item in generated if not item["explanation"]
        ]
        raise RuntimeError(
            f"AV did not emit <explanation> tags for fixture rows {missing}; "
            "stop before AR scoring"
        )

    artifact = {
        "created_at_unix": time.time(),
        "model_repo": MODEL_REPO,
        "av_adapter": AV_ADAPTER,
        "n": len(generated),
        "seed": 0,
        "injection_token_id": cfg.injection_token_id,
        "rows": generated,
    }
    output_path = Path(ARTIFACT_PATH)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(artifact, ensure_ascii=False), encoding="utf-8")
    artifact_volume.commit()

    del actor, base
    gc.collect()
    torch.cuda.empty_cache()

    return {
        "artifact": ARTIFACT_PATH,
        "n": len(generated),
        "fixture_indices": [item["fixture_index"] for item in generated],
        "elapsed_seconds": round(time.time() - started, 1),
        "explanations": [
            {
                "fixture_index": item["fixture_index"],
                "explanation": item["explanation"],
            }
            for item in generated
        ],
    }


@app.function(**GPU_FUNCTION_KWARGS)
def score_smoke() -> dict:
    """Score the eight human-reviewed explanations with the AR."""

    import torch
    import torch.nn.functional as F
    import pyarrow.parquet as pq
    from huggingface_hub import snapshot_download

    from nla.config import load_nla_config
    from nla.models import NLACriticModel
    from nla.schema import normalize_activation
    from nla.utils import critic_predict

    started = time.time()
    artifact_volume.reload()
    artifact = json.loads(Path(ARTIFACT_PATH).read_text(encoding="utf-8"))
    rows = artifact["rows"]

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
    for i, ids in enumerate(token_rows):
        input_ids[i, : len(ids)] = torch.tensor(ids, device=device)
        attention_mask[i, : len(ids)] = 1

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

    # Use all 64 fixture activations for the denominator, while scoring only
    # the eight generated explanations. This makes the result a cheap sampled
    # FVE diagnostic rather than pretending it is the full held-out evaluation.
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

    scores = {
        "created_at_unix": time.time(),
        "n_scored": len(rows),
        "fixture_indices": [row["fixture_index"] for row in rows],
        "mse_scale": mse_scale,
        "baseline_mse_all_64": baseline_mse,
        "mean_mse_scored_sample": mean_mse,
        "sampled_fve": sampled_fve,
        "per_row": [
            {
                "fixture_index": row["fixture_index"],
                "mse": float(mse),
                "fve_against_all_64_baseline": 1.0 - float(mse) / baseline_mse,
            }
            for row, mse in zip(rows, per_row_mse.tolist())
        ],
    }
    output_path = Path(SCORE_PATH)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(scores, indent=2), encoding="utf-8")
    artifact_volume.commit()
    return {**scores, "artifact": SCORE_PATH, "elapsed_seconds": round(time.time() - started, 1)}
