"""One process serves local HTTP and explicitly enabled authenticated LAN HTTPS."""
import argparse
import asyncio
import os
from contextlib import contextmanager
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def configure_node_path(root=ROOT):
    runtime = root / '.runtime' / 'node'
    if (runtime / 'node.exe').is_file():
        os.environ['PATH'] = str(runtime) + os.pathsep + os.environ.get('PATH', '')


async def serve(app, tls):
    import uvicorn

    class Server(uvicorn.Server):
        @contextmanager
        def capture_signals(self):
            yield  # asyncio.run owns shutdown for both listeners.

    configs = [uvicorn.Config(app, host='127.0.0.1', port=8765, access_log=False, proxy_headers=False)]
    if tls:
        configs.append(uvicorn.Config(app, host='0.0.0.0', port=8766, access_log=False, proxy_headers=False,
                                     ssl_certfile=tls['server_cert'], ssl_keyfile=tls['server_key']))
    servers = [Server(config) for config in configs]
    tasks = [asyncio.create_task(server.serve()) for server in servers]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in tasks:
            if task.done(): task.result()
    finally:
        for server in servers: server.should_exit = True
        await asyncio.gather(*tasks, return_exceptions=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument('--lan', action='store_true')
    parser.add_argument('--lan-host', action='append', default=[])
    args = parser.parse_args()
    configure_node_path()
    from app.access import AccessGate
    from app.lan import discover_hosts, ensure_tls
    from app.main import create_app
    data = args.data_dir.resolve()
    hosts, tls = [], None
    if args.lan:
        if not AccessGate(data).configured:
            parser.error('先在本机网页“模型与数据”设置访问密码，再启用局域网')
        hosts = args.lan_host or discover_hosts()
        if not hosts: parser.error('未发现私有IPv4地址；连接局域网或指定 --lan-host')
        tls = ensure_tls(data, hosts)
        for host in hosts: print(f'LAN: https://{host}:8766', flush=True)
        print(f'CA SHA256: {tls["ca_fingerprint"]}', flush=True)
    app = create_app(data, lan_hosts=hosts)
    app.state.lan_enabled = bool(tls)
    try:
        asyncio.run(serve(app, tls))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
