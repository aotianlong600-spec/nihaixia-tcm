from pathlib import Path
import subprocess


def test_static_model_network_runtime() -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            "node", "--test", "tests/pages_runtime.test.mjs", "tests/consult_ui.test.mjs",
            "tests/codex_relay_worker.test.mjs", "tests/public_codex_relay.test.mjs",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_pages_cache_version_changes_when_only_javascript_changes(tmp_path, monkeypatch) -> None:
    import json
    from scripts import build_pages

    web = tmp_path / "web"
    pages = tmp_path / "scripts" / "pages"
    web.mkdir()
    pages.mkdir(parents=True)
    (web / "index.html").write_text('<html lang="zh-CN"><head></head><script src="/ni_ai.js"></script></html>')
    (web / "ni_ai.js").write_text("console.log('first')")
    (pages / "pages_runtime.js").write_text("const meta = null /* __STATIC_AI_META__ */;")
    (pages / "pages_worker.js").write_text("const version = '__BUILD_ID__'")
    (pages / "sw-template.js").write_text("__PWA_CONFIG__")
    monkeypatch.setattr(build_pages, "ROOT", tmp_path)
    monkeypatch.setattr(build_pages, "WEB_DIR", web)
    monkeypatch.setattr(build_pages, "PAGES_SRC", pages)
    monkeypatch.setattr(build_pages, "DIST", tmp_path / "dist")
    monkeypatch.setattr(build_pages, "RUNTIME_ASSETS", {})
    monkeypatch.setattr(build_pages, "create_pwa_icons", lambda path: None)
    def unchanged_bundle(path):
        path.parent.mkdir(parents=True)
        path.write_bytes(b"unchanged Python bundle")

    monkeypatch.setattr(build_pages, "build_bundle_zip", unchanged_bundle)

    def build_version():
        dist = build_pages.build_dist(skip_pdfs=True)
        return json.loads((dist / "sw.js").read_text())["version"]

    original = build_version()
    (pages / "pages_runtime.js").write_text("const meta = null /* __STATIC_AI_META__ */; // request fix")
    runtime_changed = build_version()
    (web / "ni_ai.js").write_text("console.log('updated')")
    ui_changed = build_version()
    assert len({original, runtime_changed, ui_changed}) == 3
