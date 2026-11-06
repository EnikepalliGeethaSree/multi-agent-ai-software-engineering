# Fine-tuning the change classifier

What was fine-tuned, how, what it achieved, and what it does not show.

**Status:** classifier fine-tuning is implemented, trained and tested on held-out data. Its effect
inside a real LLM review is not measured yet. Generative fine-tuning was not done. Results are from
run `20261106T144800Z_classifier_cls_test_n1771`.

## The short version

We fine-tuned CodeBERT to answer one question: **is a human reviewer likely to comment on this code
change?** On 1,771 held-out Python changes from 15 repositories, separated from training and
tuning by project name wherever the data has one (limits below):

| Scorer | Accuracy | Precision | Recall | F1 | False positive rate | ROC-AUC (95% CI) |
|---|---:|---:|---:|---:|---:|---:|
| **Fine-tuned classifier** | **0.665** | **0.707** | **0.672** | **0.689** | 0.345 | **0.723 (0.699-0.748)** |
| TF-IDF + logistic regression | 0.591 | 0.678 | 0.494 | 0.572 | 0.290 | 0.645 (0.619-0.670) |
| Original static analysis | 0.500 | 0.674 | 0.184 | 0.289 | **0.110** | 0.541 |
| Change size alone | - | - | - | - | - | 0.635 |
| Always "needs review" | 0.553 | - | - | - | - | - |

The classifier beats every baseline on ranking, and its 95% bootstrap interval does not overlap
TF-IDF's. The cost is more false alarms than static analysis: 34.5% of changes that drew no comment
were flagged, against 11.0%.

**What this does not show.** It does not show that review comments got better. The classifier writes
no comments, so BLEU and similar scores cannot change. The label is "a human commented", which is a
proxy for "needs review" and is not a defect label. No Gemini run exists yet, so savings in LLM calls
are unmeasured too.

## Why a classifier, and why this approach

The guide asked for fine-tuning to improve accuracy. Gemini offers no fine-tuning (see
[llm-gemini.md](llm-gemini.md)), and principle 1 says the main LLM is not trained. So this is the
separately scoped experiment that principle allows (decision D28): a small model that **orders or
gates LLM work and can never remove a finding**.

| Item | Choice |
|---|---|
| Base model | `microsoft/codebert-base` (124.6M parameters, 12 layers) |
| Task | Binary: does this diff need review? |
| Method | Partial fine-tuning: first 10 layers frozen, 14.8M parameters trained |
| Input | Unified diff text only, no metadata, 128 tokens |
| Settings | 2 epochs requested, batch 16, learning rate 3e-5, seed 42 |
| Hardware | CPU only (12 cores, 15 GB RAM, no GPU) |
| Time | 110-minute training budget, stopped at 1.15 epochs; 115.1 minutes elapsed in total (explained under Training) |

LoRA is implemented as an option (`--lora`) but was not used: it needs gradients through every layer,
which is impractical on CPU.

## Dataset preprocessing

Source: CodeReviewer Diff Quality Estimation. The raw data has serious traps, and each one would have
produced a falsely good model.

**1. The label leaks through the metadata.** All 132,918 train positives have only
`id, msg, oldf, patch, y`. All 132,918 negatives also have `lang, proj, idx`. So:

- Filtering on `lang == "py"` selects negatives only. The "39,630 Python examples" in the earlier
  feasibility note are all label 0.
- Metadata never reaches the model. Python is recognised from content, by one rule for both classes.
  Checked on tagged records: it kept 0 of 91,369 non-Python records and 69.2% of Python ones.

**2. The official validation and test splits overlap.** They share 28 projects and 664 identical
Python patches. So we split the projects with seed 42:

| Set | Changes | Comment / no comment | Use |
|---|---:|---:|---|
| Dev | 1,963 | 1,064 / 899 | Tuning, checkpoint choice, threshold |
| Repository-disjoint test | 1,771 | 979 / 792 | **Primary result**, used once |
| Official Python test, deduplicated | 3,634 | 2,022 / 1,612 | Reported too, flagged: shares projects with validation |

