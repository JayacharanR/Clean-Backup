# Demo GIF

[`demo.gif`](demo.gif) is a looping, 32-second walkthrough made from eight screen captures of the running React/Flask app. The captures show real operations on a separate sample library, database, configuration directory, and undo journal. Captions and pauses were added for readability; the app results were not altered.

## What the recording shows

1. **Scan:** nine JPEGs are hashed by the Rust `phash_rs` backend. The scan finds three groups and six duplicates at sensitivity 10.
2. **Review:** compare duplicate cards and open the image preview. Each group contains an original, a half-resolution copy, and a recompressed copy.
3. **Organize:** copy all nine images into `2025/March`, `2025/April`, and `2025/May`, using their EXIF dates. The app reports nine processed images and zero errors. Duplicate checks are unchecked for this step so every sample is copied.
4. **Undo:** revert the session containing nine copy operations. Filesystem checks confirmed that all nine output copies were removed and all nine source images remained intact.

This recording covers local deduplication, review, organization, and undo. It does not demonstrate classification, face recognition, or cloud sync.

## Sample images

The sample library uses these Pexels photos, downloaded under the [Pexels License](https://www.pexels.com/license/):

| Local filename | Source |
|---|---|
| `mountains.jpg` | [Pexels photo 3278215](https://www.pexels.com/photo/3278215/) |
| `food.jpg` | [Pexels photo 1640777](https://www.pexels.com/photo/1640777/) |
| `puppies.jpg` | [Pexels photo 1108099](https://www.pexels.com/photo/1108099/) |

Each original was saved at JPEG quality 94 with an EXIF `DateTimeOriginal` of March 15, April 15, or May 15, 2025. Pillow produced a half-resolution variant at quality 72 and a full-resolution variant at quality 32. No personal media or cloud credentials were used.

## Re-record locally

Complete the [local setup](../README.md#local-development), build the frontend, and prepare a disposable sample folder containing the photos and variants above. Use absolute paths for the following environment variables. Run from the disposable directory so relative log and undo files also stay separate:

```bash
# Set this to the absolute path of your clone.
REPO=/absolute/path/to/Clean-Backup
CAPTURE_DIR=$(mktemp -d /tmp/clean-backup-demo.XXXXXX)
mkdir -p "$CAPTURE_DIR/library" "$CAPTURE_DIR/organized" "$CAPTURE_DIR/config"
# Put the sample photos and variants into "$CAPTURE_DIR/library".
cd "$CAPTURE_DIR"
CLEAN_BACKUP_DB_PATH="$CAPTURE_DIR/showcase.db" \
CLEAN_BACKUP_CONFIG_DIR="$CAPTURE_DIR/config" \
CLEAN_BACKUP_PORT=8080 \
"$REPO/.venv/bin/python" "$REPO/main.py" --web
```

Open `http://localhost:8080`. Use the sample library for **Duplicates**, inspect a group and its preview, then use **Organize** with **Copy** and the disposable `organized` destination. Check the completed summary, open **Undo History**, and revert that sample session. Do not set `DEMO_MODE=true`: the read-only deployment mode blocks organization and undo.

Capture the eight states listed above at a consistent desktop viewport. The committed GIF uses 960 × 660 pixels including its caption strip, eight frames with pauses of 3, 4.5, 5, 4, 3.5, 4.5, 3.5, and 4 seconds, and an infinite loop. It is under 1 MB and uses a repository-relative Markdown image link so it displays directly on GitHub.

Verify a replacement before committing it:

```python
from pathlib import Path
from PIL import Image

path = Path("docs/demo.gif")
with Image.open(path) as gif:
    assert gif.is_animated and gif.n_frames == 8
    assert gif.info["loop"] == 0
    assert gif.size == (960, 660)
    duration = 0
    for index in range(gif.n_frames):
        gif.seek(index)
        duration += gif.info["duration"]
    assert duration == 32000
assert path.stat().st_size < 1_000_000
```

Inspect every frame visually as well. Confirm that images load, text remains legible, the results match the operations, and the output directory is empty after undo.
