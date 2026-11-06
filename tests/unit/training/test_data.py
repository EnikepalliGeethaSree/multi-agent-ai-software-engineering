"""Classifier data preparation: the label must not leak, and the splits must stay independent."""

from __future__ import annotations

import json
import zipfile

from marl_agents.evaluation.datasets.codereviewer import CLS_MEMBERS, CLS_ZIP, CodeReviewerSample
from marl_agents.llm.classifier import change_text
from marl_agents.training.data import (
    Example,
    Pooled,
    balance,
    cap_projects,
    clean_eval_split,
    is_low_information,
    looks_like_python,
    match_sizes,
    other_language_examples,
    patch_key,
    project_holdout,
    reweight,
    select_train,
    size_bin,
)
from marl_agents.training.train import best_threshold

PY = "def f(x):\n    return x + 1\n"
PATCH = "@@ -1,2 +1,2 @@\n def f(x):\n-    return x + 1\n+    return x + 2\n"
JAVA = "public class A {\n  int f() {\n    return 1;\n  }\n}\n"


def raw(
    patch: str = PATCH, oldf: str = PY, y: int = 1, msg: str = "This looks wrong to me", **extra
):  # type: ignore[no-untyped-def]
    return {"patch": patch, "oldf": oldf, "y": y, "msg": msg, **extra}


def test_python_is_recognised_from_content() -> None:
    assert looks_like_python(PY, PATCH)
    assert not looks_like_python(JAVA, PATCH)
    assert not looks_like_python("", "@@ -0,0 +1 @@\n+int x = 1;\n")


def test_new_file_is_judged_by_its_added_lines() -> None:
    assert looks_like_python("", "@@ -0,0 +1,2 @@\n+def g():\n+    return 2\n")


def test_dataset_code_is_parsed_and_never_run() -> None:
    bomb = "raise SystemExit('executed')\n"
    assert looks_like_python(bomb, PATCH)  # would have exited the test run if executed


def test_language_tag_plays_no_part_in_selection() -> None:
    """Positives have no `lang`, negatives do: the same content must get the same decision."""
    tagged = raw(y=0, msg="", lang="py", proj="p", idx=1)
    untagged = raw(patch=PATCH + "+    z = 3\n", y=1)
    kept, report, check = select_train([tagged, untagged], set())
    assert sorted(e.label for e in kept) == [0, 1]
    assert report.dropped == {}
    assert check == {"py_tag_kept": 1}


def test_examples_expose_nothing_but_diff_text_and_label() -> None:
    assert set(Example.model_fields) == {"text", "label"}
    pool, _, _ = select_train([raw(lang="py", proj="secret-project", idx=7)], set())
    assert pool[0].project == "secret-project"  # for sampling only
    trained_on = reweight(pool, [Example(text=pool[0].text, label=1)], None, None)
    assert all("secret-project" not in e.model_dump_json() for e in trained_on)
    assert all(set(e.model_dump()) == {"text", "label"} for e in trained_on)


def test_non_python_records_are_dropped_and_counted() -> None:
    kept, report, check = select_train([raw(oldf=JAVA, y=0, lang="java")], set())
    assert kept == [] and report.dropped == {"not_python": 1}
    assert check == {"other_tag_dropped": 1}


def test_low_information_comments_are_not_positive_examples() -> None:
    for comment in ("", "nit", "LGTM", "+1", "typo", "thanks!", "why?"):
        assert is_low_information(comment), comment
    assert not is_low_information("This loop never terminates when n is zero")
    kept, report, _ = select_train([raw(msg="nit")], set())
    assert kept == [] and report.dropped == {"low_information_comment": 1}
    kept, _, _ = select_train([raw(msg="nit")], set(), keep_low_information=True)
    assert len(kept) == 1


def test_duplicates_are_removed_and_conflicting_labels_dropped() -> None:
    kept, report, _ = select_train([raw(), raw()], set())
    assert len(kept) == 1 and report.dropped == {"duplicate": 1}
    kept, report, _ = select_train([raw(y=1), raw(y=0, msg=""), raw(y=1)], set())
    assert kept == [] and report.dropped == {"conflicting_labels": 3}


def test_train_never_contains_a_patch_from_valid_or_test() -> None:
    kept, report, _ = select_train([raw()], {patch_key(PATCH)})
    assert kept == [] and report.dropped == {"duplicate_of_valid_or_test": 1}


def test_near_duplicates_share_a_key() -> None:
    moved = PATCH.replace("@@ -1,2 +1,2 @@", "@@ -40,2 +40,2 @@").replace("x + 2", "x  +  2")
    assert patch_key(PATCH) == patch_key(moved)
    assert patch_key(PATCH) != patch_key(PATCH.replace("x + 2", "x + 3"))


def test_empty_or_malformed_patches_are_dropped() -> None:
    kept, report, _ = select_train(
        [raw(patch=""), raw(patch="no hunk header"), raw(patch="@@ -1 +1 @@\n a\n")], set()
    )
    assert kept == []
    assert report.dropped == {"empty_or_malformed_patch": 2, "no_changed_lines": 1}