**3. Train positives look unlike real positives.** They average 1,684 characters against 721 in dev,
and 26% are new files against 12%. Negatives lean on a few projects. A model can score well by
learning this, and fail on real data.

The TF-IDF model made this measurable, so training recipes were compared on dev only:

| Recipe | Held-out train AUC | Dev AUC |
|---|---:|---:|
| Balanced only | 0.825 | 0.619 |
| Project cap only | 0.810 | 0.628 |
| Size match only | 0.754 | 0.619 |
| Project cap + size match | 0.718 | 0.625 |
| Other languages only | 0.749 | 0.607 |
| **Reweighted Python + other languages (chosen)** | 0.751 | **0.641** |

Change size alone scores 0.642 on dev, so that was the bar to beat. No TF-IDF recipe beat it. The
falling held-out score shows the artifacts being removed.

**Final training set: 16,000 changes, 8,000 per class.** 7,299 are Python (projects capped at 1,500
records, sizes matched to dev). The other 8,701 are non-Python records from `valid`, whose two classes
were collected the same way. They share a source file with dev, and the audit below found no shared
project or patch. **So most training data is not Python**,
while every test result is Python only. Scripts: `scripts/compare_training_recipes.py`,
`scripts/compare_same_source.py`. Saved to `data/classifier/py/`.

The comment filter for low-information text removed 0 records.

### How separate the sets are

"Repository-disjoint" here means that **dev and test were split by project name, and the split was
applied wherever the data has a project name.** It does not prove complete repository separation,
because 3,383 training positives have no project name.

The audit below compares project names, and patches by a key that ignores whitespace and hunk
positions. Nothing was scored. Saved as `separation_audit.json` in the run folder
(`scripts/audit_classifier_separation.py`).

| Training records | Count | In dev projects | In held-out test projects | Patches shared with dev | Patches shared with held-out test |
|---|---:|---:|---:|---:|---:|
| Python, no comment (project named) | 3,916 | 0 | 0 | 0 | 0 |
| Python, commented (no project name) | 3,383 | Unknown | Unknown | 0 | 0 |
| Non-Python from `valid` | 8,701 | 0 | 0 | 0 | 0 |

Dev and the held-out test share 0 projects and 0 patches.

**The 8,701 non-Python records.** They come from the same raw `valid` file as dev, so this was checked
directly. All 8,701 have project names, across 185 projects. None is in a dev or held-out test project,
and none shares a patch with dev, the held-out test or the official Python test. The code enforces only
part of this: it excludes test-project names and dev and test patches. That none came from a dev project
was found by the audit, not enforced, so repeat the audit if the data or seed changes.

**What these checks cannot show.** Project names miss forks and renamed repositories, and patch keys
catch copies, not similar code. So the claim is "no overlap found wherever it can be checked", not
"complete separation".

**The official test set is less separate.** 14 of its 29 projects are dev projects, and 3 Python
training negatives share a patch with it. Neither applies to the primary held-out set, and this is why
the official set is reported as secondary.

## Training and checkpoint selection

| Epoch | Train loss | Dev AUC | Dev balanced accuracy | Threshold |
|---:|---:|---:|---:|---:|
| 1.00 | 0.633 | 0.705 | 0.651 | 0.46 |
| 1.15 | 0.588 | **0.712** | 0.653 | 0.44 |

The checkpoint was chosen by dev AUC. The threshold maximises dev balanced accuracy. Best-F1 was
tried first and rejected because it chose 0.05, which flags almost everything.

**Why 115.1 minutes against a 110-minute budget.** `--max-minutes 110` limits the training loop only.
The loop checks the clock after each batch and stopped just past 110 minutes, about 150 batches into
the second epoch. By design, the run then scored the 1,963 dev changes and saved the checkpoint. That
took about 5 minutes (the same step after the first epoch took 5.1, from 90.5 to 95.6 minutes), which
gives 115.1. No training happened after the budget ended. The timer starts after model setup, so setup
is not in this figure, and the first epoch's dev check is inside the 110 minutes.

