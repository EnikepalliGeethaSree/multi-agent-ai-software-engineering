"""BugsInPy loading and repository handling. A local git repository stands in for GitHub."""

import subprocess
import tarfile
from pathlib import Path

import pytest

from marl_agents.config import Settings
from marl_agents.evaluation.datasets.bugsinpy import (
    BugsInPySample,
    changed_line_count,
    is_small_fix,
    iter_bugs,
    load_bugsinpy,
    ordered_candidates,
    parse_pairs,
    parse_test_names,
    patch_for_file,
)
from marl_agents.evaluation.datasets.bugsinpy_repo import (
    BugRepoCache,
    DiskSpaceError,
    IneligibleBug,
    RepoCacheError,
    extract_tests,
    gold_lines,
    locate_gold,
    resolve_bug,
)

FIXTURE = Path(__file__).parents[2] / "fixtures" / "datasets" / "bugsinpy"
PATCH = """diff --git a/pkg/core.py b/pkg/core.py
index 1..2 100644
--- a/pkg/core.py
+++ b/pkg/core.py
@@ -1,4 +1,4 @@
 def half(x):
-    return x // 2
+    return x / 2


"""
BUGGY = "def half(x):\n    return x // 2\n\n\ndef other():\n    return 1\n"
FIXED = "def half(x):\n    return x / 2\n\n\ndef other():\n    return 1\n"


def sample(**changes) -> BugsInPySample:
    values = {
        "sample_id": "demo-1", "project": "demo", "bug_id": 1,
        "github_url": "https://github.com/acme/demo", "buggy_commit": "a" * 40,
        "fixed_commit": "b" * 40, "test_files": ["tests/test_core.py"], "test_names": ["test_half"],
        "patch": PATCH, "source_files": ["pkg/core.py"], "changed_lines": 2,
    }  # fmt: skip
    return BugsInPySample(**{**values, **changes})


# ---- the dataset's formats ------------------------------------------------------------------------


def test_fields_run_together_on_one_line() -> None:
    text = 'test_file="tests/test_black.py"python_version="3.8.3"\n'
    assert parse_pairs(text) == {"test_file": "tests/test_black.py", "python_version": "3.8.3"}


def test_space_before_the_equals_sign_as_youtube_dl_writes_it() -> None:
    assert parse_pairs('fixed_commit_id ="abc"\r\n') == {"fixed_commit_id": "abc"}


def test_url_after_a_field_with_no_newline() -> None:
    assert parse_pairs('cause="N.A."github_url="https://x"')["github_url"] == "https://x"


def test_test_names_from_both_runners() -> None:
    assert parse_test_names("pytest a/test_x.py::TestA::test_b\n") == ["test_b"]
    assert parse_test_names("pytest a/test_x.py::test_c[1-2]") == ["test_c"]
    assert parse_test_names("python -m unittest -q tests.test_black.Case.test_d\n") == ["test_d"]
    assert parse_test_names("pytest a.py::test_e\npytest a.py::test_f\n") == ["test_e", "test_f"]
    assert parse_test_names("") == []


def test_counting_changed_lines() -> None:
    assert changed_line_count(PATCH) == 2


def test_patch_for_one_file_of_several() -> None:
    two = PATCH + PATCH.replace("pkg/core.py", "pkg/two.py")
    assert "pkg/two.py" in patch_for_file(two, "pkg/two.py")
    assert "pkg/core.py" not in patch_for_file(two, "pkg/two.py")
    assert patch_for_file(two, "pkg/none.py") == ""


# ---- loading ------------------------------------------------------------------------------------


def test_fixture_loads_and_skips_stray_entries() -> None:
    bugs = list(iter_bugs(FIXTURE))
    assert [b.sample_id for b in bugs] == ["PySnooper-1", "PySnooper-2", "pandas-1", "pandas-2"]
    first = bugs[0]
    assert first.split == "dev" and first.github_url == "https://github.com/cool-RR/PySnooper"
    assert first.source_files == ["pysnooper/tracer.py"]
    assert first.test_names == ["test_chinese"]


def test_test_files_do_not_count_as_source() -> None:
    bug = next(b for b in iter_bugs(FIXTURE) if b.sample_id == "PySnooper-1")
    assert "tests/test_chinese.py" not in bug.source_files


def test_small_fix_rule() -> None:
    assert is_small_fix(sample())
    assert not is_small_fix(sample(changed_lines=11))
    assert not is_small_fix(sample(source_files=["a.py", "b.py"]))


def test_dev_and_test_share_no_project() -> None:
    bugs = list(iter_bugs(FIXTURE))
    dev = {b.project for b in ordered_candidates(bugs, "dev")}
    test = {b.project for b in ordered_candidates(bugs, "test")}
    assert dev == {"PySnooper"} and test == {"pandas"}


