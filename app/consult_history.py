"""Per-patient profiles and isolated consultation session history in SQLite."""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any
import uuid


DB_FILENAME = "consult_history.sqlite3"


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _connect(data_dir: Path) -> sqlite3.Connection:
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / DB_FILENAME
    conn = sqlite3.connect(db_path, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS history_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS patients (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            gender TEXT NOT NULL DEFAULT '',
            age TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS consult_sessions (
            id TEXT PRIMARY KEY,
            patient_id TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            intake_json TEXT NOT NULL DEFAULT '{}',
            pinned_json TEXT NOT NULL DEFAULT 'null',
            turns_json TEXT NOT NULL DEFAULT '[]',
            packet_json TEXT NOT NULL DEFAULT 'null',
            primary_formula TEXT NOT NULL DEFAULT '',
            summary_text TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_consult_sessions_patient_updated
            ON consult_sessions(patient_id, updated_at DESC);
        """
    )
    row = conn.execute("SELECT value FROM history_meta WHERE key = 'seeded_default'").fetchone()
    if row is None:
        now = _now_iso()
        pat_id = f"pat_{uuid.uuid4().hex[:10]}"
        ses_id = f"ses_{uuid.uuid4().hex[:10]}"
        conn.execute(
            "INSERT INTO patients (id, name, gender, age, notes, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (pat_id, "默认问诊人", "", "", "可新建或切换其他问诊人，每人拥有独立问诊历史", now, now),
        )
        conn.execute(
            "INSERT INTO consult_sessions (id, patient_id, title, intake_json, pinned_json, turns_json, packet_json, primary_formula, summary_text, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ses_id, pat_id, "新开问诊", "{}", "null", "[]", "null", "", "待录入症状", now, now),
        )
        conn.execute("INSERT INTO history_meta (key, value) VALUES ('seeded_default', '1')")
        conn.commit()


def _row_to_patient(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "gender": row["gender"],
        "age": row["age"],
        "notes": row["notes"],
        "session_count": int(row["session_count"]) if "session_count" in row.keys() else 0,
        "latest_formula": row["latest_formula"] if "latest_formula" in row.keys() else "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _row_to_session_summary(row: sqlite3.Row) -> dict[str, Any]:
    try:
        turns = json.loads(row["turns_json"] or "[]")
    except json.JSONDecodeError:
        turns = []
    return {
        "id": row["id"],
        "patient_id": row["patient_id"],
        "title": row["title"],
        "primary_formula": row["primary_formula"],
        "summary_text": row["summary_text"],
        "turn_count": len([t for t in turns if isinstance(t, dict) and t.get("role") == "user"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _row_to_session_detail(row: sqlite3.Row) -> dict[str, Any]:
    def _load(raw: str, fallback: Any) -> Any:
        try:
            return json.loads(raw) if raw else fallback
        except json.JSONDecodeError:
            return fallback

    return {
        "id": row["id"],
        "patient_id": row["patient_id"],
        "title": row["title"],
        "intake": _load(row["intake_json"], {}),
        "pinned_entity": _load(row["pinned_json"], None),
        "turns": _load(row["turns_json"], []),
        "latest_packet": _load(row["packet_json"], None),
        "primary_formula": row["primary_formula"],
        "summary_text": row["summary_text"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_patients(data_dir: Path) -> list[dict[str, Any]]:
    with closing(_connect(data_dir)) as conn:
        rows = conn.execute(
            """
            SELECT
                p.*,
                (SELECT COUNT(*) FROM consult_sessions s WHERE s.patient_id = p.id) AS session_count,
                COALESCE(
                    (
                        SELECT s.primary_formula
                        FROM consult_sessions s
                        WHERE s.patient_id = p.id AND s.primary_formula != ''
                        ORDER BY s.updated_at DESC
                        LIMIT 1
                    ),
                    ''
                ) AS latest_formula
            FROM patients p
            ORDER BY p.updated_at DESC, p.created_at DESC
            """
        ).fetchall()
        return [_row_to_patient(r) for r in rows]


def get_patient(data_dir: Path, patient_id: str) -> dict[str, Any] | None:
    with closing(_connect(data_dir)) as conn:
        row = conn.execute(
            """
            SELECT p.*,
                   (SELECT COUNT(*) FROM consult_sessions s WHERE s.patient_id = p.id) AS session_count,
                   '' AS latest_formula
            FROM patients p WHERE p.id = ?
            """,
            (patient_id,),
        ).fetchone()
        return _row_to_patient(row) if row else None


def create_patient(
    data_dir: Path,
    *,
    name: str,
    gender: str = "",
    age: str = "",
    notes: str = "",
    auto_create_session: bool = True,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("问诊人姓名/称呼不能为空")
    now = _now_iso()
    pat_id = f"pat_{uuid.uuid4().hex[:10]}"
    initial_session: dict[str, Any] | None = None
    with closing(_connect(data_dir)) as conn:
        conn.execute(
            "INSERT INTO patients (id, name, gender, age, notes, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (pat_id, clean_name[:40], (gender or "").strip()[:16], (age or "").strip()[:24], (notes or "").strip()[:400], now, now),
        )
        if auto_create_session:
            ses_id = f"ses_{uuid.uuid4().hex[:10]}"
            conn.execute(
                "INSERT INTO consult_sessions (id, patient_id, title, intake_json, pinned_json, turns_json, packet_json, primary_formula, summary_text, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ses_id, pat_id, "新开问诊", "{}", "null", "[]", "null", "", "待录入症状", now, now),
            )
        conn.commit()
    patient = get_patient(data_dir, pat_id)
    if auto_create_session:
        sessions = list_sessions(data_dir, pat_id)
        if sessions:
            initial_session = get_session(data_dir, sessions[0]["id"])
    assert patient is not None
    return patient, initial_session


def update_patient(
    data_dir: Path,
    patient_id: str,
    *,
    name: str | None = None,
    gender: str | None = None,
    age: str | None = None,
    notes: str | None = None,
) -> dict[str, Any] | None:
    existing = get_patient(data_dir, patient_id)
    if not existing:
        return None
    new_name = (name if name is not None else existing["name"]).strip()
    if not new_name:
        raise ValueError("问诊人姓名/称呼不能为空")
    now = _now_iso()
    with closing(_connect(data_dir)) as conn:
        conn.execute(
            "UPDATE patients SET name = ?, gender = ?, age = ?, notes = ?, updated_at = ? WHERE id = ?",
            (
                new_name[:40],
                (gender if gender is not None else existing["gender"]).strip()[:16],
                (age if age is not None else existing["age"]).strip()[:24],
                (notes if notes is not None else existing["notes"]).strip()[:400],
                now,
                patient_id,
            ),
        )
        conn.commit()
    return get_patient(data_dir, patient_id)


def delete_patient(data_dir: Path, patient_id: str) -> bool:
    with closing(_connect(data_dir)) as conn:
        cur = conn.execute("DELETE FROM patients WHERE id = ?", (patient_id,))
        conn.commit()
        return cur.rowcount > 0


def list_sessions(data_dir: Path, patient_id: str) -> list[dict[str, Any]]:
    with closing(_connect(data_dir)) as conn:
        rows = conn.execute(
            """
            SELECT id, patient_id, title, turns_json, primary_formula, summary_text, created_at, updated_at
            FROM consult_sessions
            WHERE patient_id = ?
            ORDER BY updated_at DESC, created_at DESC
            """,
            (patient_id,),
        ).fetchall()
        return [_row_to_session_summary(r) for r in rows]


def create_session(
    data_dir: Path,
    patient_id: str,
    *,
    title: str = "",
    intake: dict[str, Any] | None = None,
    pinned_entity: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not get_patient(data_dir, patient_id):
        return None
    now = _now_iso()
    ses_id = f"ses_{uuid.uuid4().hex[:10]}"
    clean_title = (title or "").strip()[:60] or "新开问诊"
    intake_obj = intake if isinstance(intake, dict) else {}
    summary = str(intake_obj.get("query") or "").strip()[:80] or "待录入症状"
    with closing(_connect(data_dir)) as conn:
        conn.execute(
            "INSERT INTO consult_sessions (id, patient_id, title, intake_json, pinned_json, turns_json, packet_json, primary_formula, summary_text, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ses_id,
                patient_id,
                clean_title,
                json.dumps(intake_obj, ensure_ascii=False),
                json.dumps(pinned_entity, ensure_ascii=False),
                "[]",
                "null",
                "",
                summary,
                now,
                now,
            ),
        )
        conn.execute("UPDATE patients SET updated_at = ? WHERE id = ?", (now, patient_id))
        conn.commit()
    return get_session(data_dir, ses_id)


def get_session(data_dir: Path, session_id: str) -> dict[str, Any] | None:
    with closing(_connect(data_dir)) as conn:
        row = conn.execute("SELECT * FROM consult_sessions WHERE id = ?", (session_id,)).fetchone()
        return _row_to_session_detail(row) if row else None


def _derive_session_meta(
    explicit_title: str | None,
    existing_title: str,
    intake: dict[str, Any],
    turns: list[Any],
    latest_packet: dict[str, Any] | None,
    pinned_entity: dict[str, Any] | None,
) -> tuple[str, str, str]:
    primary_formula = ""
    if isinstance(latest_packet, dict):
        matched = (latest_packet.get("case_packet") or latest_packet).get("matched_formulas") or []
        if matched and isinstance(matched[0], dict):
            primary_formula = str(matched[0].get("name") or "")

    first_user_q = ""
    for t in turns:
        if isinstance(t, dict) and t.get("role") == "user" and t.get("query"):
            first_user_q = str(t["query"]).strip()
            break
    intake_q = str(intake.get("query") or "").strip()
    pinned_name = str((pinned_entity or {}).get("name") or "").strip()

    summary_text = (first_user_q or intake_q or pinned_name or "待录入症状").replace("\n", " ")[:90]

    if explicit_title is not None and explicit_title.strip():
        title = explicit_title.strip()[:60]
    elif existing_title and existing_title != "新开问诊":
        title = existing_title
    else:
        head = (first_user_q or intake_q or pinned_name).replace("\n", " ").strip()
        if head and primary_formula:
            title = f"{head[:14]} · {primary_formula}"
        elif head:
            title = head[:24]
        elif primary_formula:
            title = primary_formula
        else:
            title = "新开问诊"

    return title[:60], primary_formula[:40], summary_text


def save_session(
    data_dir: Path,
    session_id: str,
    *,
    title: str | None = None,
    intake: dict[str, Any] | None = None,
    pinned_entity: dict[str, Any] | None = None,
    turns: list[Any] | None = None,
    latest_packet: dict[str, Any] | None = None,
    update_pinned: bool = False,
    update_packet: bool = False,
) -> dict[str, Any] | None:
    existing = get_session(data_dir, session_id)
    if not existing:
        return None
    next_intake = intake if isinstance(intake, dict) else existing["intake"]
    next_pinned = pinned_entity if update_pinned else existing["pinned_entity"]
    next_turns = turns if isinstance(turns, list) else existing["turns"]
    # Keep persisted turns slim (strip duplicate heavy packet snapshots inside turns; latest_packet holds active context)
    slim_turns: list[dict[str, Any]] = []
    for t in next_turns[-40:]:
        if not isinstance(t, dict):
            continue
        copy_t = {k: v for k, v in t.items() if k not in {"packet", "streaming"}}
        slim_turns.append(copy_t)
    next_packet = latest_packet if update_packet else existing["latest_packet"]

    new_title, primary_formula, summary_text = _derive_session_meta(
        title,
        existing["title"],
        next_intake,
        slim_turns,
        next_packet,
        next_pinned,
    )
    now = _now_iso()
    with closing(_connect(data_dir)) as conn:
        conn.execute(
            """
            UPDATE consult_sessions
            SET title = ?, intake_json = ?, pinned_json = ?, turns_json = ?, packet_json = ?,
                primary_formula = ?, summary_text = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                new_title,
                json.dumps(next_intake, ensure_ascii=False),
                json.dumps(next_pinned, ensure_ascii=False),
                json.dumps(slim_turns, ensure_ascii=False),
                json.dumps(next_packet, ensure_ascii=False),
                primary_formula,
                summary_text,
                now,
                session_id,
            ),
        )
        conn.execute("UPDATE patients SET updated_at = ? WHERE id = ?", (now, existing["patient_id"]))
        conn.commit()
    return get_session(data_dir, session_id)


def delete_session(data_dir: Path, session_id: str) -> tuple[bool, str | None]:
    existing = get_session(data_dir, session_id)
    if not existing:
        return False, None
    pat_id = existing["patient_id"]
    with closing(_connect(data_dir)) as conn:
        cur = conn.execute("DELETE FROM consult_sessions WHERE id = ?", (session_id,))
        conn.commit()
        return cur.rowcount > 0, pat_id