Model and threshold were frozen before the test set was read, and the test set was evaluated once.
Metrics were then recomputed from the saved predictions with scikit-learn and matched exactly. The
weights' SHA-256 is stored in the run's `metrics.json`.

## Full results

**Primary (repository-disjoint as defined above, n = 1,771), threshold 0.44:**

| | Predicted needs review | Predicted no comment |
|---|---:|---:|
| Human commented | 658 | 321 |
| No comment | 273 | 519 |

| Class | Precision | Recall | Support |
|---|---:|---:|---:|
| Needs review | 0.707 | 0.672 | 979 |
| No comment | 0.618 | 0.655 | 792 |

**Official test (secondary; shares projects with validation, n = 3,634):** accuracy 0.669, precision 0.708, recall
0.690, F1 0.699, false positive rate 0.357, ROC-AUC 0.724 (0.707-0.741). That is almost the same as the
primary result. Change size alone scored 0.641 and TF-IDF 0.637 on this set. Static analysis scored
ROC-AUC 0.540 on 3,633 of these changes, because one has no saved prediction.

Test AUC (0.723) is close to dev AUC (0.712), which is what a model that generalises should show.

### How the confidence intervals were computed

ROC-AUC intervals use a **percentile bootstrap** (`bootstrap_ci` in
`evaluation/metrics/classification.py`):

1. Draw as many (label, score) pairs as the set holds, with replacement: 1,771 or 3,634.
2. Compute ROC-AUC on the draw.
3. Repeat 300 times, using Python's `random.Random` with seed 42.
4. Sort the 300 values and take the 8th and 293rd as the 2.5th and 97.5th percentiles.

Limits:

- It resamples single changes, not projects, and does not stratify by class. Changes from one project
  are related, so the intervals may be too narrow.
- 300 resamples is a modest number, so the endpoints carry some noise.
- Only the classifier and TF-IDF have intervals. Static analysis and change size have none.
- Non-overlapping intervals are a description, not a paired significance test.

### Did it only learn change size?

No. Bigger changes draw more comments, so size was the main concern. This check ran after the model
was frozen, from saved scores. It is descriptive and changed nothing. Saved as `confound_check.json`
in the run folder (`scripts/classifier_confound_check.py`).

| Changed lines | n | Share commented | Classifier AUC | Size AUC |
|---|---:|---:|---:|---:|
| 1-2 | 576 | 0.427 | 0.663 | 0.525 |
| 3-5 | 424 | 0.533 | 0.675 | 0.502 |
| 6-10 | 304 | 0.533 | 0.701 | 0.508 |
| 11-20 | 267 | 0.693 | 0.716 | 0.502 |
| 21-50 | 188 | 0.787 | 0.781 | 0.570 |
| 51+ | 12 | 1.000 | not defined | not defined |

Inside a size band, size carries almost no signal and the classifier still ranks well: weighted
within-band AUC is 0.693.

By project (those with at least 30 changes and both classes), the classifier beats size in **11 of 12**.
Its median AUC is 0.72 and the range is 0.457-0.829. The exception is `materialsproject-pymatgen`
(n = 42, AUC 0.457, below chance). Results differ by repository, so expect some projects to do worse.

### Ranking changes

If reviewers read the highest-scored changes first:

| Top share of changes | Classifier: share commented | Largest changes first |
|---:|---:|---:|
| 10% | 0.938 | 0.808 |
| 20% | 0.848 | 0.757 |
| 30% | 0.799 | 0.714 |
| 50% | 0.712 | 0.643 |

The base rate is 0.553. This is the classifier's strongest use, and why `prioritize` is the default.

## How it is used in a review

`python -m marl_agents.cli review-change ... --classifier data/models/change_cls`

| Mode | What happens |
|---|---|
| `prioritize` (default) | Riskiest units go to the LLM first, so a quota stop loses the least important work |
| `gate` | Also skips units scoring below the threshold |

Safety rules, tested in `tests/unit/agents/test_scheduling.py`:

- A unit with a critical, high or high-confidence static finding is never gated.
- Static findings are never removed, whatever the score.
- It applies only to change reviews, because it learned from diffs.
- Its threshold is the model's own (0.44) unless `classifier.threshold` is set.

