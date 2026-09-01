"""Collect the 300 contexts specified for Phase 1.

This phase is deliberately local.  It streams the three specified Hugging
Face datasets, trims with the AV tokenizer, writes one parquet file, and
records every gate result before the next phase is allowed to start.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterator


ROOT = Path(__file__).resolve().parents[1]
MODEL_REPO = "ceselder/qwen3.6-27b-nla-rl"
PREFLIGHT_FILES = [
    "av_base/chat_template.jinja",
    "av_base/tokenizer.json",
    "av_base/tokenizer_config.json",
    "data/example_activations.parquet",
    "nla_meta.yaml",
]

FINEWEB_REPO = "HuggingFaceFW/fineweb"
FINEWEB_CONFIG = "sample-10BT"
SWE_CHAT_REPO = "SALT-NLP/SWE-chat"
SWE_CHAT_CONFIG = "conversations"
WIKIPEDIA_REPO = "wikimedia/wikipedia"
WIKIPEDIA_CONFIG = "20231101.en"

CONTEXTS_PATH = ROOT / "data" / "contexts.parquet"
GATE_PATH = ROOT / "results" / "contexts_gate.json"
PREVIEW_PATH = ROOT / "results" / "contexts_preview.md"

TARGET_ROWS_PER_STRATUM = 100
CHAT_TOKEN_BUDGET = 512
WIKIPEDIA_BATCH_SIZE = 16


def _load_tokenizer(tokenizer_dir: Path | None):
    """Load the AV tokenizer using the same Transformers 4/5 fallback as smoke."""

    from transformers import AutoTokenizer, PreTrainedTokenizerFast

    if tokenizer_dir is None:
        from huggingface_hub import snapshot_download

        repo_dir = snapshot_download(
            MODEL_REPO,
            allow_patterns=PREFLIGHT_FILES,
            token=True,
        )
        tokenizer_dir = Path(repo_dir) / "av_base"
    elif (tokenizer_dir / "av_base").is_dir():
        tokenizer_dir = tokenizer_dir / "av_base"

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


def _token_ids(tokenizer: Any, text: str) -> list[int]:
    return tokenizer.encode(text, add_special_tokens=False)


def _token_count(tokenizer: Any, text: str) -> int:
    return len(_token_ids(tokenizer, text))


def _stream_dataset(repo: str, config: str | None):
    from datasets import load_dataset

    kwargs: dict[str, Any] = {
        "split": "train",
        "streaming": True,
        "token": True,
    }
    if config is not None:
        kwargs["name"] = config
    return load_dataset(repo, **kwargs)


def _dataset_server_rows(repo: str, config: str) -> Iterator[dict[str, Any]]:
    """Page the same Hub dataset split when parquet range reads are unavailable."""

    import urllib.parse
    import urllib.request

    from huggingface_hub import get_token

    offset = 0
    page_size = 100
    token = get_token()
    while True:
        query = urllib.parse.urlencode(
            {
                "dataset": repo,
                "config": config,
                "split": "train",
                "offset": offset,
                "length": page_size,
            }
        )
        request = urllib.request.Request(
            f"https://datasets-server.huggingface.co/rows?{query}",
            headers={"Authorization": f"Bearer {token}"} if token else {},
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.load(response)
        if payload.get("error"):
            raise RuntimeError(
                f"dataset-row service rejected {repo}:{config}: {payload['error']}"
            )

        page = payload.get("rows")
        if not isinstance(page, list):
            raise RuntimeError(
                f"dataset-row service returned no rows for {repo}:{config} at offset {offset}"
            )
        for item in page:
            if not isinstance(item, dict) or "row" not in item:
                raise RuntimeError(
                    f"dataset-row service returned a malformed row for {repo}:{config}"
                )
            yield item["row"]

        offset += len(page)
        total = payload.get("num_rows_total")
        if not page or len(page) < page_size or (
            isinstance(total, int) and offset >= total
        ):
            return


def _collect_fineweb(tokenizer: Any) -> tuple[list[dict[str, str]], dict[str, Any]]:
    dataset = _dataset_server_rows(FINEWEB_REPO, FINEWEB_CONFIG)
    eligible: list[str] = []
    scanned = 0

    for row in dataset:
        scanned += 1
        if "text" not in row:
            raise RuntimeError("FineWeb row has no text field")
        text = row["text"]
        if not isinstance(text, str):
            raise RuntimeError(f"FineWeb text is not a string: {type(text).__name__}")
        if not text.strip():
            continue
        if _token_count(tokenizer, text) >= 300:
            eligible.append(text)
        if len(eligible) == 600:
            break

    if len(eligible) != 600:
        raise RuntimeError(
            f"FineWeb stream ended before 600 eligible documents: {len(eligible)}"
        )

    sampled = random.Random(0).sample(eligible, TARGET_ROWS_PER_STRATUM)
    return (
        [
            {
                "text": text,
                "source_dataset": f"{FINEWEB_REPO}:{FINEWEB_CONFIG}",
            }
            for text in sampled
        ],
        {
            "rows_scanned": scanned,
            "eligible_pool": len(eligible),
            "reader": "Hugging Face dataset-row service, ordered pages of 100",
        },
    )


def _chat_contexts(
    tokenizer: Any,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Build chunks from consecutive role/content rows in one SWE session."""

    dataset = _dataset_server_rows(SWE_CHAT_REPO, SWE_CHAT_CONFIG)
    contexts: list[dict[str, str]] = []
    current_session: str | None = None
    current_parts: list[str] = []
    current_tokens = 0
    rows_seen = 0
    sessions_seen: set[str] = set()
    short_chunks = 0

    for row in dataset:
        rows_seen += 1
        for field in ("session_id", "role", "content"):
            if field not in row:
                raise RuntimeError(f"SWE-chat row has no {field} field")

        session_id = row["session_id"]
        if not isinstance(session_id, str) or not session_id:
            raise RuntimeError("SWE-chat row has an empty or non-string session_id")
        sessions_seen.add(session_id)

        if current_session is None:
            current_session = session_id
        elif session_id != current_session:
            if current_parts:
                if current_tokens >= CHAT_TOKEN_BUDGET:
                    contexts.append(
                        {
                            "text": "\n".join(current_parts),
                            "source_dataset": f"{SWE_CHAT_REPO}:{SWE_CHAT_CONFIG}",
                        }
                    )
                else:
                    short_chunks += 1
            current_session = session_id
            current_parts = []
            current_tokens = 0

        role = row["role"]
        content = row["content"]
        if content is None or content == "":
            continue
        if not isinstance(role, str) or not isinstance(content, str):
            raise RuntimeError("SWE-chat role/content values are not strings")

        line = f"{role}: {content}"
        current_parts.append(line)
        current_tokens += _token_count(tokenizer, line)

        if current_tokens >= CHAT_TOKEN_BUDGET:
            contexts.append(
                {
                    "text": "\n".join(current_parts),
                    "source_dataset": f"{SWE_CHAT_REPO}:{SWE_CHAT_CONFIG}",
                }
            )
            current_parts = []
            current_tokens = 0
            if len(contexts) == TARGET_ROWS_PER_STRATUM:
                break

    if len(contexts) < TARGET_ROWS_PER_STRATUM and current_parts:
        if current_tokens >= CHAT_TOKEN_BUDGET:
            contexts.append(
                {
                    "text": "\n".join(current_parts),
                    "source_dataset": f"{SWE_CHAT_REPO}:{SWE_CHAT_CONFIG}",
                }
            )
        else:
            short_chunks += 1

    if len(contexts) != TARGET_ROWS_PER_STRATUM:
        raise RuntimeError(
            "SWE-chat stream did not produce 100 token-budget contexts: "
            f"{len(contexts)} contexts from {rows_seen} rows"
        )

    return contexts, {
        "rows_scanned": rows_seen,
        "sessions_seen": len(sessions_seen),
        "short_chunks_discarded": short_chunks,
        "reader": "Hugging Face dataset-row service, ordered pages of 100",
    }


