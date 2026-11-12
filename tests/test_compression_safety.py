"""Compression publication must preserve inputs and existing outputs."""

from pathlib import Path
from subprocess import CompletedProcess

from PIL import Image
import pytest

from src import compressor


@pytest.fixture
def photo(tmp_path):
    source = tmp_path / "original.jpg"
    Image.new("RGB", (100, 80), "blue").save(source, quality=95)
    return source


@pytest.mark.parametrize("existing", ["source", "other_file", "symlink"])
def test_image_compression_never_replaces_existing_content(photo, existing):
    output = photo.parent / "output.jpg"
    before = photo.read_bytes()
    if existing == "source":
        output = photo
    elif existing == "other_file":
        output.write_bytes(b"previous output")
    else:
        output.symlink_to(photo)
    expected = output.read_bytes()
    assert not compressor.compress_image(photo, output, level=3)
    assert output.read_bytes() == expected
    assert photo.read_bytes() == before
    assert not list(photo.parent.glob(".clean-backup-*"))


def test_image_output_is_decodable_and_source_unchanged(photo):
    output = photo.parent / "output.jpg"
    before = photo.read_bytes()
    assert compressor.compress_image(photo, output)
    with Image.open(output) as image:
        image.load()
        assert image.size == (100, 80)
    assert photo.read_bytes() == before
    assert not list(photo.parent.glob(".clean-backup-*"))


def test_encoder_failure_does_not_leave_partial_final_output(photo, monkeypatch):
    output = photo.parent / "output.jpg"
    before = photo.read_bytes()

    def interrupted(image, path, **kwargs):
        Path(path).write_bytes(b"partial")
        raise OSError("Disk full")

    monkeypatch.setattr(Image.Image, "save", interrupted)
    assert not compressor.compress_image(photo, output)
    assert photo.read_bytes() == before
    assert not output.exists()
    assert not list(photo.parent.glob(".clean-backup-*"))


def test_concurrent_output_is_not_replaced_at_publication(photo, monkeypatch):
    output = photo.parent / "output.jpg"
    encode = compressor._encode_image

    def race(source, temporary, level):
        result = encode(source, temporary, level)
        output.write_text("other process created this")
        return result

    monkeypatch.setattr(compressor, "_encode_image", race)
    assert not compressor.compress_image(photo, output)
    assert output.read_text() == "other process created this"


@pytest.mark.parametrize("nested", ["same", "inside", "outside"])
def test_directory_compression_refuses_overlapping_roots(photo, nested):
    source = photo.parent
    output = {"same": source, "inside": source / "compressed", "outside": source.parent}[nested]
    before = photo.read_bytes()
    with pytest.raises(ValueError, match="overlap"):
        compressor.compress_files(source, output)
    assert photo.read_bytes() == before


@pytest.mark.parametrize("success", [True, False])
def test_ffmpeg_only_writes_private_staging_output(tmp_path, monkeypatch, success):
    source, output = tmp_path / "input.mp4", tmp_path / "output.mp4"
    source.write_bytes(b"fixture video")

    def ffmpeg(command, **kwargs):
        if "-version" in command:
            return CompletedProcess(command, 0)
        temporary = Path(command[-1])
        assert temporary != output and temporary != source
        assert not output.exists()
        temporary.write_bytes(b"encoded video" if success else b"partial")
        return CompletedProcess(command, 0 if success else 1, stderr="encoder failed")

    monkeypatch.setattr(compressor.subprocess, "run", ffmpeg)
    assert compressor.compress_video(source, output) == success
    assert source.read_bytes() == b"fixture video"
    assert output.exists() == success
    assert not list(tmp_path.glob(".clean-backup-*"))


def test_ffmpeg_never_runs_for_existing_destination(tmp_path, monkeypatch):
    source, output = tmp_path / "input.mp4", tmp_path / "output.mp4"
    source.write_bytes(b"video")
    output.write_bytes(b"keep existing output")

    def unexpected(*args, **kwargs):
        pytest.fail("FFmpeg must not run for an occupied target")

    monkeypatch.setattr(compressor.subprocess, "run", unexpected)
    assert not compressor.compress_video(source, output)
    assert output.read_bytes() == b"keep existing output"
