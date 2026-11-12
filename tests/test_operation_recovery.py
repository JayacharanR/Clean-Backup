"""Exercise recovery preconditions and interrupted journal transitions."""

from concurrent.futures import ThreadPoolExecutor
import json
import multiprocessing
import os
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from src import file_operations as operations
from src import undo_manager as journals


def _crash_transfer(root, operation, stage):
    """Exit without finally blocks to exercise the actual persisted intent."""
    manager = journals.UndoManager(root / "journals")
    manager.start_session()
    if stage == "before_publication":
        prepare = manager.prepare_action

        def crash(*args):
            prepare(*args)
            os._exit(73)

        manager.prepare_action = crash
    elif stage == "after_publication":
        publish = operations._publish

        def crash(*args):
            publish(*args)
            os._exit(73)

        operations._publish = crash
    else:
        manager.complete_action = lambda *args: os._exit(73)
    operations.verified_transfer(
        root / "source", root / "output", operation, journal=manager
    )


@pytest.mark.parametrize("operation", ["copy", "move"])
@pytest.mark.parametrize(
    "stage", ["before_publication", "after_publication", "before_completion"]
)
def test_recovery_after_process_exit(state, operation, stage):
    source = state / "source"
    source.write_text("original")
    process = multiprocessing.get_context("spawn").Process(
        target=_crash_transfer, args=(state, operation, stage)
    )
    process.start()
    process.join(timeout=15)
    if process.is_alive():
        process.kill()
        process.join()
        pytest.fail("Crash probe did not exit")
    assert process.exitcode == 73
    manager = journals.UndoManager()
    sessions = manager.list_sessions()
    assert len(sessions) == 1
    assert manager.undo_session(sessions[0]["path"])
    assert source.read_text() == "original"
    assert not (state / "output").exists()


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(journals, "JOURNAL_DIR", tmp_path / "journals")
    return tmp_path


def transfer(state, operation="copy"):
    source, target = state / "source", state / "out" / "file"
    source.write_text("original")
    with journals.UndoManager() as manager:
        path = manager.journal_path
        operations.verified_transfer(source, target, operation, journal=manager)
    return source, target, manager, path


@pytest.mark.parametrize("operation", ["copy", "move"])
def test_undo_roundtrip(state, operation):
    source, target, manager, path = transfer(state, operation)
    assert manager.undo_session(path)
    assert source.read_text() == "original"
    assert not target.exists()
    assert not path.exists()


@pytest.mark.parametrize("operation", ["copy", "move"])
def test_undo_retains_edited_output_and_journal(state, operation):
    source, target, manager, path = transfer(state, operation)
    target.write_text("new user edit")
    assert not manager.undo_session(path)
    assert target.read_text() == "new user edit"
    assert path.exists()
    assert manager.list_sessions()[0]["count"] == 1


def test_undo_move_conflict_can_be_retried(state):
    source, target, manager, path = transfer(state, "move")
    source.write_text("new file at old location")
    assert not manager.undo_session(path)
    assert source.read_text() == "new file at old location"
    assert target.read_text() == "original"
    source.rename(state / "new-file-kept")
    assert manager.undo_session(path)
    assert source.read_text() == "original"
    assert (state / "new-file-kept").read_text() == "new file at old location"


@pytest.mark.parametrize("change", ["missing", "edited"])
def test_copy_undo_keeps_last_original_content(state, change):
    source, target, manager, path = transfer(state)
    if change == "missing":
        source.unlink()
    else:
        source.write_text("different content")
    assert not manager.undo_session(path)
    assert target.read_text() == "original"
    assert path.exists()


def test_intent_failure_prevents_publication_and_source_removal(state, monkeypatch):
    source, target = state / "source", state / "target"
    source.write_text("keep")
    with journals.UndoManager() as manager:

        def full_disk():
            raise OSError("Journal disk full")

        monkeypatch.setattr(manager, "_save_journal", full_disk)
        with pytest.raises(OSError):
            operations.verified_transfer(source, target, "move", journal=manager)
    assert source.read_text() == "keep"
    assert not target.exists()


@pytest.mark.parametrize("operation", ["copy", "move"])
def test_pending_intent_recovers_after_completion_write_failure(
    state, monkeypatch, operation
):
    source, target = state / "source", state / "target"
    source.write_text("original")
    with journals.UndoManager() as manager:
        path = manager.journal_path

        def failed_commit(*args):
            raise OSError("Completion write failed")

        monkeypatch.setattr(manager, "complete_action", failed_commit)
        with pytest.raises(OSError):
            operations.verified_transfer(source, target, operation, journal=manager)
    assert json.loads(path.read_text())[0]["state"] == "prepared"
    assert target.read_text() == "original"
    assert manager.undo_session(path)
    assert source.read_text() == "original"
    assert not target.exists()


def test_partial_undo_does_not_replay_completed_actions(state):
    with journals.UndoManager() as manager:
        path = manager.journal_path
        for name in ("a", "b"):
            (state / name).write_text(name)
            operations.verified_transfer(
                state / name, state / "out" / name, "move", journal=manager
            )
    (state / "a").write_text("new occupant")
    assert not manager.undo_session(path)
    assert (state / "b").read_text() == "b"
    (state / "a").unlink()
    assert manager.undo_session(path)
    assert (state / "a").read_text() == "a"
    assert (state / "b").read_text() == "b"


