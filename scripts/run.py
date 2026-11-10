"""只读知识库服务的启动入口。单进程，默认仅监听本机。"""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def serve(app, port=8767):
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=port, access_log=False, proxy_headers=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data", help="知识库存放目录（默认 data/）")
    parser.add_argument("--port", type=int, default=8767)
    args = parser.parse_args()
    from app.main import create_app

    serve(create_app(args.data_dir.resolve()), args.port)


if __name__ == "__main__":
    main()
