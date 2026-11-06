import pytest

from marl_agents.ingestion.diff import PatchError, apply_patch, changed_new_lines, parse_hunks

OLD = "a\nb\nc\nd\ne\n"


def test_modification_marks_new_lines() -> None:
    patch = "@@ -2,3 +2,3 @@\n b\n-c\n+C\n d\n"
    assert changed_new_lines(patch) == [(3, 3)]
    assert apply_patch(OLD, patch) == "a\nb\nC\nd\ne\n"


def test_addition_spans_all_added_lines() -> None:
    patch = "@@ -2,2 +2,4 @@\n b\n+x\n+y\n c\n"
    assert changed_new_lines(patch) == [(3, 4)]
    assert apply_patch(OLD, patch) == "a\nb\nx\ny\nc\nd\ne\n"


def test_pure_deletion_is_attributed_to_neighbouring_lines() -> None:
    patch = "@@ -2,3 +2,2 @@\n b\n-c\n d\n"
    assert changed_new_lines(patch) == [(2, 3)]
    assert apply_patch(OLD, patch) == "a\nb\nd\ne\n"


def test_multiple_hunks_and_merge_of_adjacent_ranges() -> None:
    patch = "@@ -1,2 +1,2 @@\n-a\n+A\n b\n@@ -4,2 +4,2 @@\n-d\n+D\n e\n"
    assert changed_new_lines(patch) == [(1, 1), (4, 4)]
    assert apply_patch(OLD, patch) == "A\nb\nc\nD\ne\n"
    assert len(parse_hunks(patch)) == 2


def test_fuzz_finds_hunk_a_few_lines_away() -> None:
    patch = "@@ -1,2 +1,2 @@\n c\n-d\n+D\n"  # declared at line 1, actually at line 3
    assert apply_patch(OLD, patch) == "a\nb\nc\nD\ne\n"


def test_mismatched_context_raises() -> None:
    with pytest.raises(PatchError):
        apply_patch(OLD, "@@ -2,2 +2,2 @@\n zzz\n-c\n+C\n")


def test_empty_context_lines_without_leading_space() -> None:
    old = "def f():\n\n    return 1\n"
    patch = "@@ -1,3 +1,3 @@\n def f():\n\n-    return 1\n+    return 2\n"
    assert apply_patch(old, patch) == "def f():\n\n    return 2\n"
    assert changed_new_lines(patch) == [(3, 3)]
