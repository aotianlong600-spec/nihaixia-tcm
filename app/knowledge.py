"""Local, page-addressable originals and reviewed evidence. Transactions belong to callers."""

from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
import unicodedata
import uuid

# PDF libraries are imported only inside the functions that parse or render
# originals; the portable core consumes pre-extracted text and stays native-free.


MAX_PDF_BYTES = 50 * 1024 * 1024
# PDFium forbids concurrent calls even for different documents.
PDFIUM_LOCK = threading.RLock()
_SHA = re.compile(r"[0-9a-f]{64}\Z")
# shortcut: common clinical variants only; expand from reviewed search failures, not raw text.
_VARIANTS = str.maketrans(dict(pair.split(":") for pair in (
    "湯:汤 薑:姜 兩:两 黃:黄 傷:伤 寒:寒 論:论 匱:匮 經:经 內:内 醫:医 案:案 "
    "陰:阴 陽:阳 氣:气 血:血 脈:脉 證:证 症:症 風:风 熱:热 惡:恶 無:无 頭:头 "
    "嘔:呕 瀉:泻 燥:燥 濕:湿 體:体 虛:虚 實:实 腎:肾 臟:脏 腑:腑 藥:药 "
    "術:术 朮:术 梔:栀 歸:归 棗:枣 蔘:参 參:参 龍:龙 膠:胶 烏:乌 麥:麦 "
    "門:门 開:开 關:关 滿:满 脅:胁 煩:烦 渴:渴 便:便 祕:秘 衛:卫 營:营 "
    "發:发 汗:汗 項:项 強:强 痙:痉 癲:癫 癇:痫 針:针 灸:灸 鍼:针 厚:厚 "
    "樸:朴 連:连 葉:叶 產:产 孕:孕 婦:妇 兒:儿 肺:肺 癰:痈 瘡:疮 瘀:瘀 "
    "塊:块 腫:肿 腸:肠 胃:胃 裡:里 裏:里 結:结 胸:胸 遲:迟 數:数 緊:紧 "
    "澀:涩 濃:浓 動:动 轉:转 壯:壮 診:诊 療:疗 劑:剂 錢:钱 炮:炮 製:制"
).split()))


def _now():
    return datetime.now(timezone.utc).isoformat()


def _normalize(text):
    text = unicodedata.normalize("NFKC", text).translate(_VARIANTS).casefold()
    return "".join(char for char in text if char.isalnum())


def _rows(cursor):
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _document_id(document_id):
    if not isinstance(document_id, str) or not _SHA.fullmatch(document_id):
        raise ValueError("invalid document id")
    return document_id


def _page_number(physical_page):
    if type(physical_page) is not int:
        raise ValueError("physical_page must be an integer")
    return physical_page


def render_page(conn, data_dir, document_id, physical_page):
    import pypdfium2

    path = document_path(conn, data_dir, document_id)
    with PDFIUM_LOCK, pypdfium2.PdfDocument(str(path)) as pdf:
        if type(physical_page) is not int or not 1 <= physical_page <= len(pdf):
            raise ValueError("PDF物理页不存在")
        page = pdf[physical_page - 1]
        try:
            width, height = page.get_width(), page.get_height()
            if width <= 0 or height <= 0:
                raise ValueError("PDF页面尺寸无效")
            bitmap = page.render(scale=min(1.5, 2000 / width, 2800 / height))
            try:
                output = BytesIO()
                with bitmap.to_pil() as image:
                    image.save(output, format="PNG")
                return output.getvalue()
            finally:
                bitmap.close()
        finally:
            page.close()


def _required_text(payload, key, maximum):
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{key} must be nonempty text, at most {maximum} characters")
    return value


