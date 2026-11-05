"""Prepare a private CA without enabling LAN access or changing system trust."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.lan import discover_hosts, ensure_tls


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data')
    parser.add_argument('--host', action='append', default=[])
    args = parser.parse_args()
    hosts = args.host or discover_hosts()
    if not hosts: parser.error('未发现私有IPv4，请连接局域网或指定 --host')
    tls = ensure_tls(args.data_dir.resolve(), hosts)
    print(json.dumps({'ca_certificate': tls['ca_cert'], 'ca_sha256': tls['ca_fingerprint'],
                      'addresses': [f'https://{host}:8766' for host in hosts]}, ensure_ascii=False))


if __name__ == '__main__': main()
