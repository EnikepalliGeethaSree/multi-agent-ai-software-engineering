"""Fine-tune a code model to predict which changes need review.

    python -m marl_agents.training.train --base microsoft/codebert-base --freeze-layers 9
    python -m marl_agents.training.train --lora          # PEFT LoRA adapters instead of freezing

Runs on CPU (slow: keep --max-minutes realistic) or on a free Colab GPU. Works with any
`AutoModelForSequenceClassification` model. The best epoch is chosen on the dev split only; the
test split is never read here. The time budget stops training cleanly and is recorded, so a short
run is never mistaken for a finished one.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from marl_agents.config import PROJECT_ROOT
from marl_agents.evaluation.metrics import binary_metrics, roc_auc
from marl_agents.llm.classifier import METADATA_FILE, ClassifierMetadata
from marl_agents.training.data import SEED, Example, read_examples

logger = logging.getLogger(__name__)

DEFAULT_BASE = "microsoft/codebert-base"
LORA_TARGETS = ["query", "value"]


def best_threshold(labels: list[int], scores: list[float]) -> tuple[float, float]:
    """The cut-off with the best balanced accuracy, chosen on dev and then frozen for test.

    Not best F1: on nearly balanced classes that picks "flag everything", which cannot prioritize.
    """
    positives = sum(labels)
    negatives = len(labels) - positives
    best = (0.5, -1.0)
    for step in range(1, 100):
        threshold = step / 100
        m = binary_metrics(labels, [int(s >= threshold) for s in scores])
        balanced = (m.tp / max(positives, 1) + m.tn / max(negatives, 1)) / 2
        if balanced > best[1]:
            best = (threshold, balanced)
    return best


def _freeze(model: Any, layers: int) -> None:
    """Keep the embeddings and the first `layers` encoder layers fixed."""
    encoder = getattr(model, model.base_model_prefix)
    for p in encoder.embeddings.parameters():
        p.requires_grad = False
    for layer in encoder.encoder.layer[:layers]:
        for p in layer.parameters():
            p.requires_grad = False


def _batches(examples: list[Example], size: int, shuffle_seed: int | None) -> list[list[Example]]:
    order = list(examples)
    if shuffle_seed is not None:
        random.Random(shuffle_seed).shuffle(order)
    return [order[i : i + size] for i in range(0, len(order), size)]


def _score(
    model: Any, tokenizer: Any, torch: Any, examples: list[Example], args: Any, device: Any
) -> list[float]:
    model.eval()
    ordered = sorted(range(len(examples)), key=lambda i: len(examples[i].text))
    scores = [0.0] * len(examples)
    with torch.no_grad():
        for i in range(0, len(ordered), args.eval_batch):
            ids = ordered[i : i + args.eval_batch]
            batch = tokenizer(
                [examples[j].text for j in ids],
                truncation=True,
                padding=True,
                max_length=args.max_length,
                return_tensors="pt",
            ).to(device)
            probs = torch.softmax(model(**batch).logits, dim=-1)[:, 1].tolist()
            for j, p in zip(ids, probs, strict=True):
                scores[j] = p
    return scores


def train(args: argparse.Namespace) -> dict[str, Any]:
    import torch
    from transformers import (
        AutoModelForSequenceClassification,
        AutoTokenizer,
        get_linear_schedule_with_warmup,
    )

    torch.manual_seed(args.seed)
    random.seed(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    train_set = read_examples(args.data / "train.jsonl")
    if args.limit:
        train_set = train_set[: args.limit]
    dev_set = read_examples(args.data / "dev.jsonl")
    if args.dev_limit:
        dev_set = dev_set[: args.dev_limit]
    labels = [e.label for e in dev_set]

    tokenizer = AutoTokenizer.from_pretrained(args.base)
    model = AutoModelForSequenceClassification.from_pretrained(args.base, num_labels=2)
    if args.lora:
        from peft import LoraConfig, TaskType, get_peft_model

        lora = LoraConfig(
            task_type=TaskType.SEQ_CLS, r=8, lora_alpha=16, lora_dropout=0.1,
            target_modules=LORA_TARGETS,
        )  # fmt: skip
        model = get_peft_model(model, lora)
    elif args.freeze_layers:
        _freeze(model, args.freeze_layers)
    model.to(device)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    print(f"device {device}: {trainable:,} of {total:,} parameters trainable", flush=True)

    steps_per_epoch = max(1, len(train_set) // args.batch // args.accumulate)
    optimizer = torch.optim.AdamW(
        [p for p in model.parameters() if p.requires_grad], lr=args.lr, weight_decay=0.01
    )
    schedule = get_linear_schedule_with_warmup(  # type: ignore[no-untyped-call]
        optimizer, int(0.1 * steps_per_epoch * args.epochs), steps_per_epoch * args.epochs
    )

    start = time.perf_counter()
    deadline = start + args.max_minutes * 60 if args.max_minutes else None
    history: list[dict[str, Any]] = []
    best_auc, stopped_early, epochs_run = -1.0, False, 0.0
    args.out.mkdir(parents=True, exist_ok=True)

    def checkpoint(epoch: float, loss: float) -> float:
        scores = _score(model, tokenizer, torch, dev_set, args, device)
        auc = roc_auc(labels, scores) or 0.0
        threshold, balanced = best_threshold(labels, scores)
        history.append(
            {
                "epoch": round(epoch, 2),
                "train_loss": round(loss, 4),
                "dev_auc": round(auc, 4),
                "dev_balanced_accuracy": round(balanced, 4),
                "threshold": threshold,
                "minutes": round((time.perf_counter() - start) / 60, 1),
            }
        )
        print(history[-1], flush=True)
        return auc

    def save(threshold: float) -> None:
        merged = model.merge_and_unload() if args.lora else model
        merged.save_pretrained(args.out)
        tokenizer.save_pretrained(args.out)
        meta = ClassifierMetadata(
            base_model=args.base,
            max_length=args.max_length,
            threshold=threshold,
            trained_at=datetime.now(UTC).isoformat(),
            train_examples=len(train_set),
            method="LoRA" if args.lora else f"fine-tuning (first {args.freeze_layers} frozen)",
        )
        (args.out / METADATA_FILE).write_text(meta.model_dump_json(indent=2), encoding="utf-8")

    for epoch in range(args.epochs):
        model.train()
        running, seen = 0.0, 0
        optimizer.zero_grad()
        batches = _batches(train_set, args.batch, args.seed + epoch)
        for step, chunk in enumerate(batches, start=1):
            batch = tokenizer(
                [e.text for e in chunk],
                truncation=True,
                padding=True,
                max_length=args.max_length,
                return_tensors="pt",
            ).to(device)
            target = torch.tensor([e.label for e in chunk], device=device)
            loss = model(**batch, labels=target).loss
            (loss / args.accumulate).backward()
            running += loss.item() * len(chunk)
            seen += len(chunk)
            if step % args.accumulate == 0:
                torch.nn.utils.clip_grad_norm_(
                    [p for p in model.parameters() if p.requires_grad], 1.0
                )
                optimizer.step()
                schedule.step()
                optimizer.zero_grad()
            if step % 50 == 0:
                elapsed = (time.perf_counter() - start) / 60
                print(f"epoch {epoch} step {step}/{len(batches)} {elapsed:.1f} min", flush=True)
            if deadline and time.perf_counter() > deadline:
                stopped_early = True
                break
        epochs_run = epoch + step / len(batches)
        auc = checkpoint(epochs_run, running / max(seen, 1))
        model.train()
        if auc > best_auc:
            best_auc = auc
            if not args.lora:  # a LoRA model is merged once, at the end
                save(history[-1]["threshold"])
        if stopped_early:
            break
    if args.lora:
        save(history[-1]["threshold"])

    report = {
        "base_model": args.base,
        "method": "lora" if args.lora else "partial_fine_tuning",
        "frozen_layers": 0 if args.lora else args.freeze_layers,
        "device": str(device),
        "train_examples": len(train_set),
        "dev_examples": len(dev_set),
        "epochs_requested": args.epochs,
        "epochs_completed": round(epochs_run, 2),
        "stopped_by_time_budget": stopped_early,
        "trainable_parameters": trainable,
        "total_parameters": total,
        "minutes": round((time.perf_counter() - start) / 60, 1),
        "best_dev_auc": round(best_auc, 4),
        "seed": args.seed,
        "max_length": args.max_length,
        "batch": args.batch,
        "accumulate": args.accumulate,
        "lr": args.lr,
        "history": history,
    }
    (args.out / "training_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    default_data = PROJECT_ROOT / "data" / "classifier" / "py"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=default_data)
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "data" / "models" / "change_cls")
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--accumulate", type=int, default=1)
    parser.add_argument("--eval-batch", type=int, default=32)
    parser.add_argument("--lr", type=float, default=2e-5)
    parser.add_argument("--max-length", type=int, default=256)
    parser.add_argument("--freeze-layers", type=int, default=9)
    parser.add_argument("--lora", action="store_true", help="PEFT LoRA instead of freezing")
    parser.add_argument("--limit", type=int, help="use only the first N training examples")
    parser.add_argument("--dev-limit", type=int)
    parser.add_argument("--max-minutes", type=float, help="stop after this long and keep the best")
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    report = train(args)
    print(json.dumps({k: v for k, v in report.items() if k != "history"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
