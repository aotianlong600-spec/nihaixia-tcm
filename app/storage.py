import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat()


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def connect(data_dir: Path):
    conn = sqlite3.connect(data_dir / "clinical.sqlite3", timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


def initialize(data_dir: Path):
    data_dir.mkdir(parents=True, exist_ok=True)
    with connect(data_dir) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS patients (
            id TEXT PRIMARY KEY, code TEXT NOT NULL UNIQUE, notes TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS visits (
            id TEXT PRIMARY KEY, patient_id TEXT NOT NULL REFERENCES patients(id),
            previous_visit_id TEXT REFERENCES visits(id), revision INTEGER NOT NULL,
            chief_complaint TEXT NOT NULL, facts TEXT NOT NULL, context TEXT NOT NULL,
            clinician TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS visit_revisions (
            visit_id TEXT NOT NULL REFERENCES visits(id), revision INTEGER NOT NULL,
            snapshot TEXT NOT NULL, created_at TEXT NOT NULL,
            PRIMARY KEY(visit_id, revision)
        );
        CREATE TABLE IF NOT EXISTS rules (
            id TEXT PRIMARY KEY, document TEXT NOT NULL, reviews TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS analyses (
            id TEXT PRIMARY KEY, visit_id TEXT NOT NULL REFERENCES visits(id),
            visit_revision INTEGER NOT NULL, document TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS decisions (
            id TEXT PRIMARY KEY, analysis_id TEXT NOT NULL REFERENCES analyses(id),
            document TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS model_calls (
            id TEXT PRIMARY KEY, analysis_id TEXT, purpose TEXT NOT NULL,
            status TEXT NOT NULL, document TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit_events (
            id TEXT PRIMARY KEY, event TEXT NOT NULL, target_id TEXT NOT NULL,
            metadata TEXT NOT NULL, created_at TEXT NOT NULL
        );
        """)
        for rule in demo_rules():
            conn.execute("INSERT OR IGNORE INTO rules VALUES(?,?,?,?)",
                         (rule["id"], encode(rule), encode({}), now()))
    conn.close()


def audit(conn, event, target_id, **metadata):
    conn.execute("INSERT INTO audit_events VALUES(?,?,?,?,?)",
                 (str(uuid4()), event, target_id, encode(metadata), now()))


def analysis_dependency_errors(conn, snapshot):
    from .knowledge import get_page

    errors = []
    visit = conn.execute("SELECT revision FROM visits WHERE id=?", (snapshot["visit_id"],)).fetchone()
    if visit is None or visit[0] != snapshot["visit_revision"]:
        errors.append("访次版本已改变")
    for rule in snapshot.get("rule_snapshot", []):
        row = conn.execute("SELECT document FROM rules WHERE id=?", (rule["id"],)).fetchone()
        if row is None or json.loads(row[0])["status"] != "published":
            errors.append("规则已撤回或缺失：" + rule["id"])
    for evidence in snapshot.get("evidence_snapshot", []):
        page = get_page(conn, evidence["document_id"], evidence["physical_page"])
        frozen = evidence["corrected_text"] if evidence["source_type"] == "corrected" else evidence["raw_text"]
        current = None if page is None else page["corrected_text"] if page["corrected_text"] is not None else page["raw_text"]
        if page is None or page["review_status"] != "verified" or frozen != current:
            errors.append("证据页内容或校核状态已改变：" + evidence["id"])
    return errors


def demo_rules():
    common = {"version": 1, "status": "published", "synthetic": True,
              "scope": {"description": "仅合成算法验证，不是医学规则"},
              "support": [], "evidence_ids": [], "formula": [], "actions": [],
              "description": "完全合成规则，仅测试条件逻辑，不能用于诊疗。"}
    return [
        {**common, "id": "synthetic-pattern-a-v1", "title": "合成方证A（算法演示）", "kind": "pattern",
         "required": {"all": [{"fact": "demo_cold"}, {"fact": "demo_sweat", "state": "absent"}]},
         "excluded": {"fact": "demo_thirst"}},
        {**common, "id": "synthetic-red-flag-v1", "title": "合成危险信号（仅验证中止流程）", "kind": "red_flag",
         "required": {"fact": "demo_emergency"}, "excluded": None},
    ]
