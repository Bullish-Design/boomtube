from __future__ import annotations

from pathlib import Path

import pytest

from boomtube.hashing import files_identical


def test_files_identical_true(tmp_path: Path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.write_text("same content", encoding="utf-8")
    b.write_text("same content", encoding="utf-8")
    assert files_identical(a, b) is True


def test_files_identical_different_size_false(tmp_path: Path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.write_text("small", encoding="utf-8")
    b.write_text("much larger content here", encoding="utf-8")
    assert files_identical(a, b) is False


def test_files_identical_same_size_different_content_false(tmp_path: Path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.write_text("x" * 10, encoding="utf-8")
    b.write_text("y" * 10, encoding="utf-8")
    assert files_identical(a, b) is False


def test_files_identical_missing_file_false(tmp_path: Path):
    assert files_identical(tmp_path / "ghost", tmp_path / "ghost2") is False


def test_files_identical_toctou_tolerant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """F11: a file vanishing between stat and hash yields False, not an exception."""
    import boomtube.hashing as H

    a = tmp_path / "a"
    b = tmp_path / "b"
    a.write_text("x" * 10, encoding="utf-8")
    b.write_text("y" * 10, encoding="utf-8")

    def boom(path, **kwargs):
        raise FileNotFoundError(path)

    monkeypatch.setattr(H, "sha256", boom)
    assert files_identical(a, b) is False
