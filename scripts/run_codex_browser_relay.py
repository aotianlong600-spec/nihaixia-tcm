"""Serve the opt-in browser bridge on this computer only."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if __name__ == "__main__":
    import uvicorn
    from app.codex_browser_relay import create_app

    uvicorn.run(create_app(), host="127.0.0.1", port=8769, access_log=False, proxy_headers=False)