def init_knowledge(conn, data_dir):
    originals = Path(data_dir).resolve() / "originals"
    originals.mkdir(parents=True, exist_ok=True)
    if not originals.resolve().is_relative_to(Path(data_dir).resolve()):
        raise ValueError("originals directory leaves data directory")
    statements = [
        """CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, sha256 TEXT NOT NULL UNIQUE,
            physical_pages INTEGER NOT NULL CHECK(physical_pages > 0),
            author_status TEXT NOT NULL, warning TEXT NOT NULL, created_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS pages (
            document_id TEXT NOT NULL REFERENCES documents(id), physical_page INTEGER NOT NULL CHECK(physical_page > 0),
            raw_text TEXT NOT NULL, corrected_text TEXT, search_text TEXT NOT NULL,
            review_status TEXT NOT NULL DEFAULT 'pending' CHECK(review_status IN ('pending','verified')),
            kind TEXT NOT NULL DEFAULT 'unclassified', printed_page TEXT, warning TEXT NOT NULL,
            extraction_method TEXT NOT NULL, reviewer TEXT, note TEXT, reviewed_at TEXT,
            PRIMARY KEY(document_id,physical_page))""",
        """CREATE TABLE IF NOT EXISTS evidence (
            id TEXT PRIMARY KEY, document_id TEXT NOT NULL, sha256 TEXT NOT NULL,
            physical_page INTEGER NOT NULL, quote TEXT NOT NULL, kind TEXT NOT NULL,
            reviewer TEXT NOT NULL, printed_page TEXT, start INTEGER NOT NULL, end INTEGER NOT NULL,
            source_type TEXT NOT NULL, raw_text TEXT NOT NULL, corrected_text TEXT,
            extraction_method TEXT NOT NULL, created_at TEXT NOT NULL,
            FOREIGN KEY(document_id,physical_page) REFERENCES pages(document_id,physical_page))""",
        "CREATE INDEX IF NOT EXISTS evidence_document_page ON evidence(document_id,physical_page)",
    ]
    for statement in statements:
        conn.execute(statement)


def list_documents(conn):
    return _rows(conn.execute("""SELECT d.id,d.title,d.sha256,d.physical_pages,
        COUNT(CASE WHEN p.review_status='verified' THEN 1 END) AS reviewed_pages,
        CASE WHEN COUNT(CASE WHEN p.review_status='verified' THEN 1 END)=d.physical_pages THEN 'verified'
             WHEN COUNT(CASE WHEN p.review_status='verified' THEN 1 END)>0 THEN 'partial' ELSE 'pending' END AS status,
        d.author_status,d.warning FROM documents d LEFT JOIN pages p ON p.document_id=d.id
        GROUP BY d.id ORDER BY d.created_at,d.id"""))


def _registered(conn, sha):
    return conn.execute("SELECT 1 FROM documents WHERE id=?", (sha,)).fetchone() is not None


def _pdf_bytes(source):
    import pypdfium2

    source = Path(source)
    if not source.is_file() or source.stat().st_size > MAX_PDF_BYTES:
        raise ValueError("PDF must be a file no larger than 50 MiB")
    content = source.read_bytes()
    if len(content) > MAX_PDF_BYTES:
        raise ValueError("PDF exceeds 50 MiB")
    try:
        with PDFIUM_LOCK, pypdfium2.PdfDocument(content) as pdf:
            pages = len(pdf)
    except Exception as exc:
        raise ValueError("unable to read PDF") from exc
    if pages < 1:
        raise ValueError("PDF has no pages")
    return content, hashlib.sha256(content).hexdigest(), pages


def _original_path(data_dir, sha):
    root = Path(data_dir).resolve()
    original = root / "originals" / f"{sha}.pdf"
    if not original.resolve().is_relative_to(root):
        raise ValueError("original path leaves data directory")
    return original


def _preserve(data_dir, sha, content):
    target = _original_path(data_dir, sha)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if hashlib.sha256(target.read_bytes()).hexdigest() != sha:
            raise ValueError("registered original hash mismatch")
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".tmp", delete=False) as file:
            temporary = Path(file.name)
            file.write(content)
        temporary.replace(target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _warning(title, number, text, page):
    warnings = []
    if not text.strip():
        warnings.append("无可提取文字；可能为图像或空白页，需人工对照或OCR")
    elif len(_normalize(text)) < 50:
        warnings.append("提取文字极少；需对照原件")
    if "\ufffd" in text or page.get("replacement_characters", 0) or page.get("private_use_characters", 0) or page.get("other_control_characters", 0):
        warnings.append("提取含异常字符；需人工核对")
    if page.get("error") or page.get("extraction_error"):
        warnings.append("该页提取异常；需人工处理")
    if "伤寒" in title and number in (15, 16, 19, 34):
        warnings.append("审计抽查发现文本顺序错乱或句子碎裂；未订正")
    if "金匮" in title and number == 12:
        warnings.append("审计抽查发现粗体条文重复提取；未去重或订正")
    if "内经" in title and number == 2:
        warnings.append("审计抽查发现原文与解说顺序错乱；未订正")
    if "伤寒" in title and number == 209:
        warnings.append("含校正截图；需图像与文字分开校核")
    return "；".join(warnings)


def _store_document(conn, data_dir, content, sha, title, pages, method):
    if _registered(conn, sha):
        document_path(conn, data_dir, sha)
        return {**next(item for item in list_documents(conn) if item["id"] == sha), "duplicate": True}
    _preserve(data_dir, sha, content)
    unconfirmed = "内经" in title
    warning = "全部页面均为待校核提取文本；不代表医学审核"
    if unconfirmed:
        warning += "；解说作者归属未明，不自动标为倪氏观点"
    if "伤寒" in title or "金匮" in title or unconfirmed:
        warning += "；已知文本顺序或重复异常见页面警告"
    conn.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,?)", (sha, title, sha, len(pages), "unconfirmed" if unconfirmed else "unverified", warning, _now()))
    for page in pages:
        text = page["text"]
        conn.execute("""INSERT INTO pages(document_id,physical_page,raw_text,search_text,warning,extraction_method)
            VALUES (?,?,?,?,?,?)""", (sha, page["physical_page"], text, _normalize(text), _warning(title, page["physical_page"], text, page), method))
    return {**next(item for item in list_documents(conn) if item["id"] == sha), "duplicate": False}


