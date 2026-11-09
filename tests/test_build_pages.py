from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def build_pages_module():
    spec = spec_from_file_location('build_pages', ROOT / 'scripts/build_pages.py')
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_public_pages_build_rejects_starter_pack(tmp_path):
    module = build_pages_module()
    module.DIST = tmp_path / 'dist'
    (module.DIST / 'runtime').mkdir(parents=True)

    with pytest.raises(ValueError, match='complete knowledge pack'):
        module.engine_archive(None)