def test_sampling_is_repeatable_and_seeded() -> None:
    bugs = list(iter_bugs(FIXTURE))
    once = [b.sample_id for b in ordered_candidates(bugs, "dev", seed=1)]
    assert once == [b.sample_id for b in ordered_candidates(bugs, "dev", seed=1)]


def test_round_robin_stops_a_big_project_dominating() -> None:
    bugs = [sample(project="pandas", sample_id=f"pandas-{i}", bug_id=i) for i in range(9)]
    bugs += [sample(project="keras", sample_id=f"keras-{i}", bug_id=i) for i in range(2)]
    first = [b.project for b in ordered_candidates(bugs, "test")[:4]]
    assert first.count("keras") == 2 and first.count("pandas") == 2


def test_unknown_split_is_refused() -> None:
    with pytest.raises(ValueError):
        ordered_candidates([], "train")


def test_load_limits() -> None:
    assert len(load_bugsinpy("dev", limit=1, root=FIXTURE)) == 1


def test_missing_dataset_says_so(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        list(iter_bugs(tmp_path))


# ---- gold locations -----------------------------------------------------------------------------


def test_gold_lines_are_lines_of_the_buggy_file() -> None:
    assert gold_lines(PATCH, BUGGY) == [2]


def test_insertion_counts_as_the_line_before() -> None:
    patch = "@@ -1,2 +1,3 @@\n def half(x):\n+    x = abs(x)\n     return x // 2\n"
    assert gold_lines(patch, BUGGY) == [1]


def test_patch_that_does_not_fit_the_file_is_refused() -> None:
    with pytest.raises(IneligibleBug) as caught:
        gold_lines(PATCH, "completely\ndifferent\nfile\n")
    assert caught.value.reason == "patch_does_not_match_buggy_commit"


def test_gold_function_and_its_lines_in_both_versions() -> None:
    gold = locate_gold(sample(), BUGGY, FIXED)
    assert len(gold) == 1 and gold[0].qualname == "half" and gold[0].changed_lines == [2]
    assert (gold[0].buggy_start, gold[0].buggy_end) == (1, 2)
    assert (gold[0].fixed_start, gold[0].fixed_end) == (1, 2)


def test_change_outside_a_function_is_not_usable() -> None:
    patch = "diff --git a/pkg/core.py b/pkg/core.py\n@@ -1 +1 @@\n-X = 1\n+X = 2\n"
    with pytest.raises(IneligibleBug) as caught:
        locate_gold(sample(patch=patch), "X = 1\n", "X = 2\n")
    assert caught.value.reason == "change_outside_a_function"


def test_python_2_source_is_not_usable() -> None:
    bad = "def half(x):\n    return x // 2\n\n\nprint 'old'\n"
    with pytest.raises(IneligibleBug) as caught:
        locate_gold(sample(), bad, FIXED)
    assert caught.value.reason == "not_parseable_by_python_3"


def test_function_removed_by_the_fix_is_not_usable() -> None:
    with pytest.raises(IneligibleBug) as caught:
        locate_gold(sample(), BUGGY, "def renamed(x):\n    return x / 2\n")
    assert caught.value.reason == "function_gone_after_fix"


def test_extracting_a_test_method() -> None:
    code = (
        "class T:\n    def test_a(self):\n        assert 1\n\n    def test_b(self):\n        pass\n"
    )
    assert extract_tests(code, "t.py", ["test_a"]) == "def test_a(self):\n    assert 1"
    assert extract_tests(code, "t.py", ["test_none"]) == ""
    assert extract_tests("def broken(", "t.py", ["broken"]) == ""


# ---- repositories -------------------------------------------------------------------------------


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=cwd, capture_output=True, text=True, check=True,
    )  # fmt: skip
    return done.stdout.strip()


@pytest.fixture
def cached(tmp_path: Path):
    """A cache holding project `demo`: buggy commit, then fixed commit with its test."""
    work = tmp_path / "work"
    (work / "pkg").mkdir(parents=True)
    (work / "tests").mkdir()
    git(work, "init", "-q")
    (work / "pkg" / "core.py").write_text(BUGGY, encoding="utf-8", newline="\n")
    (work / "README.md").write_text("demo\n", encoding="utf-8")
    (work / "logo.png").write_bytes(b"\x89PNG")
    git(work, "add", ".")
    git(work, "commit", "-q", "-m", "buggy")
    buggy = git(work, "rev-parse", "HEAD")
    (work / "pkg" / "core.py").write_text(FIXED, encoding="utf-8", newline="\n")
    test = "from pkg.core import half\n\n\ndef test_half():\n    assert half(1) == 0.5\n"
    (work / "tests" / "test_core.py").write_text(test, encoding="utf-8", newline="\n")
    git(work, "add", ".")
    git(work, "commit", "-q", "-m", "fixed")
    fixed = git(work, "rev-parse", "HEAD")
    cache = BugRepoCache(tmp_path / "cache")
    subprocess.run(
        ["git", "clone", "-q", "--bare", str(work), str(cache.dir / "demo.git")], check=True
    )
    return cache, buggy, fixed