def _collect_wikipedia(tokenizer: Any) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Reservoir-sample 100 qualifying passages from the streaming corpus."""

    dataset = _stream_dataset(WIKIPEDIA_REPO, WIKIPEDIA_CONFIG)
    rng = random.Random(0)
    reservoir: list[dict[str, str]] = []
    eligible_seen = 0
    rows_scanned = 0
    pending: list[str] = []

    def process_batch(bodies: list[str]) -> None:
        nonlocal eligible_seen

        encoded = tokenizer(
            bodies,
            add_special_tokens=False,
            return_attention_mask=False,
        )
        for body_ids in encoded["input_ids"]:
            if len(body_ids) < 600:
                continue

            eligible_seen += 1
            if len(reservoir) < TARGET_ROWS_PER_STRATUM:
                replacement = None
            else:
                replacement = rng.randrange(eligible_seen)
                if replacement >= TARGET_ROWS_PER_STRATUM:
                    continue

            passage = tokenizer.decode(body_ids[100:], skip_special_tokens=False)
            if _token_count(tokenizer, passage) < 256:
                continue
            candidate = {
                "text": passage,
                "source_dataset": f"{WIKIPEDIA_REPO}:{WIKIPEDIA_CONFIG}",
            }
            if replacement is None:
                reservoir.append(candidate)
            else:
                reservoir[replacement] = candidate

    for row in dataset:
        rows_scanned += 1
        for field in ("title", "text"):
            if field not in row:
                raise RuntimeError(f"Wikipedia row has no {field} field")

        title = row["title"]
        body = row["text"]
        if not isinstance(title, str) or not isinstance(body, str):
            raise RuntimeError("Wikipedia title/text values are not strings")
        if not title or not body or any(char.isdigit() for char in title):
            continue
        if title.startswith("List of"):
            continue

        pending.append(body)
        if len(pending) == WIKIPEDIA_BATCH_SIZE:
            process_batch(pending)
            pending = []

        if rows_scanned % 100_000 == 0:
            if pending:
                process_batch(pending)
                pending = []
            print(
                "Wikipedia progress: "
                f"{rows_scanned} rows, {eligible_seen} eligible",
                flush=True,
            )

    if pending:
        process_batch(pending)

    if len(reservoir) != TARGET_ROWS_PER_STRATUM:
        raise RuntimeError(
            "Wikipedia stream ended before 100 qualifying passages: "
            f"{len(reservoir)}"
        )

    return reservoir, {
        "rows_scanned": rows_scanned,
        "eligible_seen": eligible_seen,
        "sampling": "reservoir_random_seed_0",
    }


def _trim_text(tokenizer: Any, text: str, context_id: str) -> tuple[str, int, int, bool]:
    ids = _token_ids(tokenizer, text)
    if len(ids) < 256:
        raise RuntimeError(
            f"candidate for {context_id} has only {len(ids)} tokens before trimming"
        )

    requested = random.Random(context_id).randint(256, 512)
    selected = ids[: min(requested, len(ids))]
    trimmed = tokenizer.decode(selected, skip_special_tokens=False)
    n_tokens = _token_count(tokenizer, trimmed)
    if n_tokens < 256 or n_tokens > 512:
        raise RuntimeError(
            f"trimmed {context_id} to invalid token count {n_tokens}"
        )
    return trimmed, n_tokens, requested, len(ids) < requested


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    temporary.replace(path)


def _write_parquet(rows: list[dict[str, Any]], path: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(
        rows,
        schema=pa.schema(
            [
                ("context_id", pa.string()),
                ("stratum", pa.string()),
                ("source_dataset", pa.string()),
                ("text", pa.string()),
                ("n_tokens", pa.int32()),
            ]
        ),
    )
    temporary = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(table, temporary)
    temporary.replace(path)


def _write_preview(rows: list[dict[str, Any]]) -> None:
    by_stratum: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_stratum[row["stratum"]].append(row)

    sections: list[str] = [
        "# Phase 1 contexts preview",
        "",
        "Three deterministic random contexts per stratum (seed 0).",
        "",
    ]
    for stratum in ("A", "B", "C"):
        sections.extend([f"## Stratum {stratum}", ""])
        selected = random.Random(0).sample(by_stratum[stratum], 3)
        for row in selected:
            sections.extend(
                [
                    f"### {row['context_id']} ({row['n_tokens']} tokens)",
                    f"Source: `{row['source_dataset']}`",
                    "",
                    row["text"],
                    "",
                ]
            )

    PREVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = PREVIEW_PATH.with_suffix(PREVIEW_PATH.suffix + ".tmp")
    temporary.write_text("\n".join(sections), encoding="utf-8")
    temporary.replace(PREVIEW_PATH)


def _gate(rows: list[dict[str, Any]], tokenizer: Any) -> dict[str, Any]:
    counts = {stratum: sum(row["stratum"] == stratum for row in rows) for stratum in "ABC"}

    duplicate_groups: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        duplicate_groups[row["text"][:200]].append(row["context_id"])
    duplicate_groups = {
        key: value for key, value in duplicate_groups.items() if len(value) > 1
    }

    invalid_token_rows = [
        {"context_id": row["context_id"], "n_tokens": row["n_tokens"]}
        for row in rows
        if not 256 <= row["n_tokens"] <= 512
    ]
    empty_rows = [row["context_id"] for row in rows if not row["text"].strip()]

    from langdetect import DetectorFactory, detect

    DetectorFactory.seed = 0
    language_rows: list[dict[str, str]] = []
    language_exceptions: list[dict[str, str]] = []
    for row in rows:
        try:
            detected = detect(row["text"])
        except Exception as exc:
            detected = "error"
            language_exceptions.append(
                {"context_id": row["context_id"], "error": str(exc)}
            )
        language_rows.append({"context_id": row["context_id"], "language": detected})

    english_count = sum(item["language"] == "en" for item in language_rows)
    english_fraction = english_count / len(rows) if rows else 0.0

    gates = {
        "counts_and_duplicate_prefix_gate": (
            counts == {"A": 100, "B": 100, "C": 100}
            and not duplicate_groups
        ),
        "token_and_empty_gate": not invalid_token_rows and not empty_rows,
        "language_gate": english_fraction >= 0.95,
        "preview_written": PREVIEW_PATH.exists(),
    }
    return {
        "created_at_unix": time.time(),
        "rows": len(rows),
        "counts": counts,
        "duplicate_prefix_groups": duplicate_groups,
        "invalid_token_rows": invalid_token_rows,
        "empty_or_whitespace_rows": empty_rows,
        "language": {
            "english_count": english_count,
            "total_count": len(rows),
            "english_fraction": english_fraction,
            "detections": language_rows,
            "exceptions": language_exceptions,
        },
        "gates": gates,
        "all_gates_pass": all(gates.values()),
        "tokenizer_vocab_size": len(tokenizer),
        "outputs": {
            "contexts": str(CONTEXTS_PATH),
            "preview": str(PREVIEW_PATH),
        },
    }


def collect(tokenizer_dir: Path | None) -> dict[str, Any]:
    started = time.time()
    tokenizer = _load_tokenizer(tokenizer_dir)
    print("Collecting Stratum A from FineWeb", flush=True)
    stratum_a, stats_a = _collect_fineweb(tokenizer)
    print("Collecting Stratum B from preferred SWE-chat", flush=True)
    stratum_b, stats_b = _chat_contexts(tokenizer)
    print("Collecting Stratum C from Wikipedia", flush=True)
    stratum_c, stats_c = _collect_wikipedia(tokenizer)

    raw_by_stratum = {"A": stratum_a, "B": stratum_b, "C": stratum_c}
    rows: list[dict[str, Any]] = []
    trim_stats = {"requested_shorter_than_candidate": 0, "requested_lengths": []}
    next_id = 0
    for stratum in ("A", "B", "C"):
        if len(raw_by_stratum[stratum]) != TARGET_ROWS_PER_STRATUM:
            raise RuntimeError(
                f"stratum {stratum} has {len(raw_by_stratum[stratum])} raw rows"
            )
        for candidate in raw_by_stratum[stratum]:
            context_id = f"c{next_id:03d}"
            text, n_tokens, requested, capped = _trim_text(
                tokenizer, candidate["text"], context_id
            )
            rows.append(
                {
                    "context_id": context_id,
                    "stratum": stratum,
                    "source_dataset": candidate["source_dataset"],
                    "text": text,
                    "n_tokens": n_tokens,
                }
            )
            trim_stats["requested_lengths"].append(requested)
            if capped:
                trim_stats["requested_shorter_than_candidate"] += 1
            next_id += 1

    if len(rows) != 300:
        raise RuntimeError(f"collected {len(rows)} rows instead of 300")

    _write_parquet(rows, CONTEXTS_PATH)
    _write_preview(rows)
    gate = _gate(rows, tokenizer)
    gate["wall_time_seconds"] = round(time.time() - started, 1)
    gate["collection_stats"] = {"A": stats_a, "B": stats_b, "C": stats_c}
    gate["trim_stats"] = trim_stats
    _write_json(GATE_PATH, gate)

    if not gate["all_gates_pass"]:
        raise RuntimeError(f"Phase 1 gates failed; inspect {GATE_PATH}")
    return gate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--tokenizer-dir",
        type=Path,
        default=None,
        help="optional local directory containing av_base tokenizer files",
    )
    args = parser.parse_args()
    result = collect(args.tokenizer_dir)
    print(json.dumps(result, indent=2, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