**Use `gate` with care.** On the test set, threshold 0.44 would flag 52.6% of changes, and would miss
321 of 979 changes (32.8%) a human commented on. Protection reduces this, but by an unmeasured amount.
The same protection can also limit the savings. In a mock-LLM pipeline check with 15 synthetic units, a forced
threshold of 0.995 skipped none, because all 15 were protected. That says nothing about real code
but is reason not to assume a large saving.

**Speed (classifier only, not a full review).** The whole evaluation took 557 seconds on CPU for about
3,630 changes, dataset loading and baselines included. In the mock-LLM pipeline check, scoring 15 units
took about 2.3 seconds, excluding the time to load the model. No full Gemini review has been timed.

## Reproducing

```bash
pip install -e ".[dev,train]"
python -m marl_agents.training.prepare --max-train 16000
python -m marl_agents.training.baseline
python scripts/compare_training_recipes.py
python scripts/compare_same_source.py
python -m marl_agents.training.train --epochs 2 --max-length 128 --freeze-layers 10 \
    --batch 16 --lr 3e-5 --max-minutes 110 --out data/models/change_cls
python -m marl_agents.cli eval classifier --model-dir data/models/change_cls   # test set: once
python scripts/classifier_confound_check.py experiments/results/<classifier run>
```

The evaluation command reads the test set, so run it only for final numbers.

## Limitations

- **Training stopped early:** 1.15 of 2 epochs, and at 128 tokens, so long diffs are cut off. Dev AUC
  was still rising when the budget ended, so more training may help, but that is untested.
- **The label is a proxy.** People comment for many reasons, and silence does not mean code is fine.
- **Train positives have no project names** (3,383 Python records), so project overlap with dev and
  test cannot be ruled out for them, although none shares a patch with dev or the held-out test.
  See [How separate the sets are](#how-separate-the-sets-are).
- **One seed, one split.** The confidence interval covers sampling of test changes, not training
  variation.
- **Python only.** No claim is made about other languages.
- **Not comparable to published scores.** Papers use other data, languages and splits.
- **Unit input differs from training.** Training used dataset diffs; reviews score units built from
  real changes. How much that matters is unmeasured.
- **The check above ran after the test.** It changed nothing, but its numbers are descriptive.

## Generative fine-tuning: not done

A generative model (one that writes review comments) was not fine-tuned. No generative training code
was run, and no such result exists.

- **Gemini cannot do it:** the API and AI Studio offer no fine-tuning.
- **This machine is unsuitable:** with 14.8M trainable parameters and short inputs, classifier training
  took about 5.4 seconds per batch (90.5 minutes for 1,000 batches). A generative model needs a decoder and longer sequences. Its speed
  here was not measured, because the classifier run already used the available time.
- **The expected gain is small:** published fine-tuned review models reach BLEU-4 of about 5, and an
  independent study found that their comments almost never match a human reviewer (see
  [research/deep-learning-feasibility.md](research/deep-learning-feasibility.md)).

**Recommendation:** do not pursue it for this project. The time is better spent on the Gemini runs
below, which show whether the classifier helps in real reviews.

### Optional: more classifier training on a free GPU

`train.py` uses a GPU when one is present. These settings are **untested**, and free Colab limits were
not verified, so check them first:

```bash
pip install -e ".[train]"
python -m marl_agents.training.train --epochs 3 --max-length 256 --freeze-layers 9 \
    --batch 16 --lr 3e-5 --out data/models/change_cls_gpu
```

Choose between models on dev only. The test set has now been used once, so any second model evaluated
on it must be reported as a second look.

## What remains (pending Gemini runs, no results yet)

1. Add a Gemini key, then compare the classifier off, prioritizing and gating on identical
   development samples. This never reads the test split, and the budget stops between samples:
   ```bash
   python -m marl_agents.cli eval classifier-ablation --model-dir data/models/change_cls \
       --limit 15 --max-llm-calls 45 --config configs/gemini.yaml
   ```
2. Report what changes in LLM calls, tokens and time, and whether any useful comments are lost. If it
   improves efficiency but not review quality, report that.
