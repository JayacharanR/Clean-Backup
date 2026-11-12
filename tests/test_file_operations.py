"""Failure and concurrency regressions for the shared transfer boundary."""

from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import shutil

import pytest

from src import file_operations as operations


def _transfer(args):
    source, target, operation = args
    return str(operations.verified_transfer(source, target, operation))


@pytest.mark.parametrize("operation", ["copy", "move"])
def test_processes_cannot_replace_colliding_targets(tmp_path, operation):
    sources = [tmp_path / f"source-{n}" for n in range(6)]
    for n, source in enumerate(sources):
        source.write_bytes(bytes([n]) * 4096)
    target = tmp_path / "output" / "same.jpg"
    with ProcessPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(_transfer, [(s, target, operation) for s in sources]))
    assert len(set(results)) == len(sources)
    assert {Path(p).read_bytes() for p in results} == {
        bytes([n]) * 4096 for n in range(6)
    }
    assert all(s.exists() == (operation == "copy") for s in sources)


@pytest.mark.parametrize("failure", ["disk_full", "corrupt_copy", "changed_source"])
def test_failed_transfer_keeps_source_and_never_publishes(
    tmp_path, monkeypatch, failure
):
    source, target = tmp_path / "source", tmp_path / "output" / "file.jpg"
    source.write_bytes(b"original content")
    real_copy = shutil.copy2

    def faulty_copy(src, dst):
        real_copy(src, dst)
        if failure == "disk_full":
            raise OSError("No space left on device")
        if failure == "corrupt_copy":
            Path(dst).write_bytes(b"corrupt bytes")
        if failure == "changed_source":
            Path(src).write_bytes(b"new user edit")

    monkeypatch.setattr(operations.shutil, "copy2", faulty_copy)
    with pytest.raises(OSError):
        operations.verified_transfer(source, target, "move")
    assert source.exists()
    assert not target.exists()
    assert list(target.parent.iterdir()) == []


def test_symlink_and_same_file_are_refused(tmp_path):
    source = tmp_path / "original"
    source.write_text("keep")
    alias = tmp_path / "alias"
    alias.symlink_to(source)
    with pytest.raises(OSError):
        operations.verified_transfer(alias, tmp_path / "copy")
    with pytest.raises(operations.FileConflictError):
        operations.verified_transfer(source, alias)
    assert source.read_text() == "keep"


def test_existing_and_dangling_targets_are_never_replaced(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    source.write_text("new")
    target.symlink_to(tmp_path / "missing")
    with pytest.raises(FileExistsError):
        operations.verified_transfer(source, target, collision="error")
    actual = operations.verified_transfer(source, target)
    assert actual != target
    assert target.is_symlink()
    assert actual.read_text() == "new"


def test_unsupported_publication_fails_without_losing_source(tmp_path, monkeypatch):
    source, target = tmp_path / "source", tmp_path / "target"
    source.write_text("keep")

    def unsupported(*args, **kwargs):
        raise OSError("Hard links unsupported")

    monkeypatch.setattr(operations.os, "link", unsupported)
    with pytest.raises(OSError):
        operations.verified_transfer(source, target, "move")
    assert source.read_text() == "keep"
    assert not target.exists()
    assert not list(tmp_path.glob(".clean-backup-*"))


def test_move_source_is_retained_if_it_changes_during_publication(
    tmp_path, monkeypatch
):
    source, target = tmp_path / "source", tmp_path / "target"
    source.write_text("original")
    publish = operations._publish

    def changed(temporary, destination):
        publish(temporary, destination)
        source.write_text("new edit")

    monkeypatch.setattr(operations, "_publish", changed)
    with pytest.raises(operations.FileConflictError):
        operations.verified_transfer(source, target, "move")
    assert source.read_text() == "new edit"
    assert target.read_text() == "original"