def test_legacy_path_only_journal_is_preserved_for_manual_review(state):
    source, target = state / "source", state / "target"
    target.write_text("possibly edited")
    path = state / "legacy.json"
    path.write_text(
        json.dumps([{"action": "move", "src": str(source), "dst": str(target)}])
    )
    assert not journals.UndoManager().undo_session(path)
    assert target.read_text() == "possibly edited"
    assert not source.exists()
    assert path.exists()


def test_active_sessions_are_not_available_for_undo(state):
    with journals.UndoManager() as manager:
        (state / "a").write_text("a")
        operations.verified_transfer(state / "a", state / "b", journal=manager)
        assert manager.list_sessions() == []
        assert not journals.UndoManager().undo_session(manager.journal_path)
        path = manager.journal_path
    assert manager.undo_session(path)


def test_concurrent_session_ids_and_records_are_independent(state):
    def run(n):
        source = state / f"source-{n}"
        source.write_text(str(n))
        with journals.UndoManager() as manager:
            path = manager.journal_path
            operations.verified_transfer(source, state / f"target-{n}", journal=manager)
            return path

    with ThreadPoolExecutor(max_workers=4) as pool:
        paths = list(pool.map(run, range(8)))
    assert len(set(paths)) == 8
    for path in paths:
        records = json.loads(path.read_text())
        assert len(records) == 1 and records[0]["state"] == "completed"


@pytest.mark.parametrize("operation", ["copy", "move"])
def test_organizer_keeps_distinct_names_and_colliding_basenames(state, operation):
    from PIL import Image
    from src.organiser import organise_files

    source, output = state / "source", state / "out"
    paths = [
        source / "a" / "photo.jpg",
        source / "b" / "photo.jpg",
        source / "a" / "photo (1).jpg",
    ]
    for path, color in zip(paths, ("red", "blue", "green")):
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (30, 30), color).save(path)
    expected = {p.read_bytes() for p in paths}
    stats = organise_files(source, output, operation, check_name_duplicates=True)
    assert stats["processed"] == 3 and stats["errors"] == 0
    assert {p.read_bytes() for p in output.rglob("*.jpg")} == expected
    manager = journals.UndoManager()
    assert manager.undo_session(manager.list_sessions()[0]["path"])
    assert {p.read_bytes() for p in paths} == expected


@pytest.mark.parametrize("nested", ["same", "inside", "outside"])
def test_organizer_rejects_overlapping_roots_before_mutation(state, nested):
    from src.organiser import organise_files

    source = state / "photos"
    source.mkdir()
    target = {"same": source, "inside": source / "out", "outside": state}[nested]
    with pytest.raises(ValueError, match="overlap"):
        organise_files(source, target)
    assert not list(state.rglob("journal_*.json"))


def test_legacy_duplicate_report_releases_its_session(state, monkeypatch):
    from src import duplicate_handler

    managers = []

    def manager_factory():
        manager = journals.UndoManager()
        managers.append(manager)
        return manager

    monkeypatch.setattr(duplicate_handler, "UndoManager", manager_factory)
    monkeypatch.setattr(duplicate_handler, "scan_for_duplicates", lambda *args: [])
    for _ in range(2):
        duplicate_handler.handle_duplicates(str(state), action="report")
    assert all(m.session_id is None and m._session_fd is None for m in managers)


@pytest.mark.parametrize("callback_failure", [False, True])
def test_legacy_classification_releases_journal_on_return_or_error(
    state, monkeypatch, callback_failure
):
    from src.classify import apply_org

    source = state / "photo.jpg"
    source.write_bytes(b"original fixture")
    manager = journals.UndoManager()
    monkeypatch.setattr(apply_org, "UndoManager", lambda: manager)
    monkeypatch.setattr(
        apply_org, "get_run_config", lambda _: {"multi_category": "tags"}
    )
    monkeypatch.setattr(
        apply_org,
        "get_all_tags_for_run",
        lambda _: [
            {"path": str(source), "category_label": "example"},
        ],
    )
    cursor = SimpleNamespace(execute=lambda *args: None, fetchone=lambda: None)
    monkeypatch.setattr(
        apply_org,
        "_get_conn",
        lambda: nullcontext(SimpleNamespace(cursor=lambda: cursor)),
    )

    def failed_callback(*args):
        raise RuntimeError("Callback failed")

    if callback_failure:
        with pytest.raises(RuntimeError, match="Callback failed"):
            apply_org.apply_classification(
                "test", state / "out", "copy", failed_callback
            )
    else:
        result = apply_org.apply_classification("test", state / "out", "copy")
        assert result["session_id"]
    assert manager.session_id is None and manager._session_fd is None
    sessions = manager.list_sessions()
    assert len(sessions) == 1
    assert manager.undo_session(sessions[0]["path"])
    assert source.read_bytes() == b"original fixture"
