# Local Personal Finance Analyzer

The application imports bank/credit-card CSV statements, normalizes merchants, detects recurring charges, flags changes (price/frequency/duplicates/new subscriptions), detects anomalies, and generates a monthly insights export


- **Everything is local**: 
    - CSV statements are imported locally on your machine and are column-name tolerant (more details on this in the [Run](#run) section)
    - Transactions and derived insights are stored in a **local SQLite database** under `./data/` by default
    - The UI is a **Streamlit app** that runs locally and is opened in your browser (typically `http://localhost:8501`)
    - No data is uploaded anywhere. By default the app makes **no external network calls**
- **Export insights only** (default): aggregates + subscriptions + alerts (no raw transactions)
- **Redacted logs**: logs never include raw transaction descriptions
- **Delete-all option**: wipe DB + caches + logs

### Optional Functionalities:
- **Local LLM via Ollama**: ask questions and generate human-readable alert explanations
- **MCP Server**: exposes your local finance tools to MCP clients
- **Encryption at rest**: passphrase-based encryption for sensitive fields (transaction descriptions + alert evidence)

---

## Setup
Using a virtual environment is recommended
### Windows (PowerShell)
```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
python -m subsentry.cli init
```
### macOS/Linux
```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
python -m subsentry.cli init
```

---

## Run
This will load up the interactive dashboard via Streamlit:
```bash
python -m subsentry.cli ui
```

The statement importer is column-name tolerant (it does not require an exact header), but it does need to find a few core fields that can be interpreted as:
- a **date** (e.g., `Date`, `Posted`, `Transaction Date`)
- a **description/merchant** string (e.g., `Description`, `Details`, `Merchant`)
- an **amount** number (e.g., `Amount`, `Value`)

**Optional:**
- `Currency`
- `Account`
---
### Local LLM (Ollama)

1) Install and run Ollama (local)
2) Pull a tool-capable model (As of 2025, an example: `qwen2.5`)
3) In the UI: Settings → enable **Local LLM**, set model name
4) Calls `http://localhost:11434` by default (can be adjusted) and only when enabled

---

### MCP Server (local tools over MCP)

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


## Limitations + Future Improvements:

The app is designed to be lightweight and local, so its detections are heuristic-based and may produce false positives depending on statement quality and merchant naming noise. Future improvements include broader CSV schema auto-detection, stronger merchant resolution (learned embeddings + user-curated aliases), optional category inference, better evaluation tooling for precision/recall, full-database encryption, and more advanced trend/forecasting models. Encryption at rest focuses on sensitive text/evidence fields rather than full-database encryption
