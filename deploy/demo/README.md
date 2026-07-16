# Demo Deployment (Render)

This directory contains everything needed to deploy a read-only demo of Clean-Backup on [Render](https://render.com).

## Architecture

- Uses the **same Dockerfile** from the repo root — no separate build path.
- `DEMO_MODE=true` enforces read-only behavior server-side (403 on all mutating endpoints).
- Seed data is loaded at startup via `seed_demo_db.py`.
- Auto-reset every 30 minutes via the in-app scheduler restores the demo to a pristine state.

## Deploy to Render

### 1. Create a new Web Service on Render

- Connect your GitHub repo (`JayacharanR/Clean-Backup`)
- **Environment**: Docker
- **Region**: Oregon (or closest)
- **Instance Type**: Free (or Starter for better performance)
- **Branch**: `main`

### 2. Set environment variables

| Variable | Value |
|----------|-------|
| `DEMO_MODE` | `true` |
| `CLEAN_BACKUP_PORT` | `8080` |
| `CLEAN_BACKUP_LOG_LEVEL` | `info` |

### 3. Deploy

Render will build using the repo-root `Dockerfile` automatically. The `render.yaml` blueprint in this directory can also be used for one-click deploy.

### One-click deploy

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/JayacharanR/Clean-Backup)

## Seed Media

Before deploying, run the download script to populate `seed-media/`:

```bash
cd deploy/demo
bash download_seed_media.sh
```

This downloads CC0-licensed sample images from Pexels/Unsplash. See `SOURCES.md` for exact attribution.

## Auto-Reset

The demo server automatically resets its database and seed media every 30 minutes when `DEMO_MODE=true`. This is handled by an in-app scheduler in `reset_demo.py`, which is triggered from the Flask startup path.
