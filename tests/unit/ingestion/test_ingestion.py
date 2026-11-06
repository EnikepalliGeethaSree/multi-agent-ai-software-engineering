import zipfile
from pathlib import Path

import pytest

from marl_agents.config import IngestionSettings
from marl_agents.ingestion import (
    FileKind,
    IngestionError,
    UnsafeArchiveError,
    load_directory,
    load_files,
    load_repository,
    load_snippet,
    safe_extract_zip,
)
from marl_agents.ingestion.models import classify


def _zip(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path


# ---- safe ZIP extraction -------------------------------------------------------------------


def test_extracts_and_unwraps_single_top_level_folder(tmp_path: Path) -> None:
    z = _zip(tmp_path / "a.zip", {"proj-main/app.py": b"x = 1\n", "proj-main/README.md": b"# hi"})
    root = safe_extract_zip(z, tmp_path / "out", IngestionSettings())
    assert root.name == "proj-main"
    assert (root / "app.py").read_text() == "x = 1\n"


@pytest.mark.parametrize("evil", ["../evil.py", "a/../../evil.py", "/abs/evil.py", "C:/evil.py"])
def test_rejects_path_traversal_and_absolute_paths(tmp_path: Path, evil: str) -> None:
    z = tmp_path / "evil.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr(zipfile.ZipInfo(evil), b"pwned")
    with pytest.raises(UnsafeArchiveError):
        safe_extract_zip(z, tmp_path / "out", IngestionSettings())
    assert not (tmp_path / "evil.py").exists()


def test_skips_symlink_members(tmp_path: Path) -> None:
    z = tmp_path / "link.zip"
    with zipfile.ZipFile(z, "w") as zf:
        info = zipfile.ZipInfo("repo/link")
        info.external_attr = 0o120777 << 16  # symlink mode
        zf.writestr(info, "/etc/passwd")
        zf.writestr("repo/ok.py", "y = 2\n")
    root = safe_extract_zip(z, tmp_path / "out", IngestionSettings())
    assert (root / "ok.py").exists()
    assert not (root / "link").exists()


def test_rejects_zip_bomb_by_compression_ratio(tmp_path: Path) -> None:
    z = _zip(tmp_path / "bomb.zip", {"zeros.txt": b"\0" * 1_000_000})
    with pytest.raises(UnsafeArchiveError, match="compression ratio"):
        safe_extract_zip(z, tmp_path / "out", IngestionSettings())


def test_rejects_too_many_files_and_oversized_totals(tmp_path: Path) -> None:
    z = _zip(tmp_path / "many.zip", {f"f{i}.py": b"x=1\n" for i in range(5)})
    with pytest.raises(UnsafeArchiveError, match="files"):
        safe_extract_zip(z, tmp_path / "o1", IngestionSettings(max_files=3))
    with pytest.raises(UnsafeArchiveError, match="expands"):
        safe_extract_zip(z, tmp_path / "o2", IngestionSettings(max_uncompressed_bytes=10))


def test_skips_oversized_member_but_keeps_the_rest(tmp_path: Path) -> None:
    z = _zip(tmp_path / "big.zip", {"r/big.py": b"#" + b"a" * 5000, "r/small.py": b"x=1\n"})
    root = safe_extract_zip(z, tmp_path / "out", IngestionSettings(max_file_bytes=1000))
    assert (root / "small.py").exists() and not (root / "big.py").exists()


def test_rejects_non_zip(tmp_path: Path) -> None:
    bad = tmp_path / "x.zip"
    bad.write_bytes(b"not a zip")
    with pytest.raises(UnsafeArchiveError):
        safe_extract_zip(bad, tmp_path / "out", IngestionSettings())


# ---- directory loading ------------------------------------------------------------------------


def test_load_directory_filters_ignored_binary_and_unknown_files(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text("x = 1\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_mod.py").write_text("def test(): pass\n")
    (tmp_path / "README.md").write_text("# r")
    (tmp_path / "conf.yaml").write_text("a: 1")
    (tmp_path / "image.png").write_bytes(b"\x89PNG\0\0")
    (tmp_path / "blob.py").write_bytes(b"x\0y")  # binary disguised as .py
    for ignored in (".git", "node_modules", "__pycache__", ".venv", "x.egg-info"):
        (tmp_path / ignored).mkdir()
        (tmp_path / ignored / "junk.py").write_text("bad = 1\n")

    repo = load_directory(tmp_path)
    paths = {f.path for f in repo.files}
    assert paths == {"pkg/mod.py", "tests/test_mod.py", "README.md", "conf.yaml"}
    assert repo.by_path["tests/test_mod.py"].kind is FileKind.TEST
    assert repo.by_path["README.md"].kind is FileKind.DOC
    assert repo.by_path["conf.yaml"].kind is FileKind.CONFIG
    assert repo.skipped["binary"] == 1


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        ("app/models.py", FileKind.CODE),
        ("tests/unit/test_x.py", FileKind.TEST),
        ("app/test_x.py", FileKind.TEST),
        ("app/x_test.py", FileKind.TEST),
        ("conftest.py", FileKind.TEST),
        ("docs/guide.rst", FileKind.DOC),
        ("pyproject.toml", FileKind.CONFIG),
    ],
)
def test_classify(path: str, kind: FileKind) -> None:
    assert classify(path) is kind


def test_resolve_path_handles_llm_variants(make_repo) -> None:  # type: ignore[no-untyped-def]
    repo = make_repo({"app/auth.py": "x=1\n", "app/sub/util.py": "y=2\n", "lib/util.py": "z=3\n"})
    assert repo.resolve_path("app/auth.py") == "app/auth.py"
    assert repo.resolve_path("./app/auth.py") == "app/auth.py"
    assert repo.resolve_path("app\\auth.py") == "app/auth.py"
    assert repo.resolve_path("`auth.py`") == "app/auth.py"  # unique suffix
    assert repo.resolve_path(str(repo.root / "app" / "auth.py")) == "app/auth.py"
    assert repo.resolve_path("util.py") is None  # ambiguous
    assert repo.resolve_path("missing.py") is None


def test_repo_id_is_content_hash(make_repo) -> None:  # type: ignore[no-untyped-def]
    a = make_repo({"m.py": "x = 1\n"})
    b = make_repo({"m.py": "x = 1\n"})
    c = make_repo({"m.py": "x = 2\n"})
    assert a.repo_id == b.repo_id != c.repo_id


def test_snippet_and_files_workspaces_are_cleaned_up(settings) -> None:  # type: ignore[no-untyped-def]
    repo = load_snippet("print(1)\n", "../../evil.py", settings.ingestion)
    assert [f.path for f in repo.files] == ["evil.py"]  # directory components stripped
    ws = repo.workspace
    assert ws is not None and ws.exists()
    repo.cleanup()
    assert not ws.exists()


@pytest.mark.parametrize("bad", ["../x.py", "/abs.py", "C:/x.py", "a/../../b.py"])
def test_load_files_rejects_unsafe_paths(settings, bad: str) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(IngestionError):
        load_files({bad: "x=1"}, settings.ingestion)


def test_load_repository_dispatch(tmp_path: Path, settings) -> None:  # type: ignore[no-untyped-def]
    z = _zip(tmp_path / "r.zip", {"r/a.py": b"a = 1\n"})
    repo = load_repository(z, settings.ingestion)
    assert [f.path for f in repo.files] == ["a.py"]
    assert repo.workspace is not None
    repo.cleanup()
    with pytest.raises(IngestionError):
        load_repository(tmp_path / "nope.txt", settings.ingestion)
