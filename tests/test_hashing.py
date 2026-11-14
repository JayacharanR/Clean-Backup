"""Single-decode hashing and grouping, through Rust and the Python fallback."""

import pytest
from PIL import Image, ImageDraw

from src import phash


def photo(path, size=(320, 240), quality=95, seed=0):
    image = Image.new("RGB", (320, 240), (35 + seed * 60, 125, 154))
    draw = ImageDraw.Draw(image)
    draw.polygon([(0, 239), (120 + seed * 40, 40), (210, 239)], fill="#183e39")
    draw.ellipse((215 - seed * 90, 20, 280 - seed * 90, 85), fill="#ffd372")
    image.resize(size).save(path, quality=quality)
    return str(path)


@pytest.fixture
def library(tmp_path):
    return {
        "large": photo(tmp_path / "large.jpg"),
        "small": photo(tmp_path / "small.jpg", size=(160, 120), quality=70),
        "other": photo(tmp_path / "other.jpg", seed=2),
        "broken": str(tmp_path / "broken.jpg"),
    }


def test_hash_and_resolution_come_from_one_call(library, tmp_path):
    (tmp_path / "broken.jpg").write_bytes(b"not an image")
    result = phash.compute_hashes_with_resolution(list(library.values()))

    assert set(result) == {library["large"], library["small"], library["other"]}
    assert result[library["large"]][1] == 320 * 240
    assert result[library["small"]][1] == 160 * 120
    assert result[library["large"]][0] == phash.compute_hash(library["large"])


def test_grouping_precomputed_hashes_matches_scanning_paths(library):
    paths = [library["large"], library["small"], library["other"]]
    from_paths = phash.find_duplicates_from_paths(paths, 10)
    from_hashes = phash.group_hashes(phash.compute_hashes_with_resolution(paths), 10)

    def normal(groups):
        return sorted((sorted(g.paths), g.best) for g in groups)

    assert normal(from_hashes) == normal(from_paths)
    assert normal(from_hashes) == [([library["large"], library["small"]], library["large"])]


def test_python_fallback_groups_the_same_records(monkeypatch):
    records = {
        "/a/small.jpg": ("ff00ff00ff00ff00", 100),
        "/a/large.jpg": ("ff00ff00ff00ff01", 400),
        "/a/other.jpg": ("00ff00ff00ff00ff", 900),
    }
    rust = phash.group_hashes(records, 2)
    monkeypatch.setattr(phash, "_USE_RUST", False)
    fallback = phash.group_hashes(records, 2)

    for groups in (rust, fallback):
        assert [(sorted(g.paths), g.best) for g in groups] == [
            (["/a/large.jpg", "/a/small.jpg"], "/a/large.jpg")
        ]


def test_fallback_hashing_reports_resolution(library, monkeypatch):
    monkeypatch.setattr(phash, "_USE_RUST", False)
    result = phash.compute_hashes_with_resolution([library["small"]])
    assert result[library["small"]][1] == 160 * 120
