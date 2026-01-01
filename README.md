# Local Personal Finance Analyzer

The application imports bank/credit-card CSV statements, normalizes merchants, detects recurring charges, flags changes (price/frequency/duplicates/new subscriptions), detects anomalies, and generates a monthly insights export

Download the test statements from the test-dataset folder in the repo and try the live demo: https://personal-finance-analyzer-demo.streamlit.app/

- **Everything is local**: 
    - CSV statements are imported on your machine
    - Transactions and derived insights are stored in a **local SQLite database** under `./data/` by default
    - The UI is a **Streamlit app** that runs locally and is opened in your browser (typically `http://localhost:8501`)
    - No data is uploaded anywhere. By default the app makes **no external network calls**
- **Optional encryption at rest**: passphrase-based encryption for sensitive fields (transaction descriptions + alert evidence)
- **Export insights only** (default): aggregates + subscriptions + alerts (no raw transactions)
- **Redacted logs**: logs never include raw transaction descriptions
- **Delete-all option**: wipe DB + caches + logs

## Optional Functionalities
- **Local LLM via Ollama**: ask questions and generate human-readable alert explanations
- **MCP Server**: exposes your local finance tools to MCP clients

---

## Statement type compatibility (what the importer accepts)

The importer is **column-name tolerant** (it does not require an exact header), but it does need to find a few core fields

### Minimum required fields
Your CSV must contain columns that can be interpreted as:
- a **date** (e.g., `Date`, `Posted`, `Transaction Date`)
- a **description/merchant** string (e.g., `Description`, `Details`, `Merchant`)
- an **amount** number (e.g., `Amount`, `Value`)

Optional:
- `Currency`
- `Account`

---

## Quickstart

### 1) Create env + install deps
Using a virtual environment is recommended
```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

### 2) Initialize local data directory
```bash
python -m subsentry.cli init
```

### 3) Run the UI (Streamlit)
```bash
python -m subsentry.cli ui
```

---

## Local LLM (Ollama)

1) Install and run Ollama (local)
2) Pull a tool-capable model (example: `qwen2.5`)
3) In the UI: Settings → enable **Local LLM**, set model name
4) Calls `http://localhost:11434` by default (can be adjusted) and only when enabled

---

## MCP Server (local tools over MCP)

Run a local MCP server over streamable HTTP:
```bash
python -m subsentry.cli mcp --transport streamable-http --port 8765
```

Connect clients to:
- `http://localhost:8765/mcp`

Or run stdio transport:
```bash
python -m subsentry.cli mcp --transport stdio
```

---

## Commands

- `init` – create folders + DB
- `import-csv` – import a statement with dedupe
- `recompute` – recompute subscriptions + alerts
- `export-insights` – export aggregate-only insights
- `set-passphrase` – enable encryption at rest (optional)
- `purge` – delete all local data
- `ui` – run Streamlit UI
- `mcp` – run MCP server


# Limitations + Future Improvements:

The app is designed to be lightweight and local, so its detections are heuristic-based and may produce false positives depending on statement quality and merchant naming noise. Future improvements include broader CSV schema auto-detection, stronger merchant resolution (learned embeddings + user-curated aliases), optional category inference, better evaluation tooling for precision/recall, full-database encryption, and more advanced trend/forecasting models. Encryption at rest focuses on sensitive text/evidence fields rather than full-database encryption
