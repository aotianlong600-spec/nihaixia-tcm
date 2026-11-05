from pathlib import Path
import ssl
from datetime import datetime,timezone
import pytest
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ec
from app.lan import ensure_tls


def test_lan_certificate_has_valid_chain_and_is_reused(tmp_path):
    first=ensure_tls(tmp_path,['192.168.50.20'])
    ca=x509.load_pem_x509_certificate(Path(first['ca_cert']).read_bytes())
    leaf=x509.load_pem_x509_certificate(Path(first['server_cert']).read_bytes())
    assert leaf.issuer==ca.subject
    ca.public_key().verify(leaf.signature,leaf.tbs_certificate_bytes,ec.ECDSA(leaf.signature_hash_algorithm))
    addresses=leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert '192.168.50.20' in [str(x) for x in addresses.get_values_for_type(x509.IPAddress)]
    assert 'localhost' in addresses.get_values_for_type(x509.DNSName)
    context=ssl.create_default_context(cafile=first['ca_cert'])
    assert context.verify_mode==ssl.CERT_REQUIRED and context.check_hostname
    assert ensure_tls(tmp_path,['192.168.50.20'])['ca_fingerprint']==first['ca_fingerprint']
    second=ensure_tls(tmp_path,['192.168.50.21'])
    assert second['ca_fingerprint']==first['ca_fingerprint']
    assert Path(first['ca_key']).read_bytes().startswith(b'-----BEGIN PRIVATE KEY-----')


def test_lan_refuses_public_addresses_and_mismatched_ca(tmp_path):
    with pytest.raises(ValueError):ensure_tls(tmp_path,['8.8.8.8'])
    one=ensure_tls(tmp_path,['192.168.50.20'])
    other=ensure_tls(tmp_path/'other',['192.168.50.20'])
    Path(one['ca_key']).write_bytes(Path(other['ca_key']).read_bytes())
    with pytest.raises(ValueError):ensure_tls(tmp_path,['192.168.50.20'])
