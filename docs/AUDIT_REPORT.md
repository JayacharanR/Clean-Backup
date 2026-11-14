# Engineering audit — 14 November 2026

Scope: the whole repository on branch `codex/audit-file-safety` — Python backend
(`src/`, `main.py`, `deploy/`), Rust extension (`phash_rs/`), React frontend
(`web/`), Docker and CI configuration, dependencies and documentation.

This continues the file-safety work recorded in
[AUDIT_REPAIRS.md](AUDIT_REPAIRS.md). Every "fixed" item below was reproduced
first (a regression test that fails on the old code, or a measurement) and
re-verified afterwards. Items that were not exercised are listed as such.
Nothing here claims the project is free of defects.

## Summary

| Area | Before | After |
|---|---|---|
| Python tests | 65 pass | 117 pass (52 new) |
| Rust tests | 3 pass | 6 pass |
| Lint (Ruff, rustfmt, Clippy `-D warnings`) | clean | clean |
| Known advisories in pinned Python packages (OSV) | 84 matches in 7 packages | 0 |
| npm advisories, runtime / build tooling | 0 / 8 | 0 / 2 |
| Web duplicate scan, 320 six-megapixel JPEGs | 6.03 s | 2.79 s (identical hashes and groups) |
| Organize 2,000 small files (copy) | 61.2 s | 9.4 s |
| Undo 1,000 moved files | 49.8 s | 1.7 s |
| Rust extension (`phash_rs.abi3.so`) | 2.46 MB | 1.85 MB |
| Rust dependency tree (`cargo tree` lines) | 195 | 98 |

## Findings

Severity reflects impact on a user running the app as documented.

### Security

