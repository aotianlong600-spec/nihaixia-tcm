"""Private LAN certificates; never install a system trust root or disable TLS checks."""
from contextlib import contextmanager
from datetime import datetime, timedelta
import ipaddress
import os
from pathlib import Path
import ssl
import socket
import time
from uuid import uuid4

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from .access import lan_hosts


def discover_hosts():
    found = set()
    try:
        for entry in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            try:
                found.update(lan_hosts([entry[4][0]]))
            except ValueError:
                pass
    except OSError:
        pass
    return sorted(found)


@contextmanager
def _lock(folder):
    with (folder / 'tls.lock').open('a+b') as f:
        f.seek(0)
        if not f.read(1):
            f.write(b'0')
            f.flush()
        f.seek(0)
        if os.name == 'nt':
            import msvcrt
            deadline = time.monotonic() + 10
            while True:
                try:
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise ValueError('另一个进程正在生成局域网证书，请稍后重试') from None
                    time.sleep(.1)
            try:
                yield
            finally:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _atomic(path, content):
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    try:
        with temporary.open('wb') as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _key_bytes(key):
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


def _public(key):
    return key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)


def ensure_tls(data_dir: Path, hosts):
    addresses = lan_hosts(hosts)
    folder = data_dir / 'lan'
    folder.mkdir(parents=True, exist_ok=True)
    paths = {k: folder / name for k, name in {'ca_cert': 'ca.pem', 'ca_key': 'ca-key.pem',
             'server_cert': 'server.pem', 'server_key': 'server-key.pem'}.items()}
    now = datetime.utcnow()
    with _lock(folder):
        existing = [paths[k].exists() for k in ('ca_cert', 'ca_key')]
        if any(existing) and not all(existing):
            raise ValueError('本机CA文件不完整；请恢复原证书，不能静默替换已配对证书')
        if all(existing):
            try:
                ca = x509.load_pem_x509_certificate(paths['ca_cert'].read_bytes())
                ca_key = serialization.load_pem_private_key(paths['ca_key'].read_bytes(), password=None)
                if not isinstance(ca_key, ec.EllipticCurvePrivateKey) or _public(ca_key) != ca.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo):
                    raise ValueError()
                if not ca.extensions.get_extension_for_class(x509.BasicConstraints).value.ca or ca.not_valid_after <= now:
                    raise ValueError()
                ca.public_key().verify(ca.signature, ca.tbs_certificate_bytes, ec.ECDSA(ca.signature_hash_algorithm))
            except (ValueError, TypeError, x509.ExtensionNotFound):
                raise ValueError('本机CA密钥、证书不匹配或已过期，请恢复证书或重新配对') from None
        else:
            ca_key = ec.generate_private_key(ec.SECP256R1())
            name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Nihaixia personal LAN CA')])
            ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(ca_key.public_key())
                  .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
                  .not_valid_after(now + timedelta(days=3650)).add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                  .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
                  .sign(ca_key, hashes.SHA256()))
            _atomic(paths['ca_key'], _key_bytes(ca_key))
            _atomic(paths['ca_cert'], ca.public_bytes(serialization.Encoding.PEM))
        wanted = set(addresses + ['127.0.0.1', '::1'])
        reuse = False
        if paths['server_cert'].is_file() and paths['server_key'].is_file():
            try:
                leaf = x509.load_pem_x509_certificate(paths['server_cert'].read_bytes())
                leaf_key = serialization.load_pem_private_key(paths['server_key'].read_bytes(), password=None)
                names = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
                ca.public_key().verify(leaf.signature, leaf.tbs_certificate_bytes, ec.ECDSA(leaf.signature_hash_algorithm))
                reuse = (leaf.issuer == ca.subject and leaf.not_valid_after > now + timedelta(days=1)
                         and _public(leaf_key) == leaf.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
                         and wanted <= {str(a) for a in names.get_values_for_type(x509.IPAddress)}
                         and 'localhost' in names.get_values_for_type(x509.DNSName))
            except Exception:
                reuse = False  # A leaf can be reissued under the same paired CA.
        if not reuse:
            leaf_key = ec.generate_private_key(ec.SECP256R1())
            names = [x509.DNSName('localhost')] + [x509.IPAddress(ipaddress.ip_address(a)) for a in sorted(wanted)]
            leaf = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Nihaixia Workbench')]))
                    .issuer_name(ca.subject).public_key(leaf_key.public_key()).serial_number(x509.random_serial_number())
                    .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=365))
                    .add_extension(x509.SubjectAlternativeName(names), critical=False)
                    .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                    .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                    .sign(ca_key, hashes.SHA256()))
            _atomic(paths['server_key'], _key_bytes(leaf_key))
            _atomic(paths['server_cert'], leaf.public_bytes(serialization.Encoding.PEM))
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(paths['server_cert'], paths['server_key'])
    return {**{k: str(v) for k, v in paths.items()}, 'ca_fingerprint': ca.fingerprint(hashes.SHA256()).hex(), 'addresses': addresses}
