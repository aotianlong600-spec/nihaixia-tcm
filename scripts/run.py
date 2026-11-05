"""Local-only server entry point; access logs intentionally omit request data."""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    args = parser.parse_args()
    os.environ["TCM_DATA_DIR"] = str(args.data_dir.resolve())
    import uvicorn
    uvicorn.run("app.main:create_app", factory=True, host="127.0.0.1", port=8765, access_log=False)


if __name__ == "__main__":
    main()