def test_show_reads_a_file_at_a_commit(cached) -> None:
    cache, buggy, fixed = cached
    assert "//" in cache.show("demo", buggy, "pkg/core.py")
    assert "//" not in cache.show("demo", fixed, "pkg/core.py")
    assert cache.show("demo", buggy, "tests/test_core.py") is None


def test_snapshot_writes_reviewable_files_only(cached, tmp_path: Path, settings: Settings) -> None:
    cache, buggy, _fixed = cached
    dest = tmp_path / "snap"
    dest.mkdir()
    assert cache.snapshot("demo", buggy, dest, settings.ingestion) == 2
    assert (dest / "pkg" / "core.py").read_text(encoding="utf-8") == BUGGY
    assert not (dest / "logo.png").exists()
    assert not (dest / "tests").exists()  # the test arrives with the fix, not before it


def test_commits_already_cached_need_no_network(cached) -> None:
    cache, buggy, fixed = cached
    assert cache.ensure_commits(sample(buggy_commit=buggy, fixed_commit=fixed)) == (buggy, fixed)


def test_short_id_resolves_locally(cached) -> None:
    cache, buggy, fixed = cached
    assert cache.ensure_commits(sample(buggy_commit=buggy[:7], fixed_commit=fixed))[0] == buggy


def test_resolving_a_bug(cached) -> None:
    cache, buggy, fixed = cached
    bug = resolve_bug(sample(buggy_commit=buggy, fixed_commit=fixed), cache)
    assert bug.gold[0].qualname == "half" and bug.file == "pkg/core.py"
    assert bug.failing_test.startswith("def test_half")
    assert bug.test_path == "tests/test_core.py"
    # Ground truth must not be able to reach a prompt through the failing test.
    assert "x / 2" not in bug.failing_test


def test_failing_test_that_cannot_be_found(cached) -> None:
    cache, buggy, fixed = cached
    with pytest.raises(IneligibleBug) as caught:
        resolve_bug(sample(buggy_commit=buggy, fixed_commit=fixed, test_names=["test_gone"]), cache)
    assert caught.value.reason == "failing_test_not_found"


@pytest.mark.parametrize(
    "bad", ["https://evil.example/a/b", "ext::sh -c id", "https://github.com/a/b;rm", ""]
)
def test_only_plain_github_urls_are_used(tmp_path: Path, bad: str) -> None:
    with pytest.raises(RepoCacheError):
        BugRepoCache(tmp_path).ensure_commits(sample(github_url=bad))


def test_commit_ids_are_checked_before_reaching_git(tmp_path: Path) -> None:
    with pytest.raises(RepoCacheError):
        BugRepoCache(tmp_path).ensure_commits(sample(buggy_commit="--upload-pack=evil"))


def test_project_names_cannot_leave_the_cache(tmp_path: Path) -> None:
    with pytest.raises(RepoCacheError):
        BugRepoCache(tmp_path).show("../evil", "a" * 40, "x.py")


def test_refuses_to_fill_the_disk(cached, monkeypatch: pytest.MonkeyPatch) -> None:
    cache, *_ = cached
    usage = type("Usage", (), {"free": 1024})
    monkeypatch.setattr("marl_agents.evaluation.datasets.bugsinpy_repo.shutil.disk_usage",
                        lambda _p: usage)  # fmt: skip
    with pytest.raises(DiskSpaceError):
        cache._fetch(cache.dir / "demo.git", "a" * 40, 1)


@pytest.mark.parametrize(
    ("name", "kind", "wanted"),
    [
        ("pkg/a.py", tarfile.REGTYPE, True),
        ("../../evil.py", tarfile.REGTYPE, False),
        ("/abs/evil.py", tarfile.REGTYPE, False),
        ("pkg/link.py", tarfile.SYMTYPE, False),
        ("pkg/con:tent.py", tarfile.REGTYPE, False),
        ("pkg/trailing.py ", tarfile.REGTYPE, False),
        ("build/a.py", tarfile.REGTYPE, False),
        ("pkg/image.png", tarfile.REGTYPE, False),
    ],
)
def test_untrusted_archive_members(name: str, kind: bytes, wanted: bool) -> None:
    member = tarfile.TarInfo(name)
    member.type = kind
    assert BugRepoCache._wanted(member, {".py"}, {"build"}, 1000) is wanted


def test_oversized_member_is_skipped() -> None:
    member = tarfile.TarInfo("pkg/a.py")
    member.size = 2000
    assert BugRepoCache._wanted(member, {".py"}, set(), 1000) is False