def import_pdf(conn, data_dir, source: Path, title: str = "") -> dict:
    import pdfplumber

    if not isinstance(title, str) or len(title) > 500:
        raise ValueError("title must be at most 500 characters")
    content, sha, physical_pages = _pdf_bytes(source)
    title = title.strip() or Path(source).stem
    if _registered(conn, sha):
        return _store_document(conn, data_dir, content, sha, title, [], "")
    pages = []
    try:
        with pdfplumber.open(BytesIO(content)) as pdf:
            if len(pdf.pages) != physical_pages:
                raise ValueError("PDF page count mismatch")
            for number, page in enumerate(pdf.pages, 1):
                try:
                    text = page.extract_text(layout=True, x_tolerance=2, y_tolerance=3) or ""
                    pages.append({"physical_page": number, "text": text})
                except Exception:
                    pages.append({"physical_page": number, "text": "", "extraction_error": True})
    except Exception as exc:
        raise ValueError("unable to extract PDF") from exc
    return _store_document(conn, data_dir, content, sha, title, pages, "pdfplumber coordinate layout; unreviewed")


def import_audit(conn, data_dir, manifest_path: Path) -> dict:
    """Trusted local CLI only: validate all sources and page sequences before writing rows."""
    manifest_path = Path(manifest_path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        documents = manifest["documents"]
        if not isinstance(documents, list) or not documents:
            raise ValueError("audit contains no documents")
        prepared = []
        for doc in documents:
            source = Path(doc["preserved_copy_path"])
            if not source.is_absolute():
                source = manifest_path.parent / source
            content, sha, physical_pages = _pdf_bytes(source)
            if sha != doc["source_sha256"] or sha != doc["copy_sha256"]:
                raise ValueError("audit PDF hash mismatch")
            if type(doc["physical_pages"]) is not int or physical_pages != doc["physical_pages"] or doc.get("extracted_pages", physical_pages) != physical_pages:
                raise ValueError("audit physical page count mismatch")
            pages_path = Path(doc["pages_json_path"])
            if not pages_path.is_absolute():
                pages_path = manifest_path.parent / pages_path
            pages = json.loads(pages_path.read_text(encoding="utf-8-sig"))
            if not isinstance(pages, list) or len(pages) != physical_pages:
                raise ValueError("audit extracted page count mismatch")
            for number, page in enumerate(pages, 1):
                if not isinstance(page, dict) or type(page.get("physical_page")) is not int or page["physical_page"] != number or not isinstance(page.get("text"), str):
                    raise ValueError("audit pages must have consecutive 1-based numbers and original text")
            title = Path(doc["filename"]).stem
            prepared.append((content, sha, title, pages))
    except (KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
        raise ValueError("invalid audit manifest or pages") from exc
    items = [_store_document(conn, data_dir, content, sha, title, pages, str(manifest.get("method", "audit original extraction"))) for content, sha, title, pages in prepared]
    return {"imported": sum(not item["duplicate"] for item in items), "duplicates": sum(item["duplicate"] for item in items), "physical_pages": sum(item["physical_pages"] for item in items), "documents": items}


def search(conn, query: str, document_id: str | None = None, limit: int = 30) -> list[dict]:
    if not isinstance(query, str) or len(query) > 256:
        raise ValueError("query must be text at most 256 characters")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    if document_id is not None:
        _document_id(document_id)
    normalized = _normalize(query)
    if not normalized:
        return []
    rows = _rows(conn.execute("""SELECT p.document_id,d.title,p.physical_page,p.raw_text,p.corrected_text,
        p.review_status,p.warning,d.warning AS document_warning FROM pages p JOIN documents d ON d.id=p.document_id
        WHERE p.search_text LIKE ? AND (? IS NULL OR p.document_id=?)
        ORDER BY p.document_id,p.physical_page LIMIT ?""", (f"%{normalized}%", document_id, document_id, limit)))
    items = []
    for row in rows:
        text = row.pop("corrected_text")
        raw = row.pop("raw_text")
        text = raw if text is None else text
        # Index normalization can change offsets; locate a window in the displayed original text.
        position = 0
        for index, char in enumerate(text):
            if _normalize(text[index:index + max(80, len(query) * 4)]).find(normalized) >= 0:
                position = index
                break
        row["snippet"] = text[max(0, position - 40):position + 240]
        row["warning"] = "；".join(filter(None, [row["warning"], row.pop("document_warning")]))
        row["pdf_url"] = f"/api/documents/{row['document_id']}/pdf#page={row['physical_page']}"
        items.append(row)
    return items


def get_page(conn, document_id, physical_page) -> dict | None:
    _document_id(document_id)
    _page_number(physical_page)
    document = conn.execute("SELECT physical_pages FROM documents WHERE id=?", (document_id,)).fetchone()
    if document is None or not 1 <= physical_page <= document[0]:
        return None
    rows = _rows(conn.execute("""SELECT document_id,physical_page,raw_text,corrected_text,review_status,
        kind,printed_page,warning,extraction_method FROM pages WHERE document_id=? AND physical_page=?""", (document_id, physical_page)))
    return rows[0] if rows else None


def review_page(conn, document_id, physical_page, payload) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("review must be an object")
    page = get_page(conn, document_id, physical_page)
    if page is None:
        raise ValueError("page does not exist")
    corrected = _required_text(payload, "corrected_text", 200000)
    kind = _required_text(payload, "kind", 100)
    reviewer = _required_text(payload, "reviewer", 200)
    note = _required_text(payload, "note", 10000)
    printed = payload.get("printed_page")
    if printed is not None and (not isinstance(printed, str) or not printed.strip() or len(printed) > 100):
        raise ValueError("printed_page must be nonempty text or null")
    conn.execute("""UPDATE pages SET corrected_text=?, search_text=?,review_status='verified',kind=?,
        printed_page=?,reviewer=?,note=?,reviewed_at=? WHERE document_id=? AND physical_page=?""",
        (corrected, _normalize(corrected), kind, printed, reviewer, note, _now(), document_id, physical_page))
    return get_page(conn, document_id, physical_page)


def create_evidence(conn, payload) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("evidence must be an object")
    page = get_page(conn, payload.get("document_id"), payload.get("physical_page"))
    if page is None or page["review_status"] != "verified":
        raise ValueError("page must be text-reviewed before evidence creation")
    quote = _required_text(payload, "quote", 50000)
    kind = _required_text(payload, "kind", 100)
    reviewer = _required_text(payload, "reviewer", 200)
    text = page["corrected_text"] if page["corrected_text"] is not None else page["raw_text"]
    start = text.find(quote)
    if start < 0:
        raise ValueError("quote is not a contiguous substring of the reviewed page")
    printed = payload.get("printed_page", page["printed_page"])
    if printed is not None and (not isinstance(printed, str) or not printed.strip() or len(printed) > 100):
        raise ValueError("printed_page must be nonempty text or null")
    evidence_id = uuid.uuid4().hex
    conn.execute("INSERT INTO evidence VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
        evidence_id, page["document_id"], page["document_id"], page["physical_page"], quote, kind, reviewer, printed,
        start, start + len(quote), "raw" if text == page["raw_text"] else "corrected", page["raw_text"],
        page["corrected_text"], page["extraction_method"], _now(),
    ))
    return get_evidence(conn, evidence_id)


def get_evidence(conn, evidence_id) -> dict | None:
    if not isinstance(evidence_id, str) or not evidence_id or len(evidence_id) > 100:
        raise ValueError("invalid evidence id")
    rows = _rows(conn.execute("SELECT * FROM evidence WHERE id=?", (evidence_id,)))
    return rows[0] if rows else None


def list_evidence(conn) -> list[dict]:
    return _rows(conn.execute("SELECT * FROM evidence ORDER BY created_at,id"))


def document_path(conn, data_dir, document_id) -> Path:
    sha = _document_id(document_id)
    if not _registered(conn, sha):
        raise ValueError("document is not registered")
    path = _original_path(data_dir, sha)
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != sha:
        raise ValueError("registered original is missing or hash mismatch")
    return path
