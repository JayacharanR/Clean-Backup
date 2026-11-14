# Clean-Backup Web UI

This frontend is a React + Vite application consumed by the Flask API server in `src/web_app.py`.

## Run Web GUI from CLI Mode 6

Use this exact terminal sequence.

### 1) Install Node.js (includes npm)

```bash
sudo apt update
sudo apt install -y nodejs npm
```

### 2) Build frontend

```bash
cd web
npm install
npm run build
```

### 3) Install Python dependencies (if needed)

```bash
# from the repository root
uv pip install -r requirements.txt
```

### 4) Start app

```bash
python main.py
```

Then select option 6 from the CLI menu to run the website on localhost.

## Local frontend development (optional)

```bash
cd web
npm install
npm run dev
```

In a separate terminal, run backend API:

```bash
# from the repository root
CLEAN_BACKUP_PORT=5179 python main.py --web
```

Vite proxies `/api/*` to `http://127.0.0.1:5179`.