| # | Severity | Finding | Status |
|---|---|---|---|
| S1 | Critical | The API has no login, answered every origin with `Access-Control-Allow-Origin: *`, and listened on `0.0.0.0`. Any website open in the user's browser could start a scan of an arbitrary directory, read files from it and permanently delete them. | **Fixed.** Wildcard CORS removed; state-changing requests from another origin and requests with an unexpected `Host` (DNS rebinding) are refused; default listen address is `127.0.0.1`; compose publishes on loopback. Verified by tests and against a running server with `curl`. |
| S2 | High | `GET /api/image` fell back to sending the raw file when Pillow could not decode it, so any file under a scanned directory (keys, documents) was readable. | **Fixed.** Only media extensions are served; undecodable files are sent as an attachment with `nosniff`. |
| S3 | High | In `DEMO_MODE` (a public instance) the scan and classify endpoints accepted any server directory; combined with S2 this exposed the host's files to anonymous visitors. | **Fixed.** Demo mode can only read `CLEAN_BACKUP_MEDIA_PATH`. |
| S4 | High | `PATCH /api/watchers/<id>` interpolated JSON keys into SQL as column names (SQL injection through identifiers). `update_sync_run` had the same pattern, reachable only from internal callers. | **Fixed.** Fixed set of updatable columns; unknown fields return 400. |
| S5 | Medium | Google Drive queries were built with unescaped file names: a name containing `'` broke the query or changed which remote file `delete`/`verify` matched. | **Fixed** (escaping verified with a fake service; not exercised against Google). |
| S6 | Medium | The OAuth URL carried two `state` parameters (the library's and a second one appended by the endpoint), and the callback error page reflected exception text as HTML. Pending flows were never evicted. | **Fixed** by construction; the single-state URL and escaping are tested, the full flow against Google is **not verified**. |
| S7 | Medium | The fallback credential key and token files were created with default permissions and restricted afterwards. | **Fixed.** Created owner-only (0600) and replaced atomically. |
| S8 | Medium | Trash used `rename` to a name derived from the path and the current second: trashing a second file with the same path within a second silently replaced the first, and it failed across filesystems. Malformed selections raised a 500. | **Fixed.** Trash uses the verified, journaled transfer and is undoable; delete accepts images only. |
| S9 | Medium | Classification models were downloaded from a mutable branch without verification, although the script's documentation said checksums were verified. | **Fixed.** SHA-256 pinned (upstream files downloaded on audit day match the July copies byte for byte); a mismatch deletes the file and fails the build. |
| S10 | Medium | `docker-compose.yml` referenced `ghcr.io/charan/clean-backup`, a namespace the project does not publish to; `docker compose pull` would fetch someone else's image if it existed. | **Fixed** (`ghcr.io/jayacharanr/clean-backup`, matching the release workflow). |
| S11 | Low | Local image builds copied `.env`, `logs/`, and the personal scratch folders `d/` and `s/` (about 225 MB of media) into the image. | **Fixed** in `.dockerignore`. |
| S12 | Low | `GET /api/face-crop` built a file path from an unvalidated `id`. Not exploitable on Linux as written. | **Fixed** (numeric ids only). |
| S13 | — | 84 advisory matches in pinned Python packages, 40+ of them in Pillow, which parses untrusted image files. | **Fixed** by targeted upgrades (see Dependencies). |

No secrets were found in tracked files or history-visible configuration.
`credentials.json` and `.env` exist locally, are git-ignored, and `.env` is
identical to `.env.example`. No rotation is required as a result of this audit.

### Correctness

| # | Severity | Finding | Status |
|---|---|---|---|
| C1 | High | Capture dates were read only from the top-level EXIF IFD. Cameras store `DateTimeOriginal` in the Exif sub-IFD, so real photos were organized by file modification time. The existing tests passed because their fixtures wrote the tag in the non-standard location. The classifier had the same defect for ISO and exposure, so night detection never saw exposure data. | **Fixed**, with fixtures written the way cameras write them. |
| C2 | High | Classification apply called the job's `(percent, message)` progress callback with one argument. Every run moved or copied files, then failed with a `TypeError` that was swallowed and reported as a *completed* job. It also filed photos under the month they were catalogued, used unverified copy/move, and turned the label "Nature / Scenery" into nested `Nature /` and ` Scenery` folders. | **Fixed.** Capture date, verified journaled transfer, one safe folder name per category, undo verified end to end. |
| C3 | Medium | Failed apply, cloud-sync and cloud-undo jobs were reported as completed with an `error` field the UI ignores. | **Fixed**; they now fail. |
| C4 | Medium | The CLI offered Google Drive backup through `src.gdrive_sync`, a module that is not in the repository; choosing it always failed. | **Fixed** (dead prompts removed; cloud sync lives in the web UI). |
| C5 | Medium | Demo reset deleted from tables that do not exist (`classifications`, `faces`, `cloud_sync_runs`, …) and ignored the errors, so visitor data was never cleared. | **Fixed** and tested against the real schema. |
| C6 | Low | The CLI printed "Undo operation completed" even when undo reported conflicts; the sensitivity prompt capped at 15 while announcing 64 (web UI: 25); the duplicate report walked the tree seven times and missed `.raf` and upper-case extensions. | **Fixed.** |
| C7 | Low | Finished jobs, including full scan results, were kept in memory for the life of the server; the Python hash fallback leaked a file handle per image. | **Fixed** (50 most recent finished jobs retained). |

### Performance

| # | Finding | Evidence | Status |
|---|---|---|---|
| P1 | A web scan hashed every image in batches, passed the paths back to Rust, which hashed them all again and decoded each a third time to read its dimensions. | 320 six-megapixel JPEGs: 6.03 s → 2.79 s, best of 3; hashes and groups compared equal with `cmp`. | **Fixed.** |
| P2 | Rust hashing held Python's GIL, so status polling stalled during each batch. | A 10 ms background thread now runs at 99 % of its ideal rate during hashing. No "before" figure was recorded. | **Fixed.** |
| P3 | Every journal state change rewrote and fsynced the whole journal: cost grew with the square of the session. | Organize (copy) 250 / 500 / 1,000 / 2,000 files: 1.5 / 4.6 / 16.0 / 61.2 s → 1.2 / 2.4 / 4.7 / 9.4 s. Undo 500 / 1,000: 13.0 / 49.8 s → 0.85 / 1.70 s. | **Fixed** with an append-only journal (see below). |
| P4 | The Rust `image` dependency was built with every default codec. | Extension 2.46 MB → 1.85 MB; `cargo tree` 195 → 98 lines. | **Fixed.** Formats compiled in: JPEG, PNG, GIF, BMP, TIFF, WebP. |

Benchmarks ran on the development machine with tiny (2 KB) files for the
organize/undo measurements, so they isolate journaling overhead; real media adds
copy-and-verify time that this change does not affect. Peak memory for the scan
was 443 MB before and 421 MB after.

### Redundancy and documentation

- Removed the dead CLI cloud code (about 70 lines) and consolidated date
  selection (`get_media_date`) and duplicate grouping (`_python_group`).
- The README described process-pool parallelism, parallel compression, working
  S3 support, name-based duplicate detection, MobileNetV3 and a 10× speedup;
  none matched the code or a measurement. It now states what is implemented,
  and documents the network model.
- `phash_rs/README.md` documented an `algorithm=` parameter and three
  algorithms that do not exist.

## Behaviour changes to be aware of

1. **Listening address.** `python main.py --web` binds `127.0.0.1` instead of
   all interfaces; compose publishes on `127.0.0.1`. To use the UI from other
   devices set `CLEAN_BACKUP_BIND=0.0.0.0` (compose) or `CLEAN_BACKUP_HOST=0.0.0.0`
   (local) and open it by IP address, or add the hostname to
   `CLEAN_BACKUP_ALLOWED_HOSTS`.
2. **Cross-origin API use is refused.** The bundled UI and the Vite dev proxy
   are same-origin and unaffected. Scripts (`curl`, automation) are unaffected.
3. **Journal format.** Journals are now append-only JSON Lines (still named
   `journal_*.json`). Journals written before this change remain readable and
   undoable; older versions of the app cannot read new journals.
4. **Classification folders.** Photos are filed by capture date, and category
   folders are single names (`Nature - Scenery`).
5. **Organization by date** now follows the camera's capture date for files
   that were previously filed by modification time.
6. **Model download** fails the Docker build if a model does not match its
   pinned checksum.

## Dependencies

Python pins changed (and nothing else): pillow 12.3.0 → 13.0.0,
cryptography 49.0.0 → 50.0.2, oauthlib 3.3.1 → 4.0.1, urllib3 2.7.0 → 2.8.0,
werkzeug 3.1.8 → 3.1.9, pyasn1 0.6.4 → 0.6.5, certifi 2026.6.17 → 2026.10.23.
The full suite passes in a clean environment built from the new pins; Fernet
and a HEIC round-trip were smoke-tested there. `pip-audit` (OSV database)
reports no known vulnerabilities for `requirements.txt`.

Frontend: `npm audit fix` (semver-compatible) reduced build-tool advisories
from 8 to 2. The remaining two are in esbuild/Vite's development server and
need a Vite major upgrade; the built assets and runtime dependencies (React)
have none. The production bundle is unchanged at 194 kB (58 kB gzip).

Rust dependencies were not checked against an advisory database
(`cargo-audit` is not installed).

## Validation performed

- `pytest tests/` — 117 passed. `ruff check src/ main.py tests/ deploy/` — clean.
- `cargo fmt --check`, `cargo clippy --locked -- -D warnings`, `cargo test --locked` — clean, 6 passed.
- `npm run build` — succeeds.
- Each new regression test was run against the previous source: 22 of the 29
  API tests and all 11 correctness tests failed there. (Seven API tests assert
  behaviour that was already correct, such as same-origin requests succeeding.)
- A real server was started and probed with `curl`: loopback bind, health,
  frontend served, foreign `Host` → 403, cross-origin POST → 403, same-origin
  POST → 200.
- Docker image build and container smoke test: see "Docker" below.

### Not verified

- ML inference (scene, face detection, face recognition) and the watcher daemon
  have no automated tests and were not exercised.
- Google Drive sync and OAuth against the real service; S3 is a stub.
- Video compression with a real FFmpeg; Windows and macOS behaviour.
- The GitHub Actions workflows were not run (pushing was not possible from the
  audit environment).

## Open items

Ordered by priority.

1. **No authentication.** The fixes above stop other websites and other hosts
   by default, but anyone who can reach the port — after opting in to LAN
   exposure — has full control of the mounted library. A shared secret or
   login is the real fix.
2. **Deletion trusts the client** for which image is the "best" in a group
   (`is_best` comes from the request). Server-owned deletion plans remain open
   (F04 in the earlier audit).
3. **The container runs Flask's development server.** Use a production WSGI
   server (for example waitress or gunicorn with threads).
4. **CLI duplicate move/copy/delete** still uses unverified `shutil` operations;
   CLI delete is permanent with a single confirmation.
5. **Compression** fidelity limits (metadata, animation, HDR) are unchanged (F08).
6. **Cloud sync** identifies remote files by name and folder, not by stored
   file id (F27); the throttle is a per-file delay, not a rate limit.
7. **Repository size.** History contains a 261 MB model file and Rust `target/`
   build output (362 MB pack). Removing them requires rewriting history and
   force-pushing, which needs the owner's decision.
8. **Image size.** The face-embedding model is ArcFace ResNet100 (261 MB, saved
   as `mobilefacenet.onnx`); the scene model saved as `mobilenetv3_small.onnx`
   is MobileNetV2. Switching to an actual MobileFaceNet would remove roughly
   250 MB but changes recognition behaviour.
9. **Scan speed** is now dominated by full-resolution JPEG decoding. Scaled
   decoding would be several times faster but changes hash values, so it needs
   re-validation of duplicate detection first. Grouping remains O(n²).
10. **Docker inputs.** Base images (`rust:slim`, `node:20-slim`,
    `python:3.12-slim`) and `maturin` are not pinned to digests/versions.
11. **Vite major upgrade** to clear the two remaining dev-server advisories.
12. Carried over from the earlier audit: hard-link requirement for publication
    (no FAT/exFAT), leftover `.clean-backup-*.partial` files after a crash,
    perceptual matching being heuristic, symlinks created by classification are
    not journaled.
