"""The append-only journal: compatibility, torn writes and linear cost."""

import json

import pytest

from src import file_operations as operations
from src import undo_manager as journals


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(journals, "JOURNAL_DIR", tmp_path / "journals")
    return tmp_path


def moved_files(state, count=3):
    with journals.UndoManager() as manager:
        path = manager.journal_path
        for index in range(count):
            source = state / f"file-{index}"
            source.write_text(f"content {index}")
            operations.verified_transfer(source, state / "out" / source.name, "move", journal=manager)
    return path


def test_each_state_change_is_one_bounded_append(state, monkeypatch):
    appended = []
    real_append = journals._append_journal

    def recording_append(path, records):
        appended.append(sum(len(journals._line(r)) for r in records))
        real_append(path, records)

    monkeypatch.setattr(journals, "_append_journal", recording_append)
    path = moved_files(state, count=40)

    # One intent and one completion per file; no write grows with the session.
    assert len(appended) == 80
    assert max(appended) < 2 * min(appended) + 600
    assert path.stat().st_size == sum(appended)
    assert [a["state"] for a in journals.load_journal(path)] == ["completed"] * 40


def test_record_cut_short_by_a_crash_is_ignored_and_undo_still_works(state):
    path = moved_files(state)
    with path.open("a") as stream:
        stream.write('{"_update": "interrupted-wri')  # no newline: never durable

    actions = journals.load_journal(path)
    assert [a["state"] for a in actions] == ["completed"] * 3

    manager = journals.UndoManager()
    assert manager.list_sessions()[0]["count"] == 3
    assert manager.undo_session(path)
    assert sorted(p.read_text() for p in state.glob("file-*")) == [f"content {i}" for i in range(3)]


def test_corrupt_middle_record_is_reported_not_guessed(state):
    path = moved_files(state)
    lines = path.read_text().splitlines(keepends=True)
    lines.insert(1, "{not json}\n")
    path.write_text("".join(lines))

    with pytest.raises(ValueError):
        journals.load_journal(path)
    manager = journals.UndoManager()
    assert manager.list_sessions() == []
    assert not manager.undo_session(path)
    assert (state / "out" / "file-0").exists()


def test_earlier_array_format_journal_is_still_undoable(state):
    path = moved_files(state)
    path.write_text(json.dumps(journals.load_journal(path), indent=2))  # previous on-disk format

    manager = journals.UndoManager()
    assert manager.list_sessions()[0]["count"] == 3
    assert manager.undo_session(path)
    assert not (state / "out" / "file-0").exists()
    assert (state / "file-0").read_text() == "content 0"


def test_partial_undo_is_resumable_from_the_log(state):
    path = moved_files(state)
    (state / "file-1").write_text("new occupant")

    manager = journals.UndoManager()
    assert not manager.undo_session(path)
    states = {a["src"].rsplit("-", 1)[1]: a["state"] for a in journals.load_journal(path)}
    assert states == {"0": "undone", "1": "completed", "2": "undone"}
    assert "error" in journals.load_journal(path)[1]

    (state / "file-1").unlink()
    assert manager.undo_session(path)
    assert (state / "file-1").read_text() == "content 1"
