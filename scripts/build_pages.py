"""Package the already built web app for GitHub Pages, using public assets only."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from importlib.metadata import distribution
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from urllib.request import urlopen
from zipfile import ZIP_DEFLATED, ZipFile
import sqlite3
from contextlib import closing

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / 'frontend/dist'
PYODIDE = 'https://cdn.jsdelivr.net/pyodide/v0.29.3/full/'
ASSETS = {
    'pyodide.mjs': '23213d27e9dacbda6f25f955fb38dabfc40ada082c04ee253047ea5dddcaa3b5',
    'pyodide.asm.js': '1263f02b5b26099b96112378156f242dd98b39a8201ba7765e5fe3d455c5ce91',
    'pyodide.asm.wasm': 'e2f4ee75b325e35eb31bfb8c613d4dd5098f5502c156a97847686875b5025480',
    'python_stdlib.zip': '4298b6ee445cb724c3973437da47789752b9e6ff4e26619026b283ec801fc46b',
    'pyodide-lock.json': '3256ffc76388de0e37f4b34d42ab484268d1afc675179ff97b2a5bb14f84ccac',
    'sqlite3-1.0.0-cp313-cp313-pyodide_2025_0_wasm32.whl': 'aab7214b987a3803fca283a8221e4b9d3274abc05d0cf506ea1a2ae7e09e3bf0',
    'LICENSE': '1f256ecad192880510e84ad60474eab7589218784b9a50bc7ceee34c2b91f1d5',
}
MODULES = (
    '__init__', 'browser_api', 'mobile_api', 'consultation_core', 'decision', 'decision_support',
    'domain', 'engine', 'formula_engine', 'knowledge', 'library', 'offline_pack', 'offline_runtime',
    'portable_validation', 'storage', 'browser_models', 'mobile_models', 'model_profiles', 'model_urls',
    'browser_library', 'browser_excerpts', 'consultation_library', 'library_analysis',
    'library_evidence', 'library_modifications', 'library_signs',
)


def download(name, digest):
    target = DIST / 'runtime/pyodide' / name
    if target.is_file() and sha256(target.read_bytes()).hexdigest() == digest:
        return
    url = ('https://raw.githubusercontent.com/pyodide/pyodide/0.29.3/LICENSE'
           if name == 'LICENSE' else PYODIDE + name)
    with urlopen(url, timeout=60) as response:
        data = response.read(16 * 1024 * 1024 + 1)
    if sha256(data).hexdigest() != digest:
        raise ValueError(f'Unexpected checksum for {name}')
    target.write_bytes(data)


def engine_archive():
    sys.path.insert(0, str(ROOT))
    from app.offline_pack import SCHEMA, export_pack

    with TemporaryDirectory(prefix='.pages-build-', dir=ROOT) as temporary:
        stage = Path(temporary)
        source = stage / 'source'
        source.mkdir()
        with closing(sqlite3.connect(source / 'clinical.sqlite3')) as db, db:
            for statement in SCHEMA.values():
                db.execute(statement)
        pack = stage / 'knowledge'
        manifest = export_pack(source, pack)
        if any(manifest['tables'].values()):
            raise ValueError('Public starter pack contains imported records')
        with ZipFile(DIST / 'runtime/engine.zip', 'w', ZIP_DEFLATED) as out:
            for module in MODULES:
                path = f'app/{module}.py'
                out.write(ROOT / path, path)
            for name in ('open_formula_library.json', 'portable_schemas.json', 'codex_models.json'):
                path = f'app/resources/{name}'
                out.write(ROOT / path, path)
            for stem in ('formula_mentions', 'formula_compositions', 'modifications', 'sign_terms'):
                for suffix in ('.json', '_manifest.json'):
                    path = f'library_evidence/{stem}{suffix}'
                    out.write(ROOT / path, path)
            for name in (*manifest['files'], 'manifest.json'):
                out.write(pack / name, f'knowledge/{name}')
            package = distribution('fastjsonschema')
            if package.version != '2.21.2':
                raise ValueError('Install the pinned fastjsonschema version before packaging')
            for file in package.files or ():
                name = file.as_posix()
                if name.startswith('fastjsonschema/') and file.suffix == '.py':
                    out.write(package.locate_file(file), name)
                elif '.dist-info/' in name and 'LICENSE' in file.name.upper():
                    out.write(package.locate_file(file), 'licenses/fastjsonschema-LICENSE')


def service_worker():
    files = sorted(p for p in DIST.rglob('*') if p.is_file() and p.name != 'sw.js' and not p.name.startswith('.'))
    paths = [p.relative_to(DIST).as_posix() for p in files]
    build = sha256()
    for path, file in zip(paths, files):
        build.update(path.encode())
        build.update(sha256(file.read_bytes()).digest())
    script = (ROOT / 'frontend/pages-sw.js').read_text(encoding='utf-8')
    content = script.replace('__BUILD_ID__', build.hexdigest()[:16]).replace('__APP_FILES__', json.dumps(paths))
    (DIST / 'sw.js').write_text(content, encoding='utf-8')


if __name__ == '__main__':
    if not (DIST / 'index.html').is_file() or not (DIST / 'browser-worker.js').is_file():
        sys.exit('Build the browser app with VITE_BROWSER_APP=1 before packaging')
    (DIST / 'runtime/pyodide').mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda item: download(*item), ASSETS.items()))
    engine_archive()
    (DIST / '.nojekyll').touch()
    service_worker()
    print('Pages app ready in frontend/dist')