def test_project_holdout_is_disjoint_complete_and_reproducible() -> None:
    projects = [f"p{i}" for i in range(29)]
    dev, test = project_holdout(projects, seed=42)
    assert dev.isdisjoint(test) and dev | test == set(projects)
    assert (dev, test) == project_holdout(reversed(projects), seed=42)
    assert project_holdout(projects, seed=1) != (dev, test)


def _sample(patch: str, label: int = 1, proj: str = "p") -> CodeReviewerSample:
    return CodeReviewerSample(
        sample_id=patch, task="cls", split="test", proj=proj, patch=patch, oldf="", label=label
    )


def test_evaluation_split_drops_cross_split_duplicates() -> None:
    other = "@@ -1 +1 @@\n-a\n+b\n"
    kept, report = clean_eval_split(
        [_sample(PATCH), _sample(PATCH), _sample(other)], "dev", {patch_key(other)}
    )
    assert [s.patch for s in kept] == [PATCH]
    assert report.dropped == {"duplicate": 1, "duplicate_across_splits": 1}


def test_balance_gives_equal_classes_reproducibly() -> None:
    items = [Example(text=str(i), label=1) for i in range(100)]
    items += [Example(text=f"n{i}", label=0) for i in range(30)]
    chosen = balance(items, None, seed=1)
    assert sum(e.label for e in chosen) == 30 and len(chosen) == 60
    assert chosen == balance(items, None, seed=1)
    assert len(balance(items, 10, seed=1)) == 10


def test_threshold_separates_the_classes() -> None:
    threshold, balanced = best_threshold([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9])
    assert 0.2 < threshold <= 0.8 and balanced == 1.0


def test_threshold_does_not_settle_on_flagging_everything() -> None:
    labels = [1] * 6 + [0] * 4
    scores = [0.9, 0.8, 0.7, 0.6, 0.55, 0.3, 0.5, 0.4, 0.3, 0.2]
    threshold, _ = best_threshold(labels, scores)
    assert sum(s >= threshold for s in scores) < len(scores)


def diff(changed: int, tag: str = "x") -> str:
    return "@@ -1 +1 @@\n" + "\n".join(f"+{tag}{i} = 1" for i in range(changed))


def test_size_bins_follow_changed_lines() -> None:
    assert [size_bin(diff(n)) for n in (1, 2, 3, 5, 6, 20, 21, 50, 51)] == [
        0, 0, 1, 1, 2, 3, 4, 4, 5,
    ]  # fmt: skip


def test_no_project_can_dominate_after_the_cap() -> None:
    pool = [Pooled(text=str(i), label=0, project="big") for i in range(100)]
    pool += [Pooled(text=f"s{i}", label=0, project="small") for i in range(5)]
    pool += [Pooled(text=f"p{i}", label=1, project=None) for i in range(7)]
    kept = cap_projects(pool, 10)
    assert sum(p.project == "big" for p in kept) == 10
    assert sum(p.project == "small" for p in kept) == 5
    assert sum(p.project is None for p in kept) == 7  # unnamed records cannot be capped
    assert len(cap_projects(pool, None)) == len(pool)


def test_positives_are_reshaped_to_the_reference_size_mix() -> None:
    pool = [Pooled(text=diff(60, str(i)), label=1) for i in range(100)]  # mostly large
    pool += [Pooled(text=diff(1, str(i)), label=1) for i in range(20)]
    reference = [Example(text=diff(1), label=1)] * 3 + [Example(text=diff(60), label=1)]
    kept = match_sizes(pool, reference)
    small = sum(size_bin(p.text) == 0 for p in kept)
    large = sum(size_bin(p.text) == 5 for p in kept)
    assert (small, large) == (20, 7)  # 3:1, as in the reference, using every small example


def test_each_class_is_matched_to_its_own_mix() -> None:
    pool = [Pooled(text=diff(1, f"n{i}"), label=0) for i in range(10)]
    pool += [Pooled(text=diff(60, f"p{i}"), label=1) for i in range(10)]
    reference = [Example(text=diff(1), label=0), Example(text=diff(60), label=1)]
    assert len(match_sizes(pool, reference)) == 20


def _valid_zip(tmp_path, records) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / CLS_ZIP
    path.parent.mkdir(parents=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(CLS_MEMBERS["valid"][0], "\n".join(json.dumps(r) for r in records) + "\n")


def test_same_source_records_stay_outside_python_and_test_projects(tmp_path) -> None:  # type: ignore[no-untyped-def]
    keep = {"patch": "@@ -1 +1 @@\n-a;\n+b;\n", "y": 1, "lang": "go", "proj": "go-repo"}
    records = [
        keep,
        dict(keep),  # duplicate
        {**keep, "patch": "@@ -1 +1 @@\n-c\n+d\n", "lang": "py"},
        {**keep, "patch": "@@ -1 +1 @@\n-e\n+f\n", "proj": "test-repo"},
        {**keep, "patch": "@@ -1 +1 @@\n-g\n+h\n"},  # already in dev
        {**keep, "patch": "@@ -1 +1 @@\n unchanged\n"},
    ]
    _valid_zip(tmp_path, records)
    out = other_language_examples(tmp_path, {"test-repo"}, {patch_key("@@ -1 +1 @@\n-g\n+h\n")})
    assert [e.text for e in out] == [change_text(keep["patch"])]
    assert out[0].label == 1
