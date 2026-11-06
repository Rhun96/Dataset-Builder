"""Чтение состояний базы знаний: txt/md/html/docx -> разделы.

Раздел: heading/level/pos/text. Заголовок — best effort, его отсутствие
не ошибка: тогда «Раздел N». PDF и сети нет (ТЗ §15).
"""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path


def read_kb(path: str | Path) -> dict:
    ext = Path(path).suffix.lower()
    if ext == ".txt":
        return {"format": "txt", "sections": _read_txt(path)}
    if ext in (".md", ".markdown"):
        return {"format": "md", "sections": _read_md(path)}
    if ext in (".html", ".htm"):
        return {"format": "html", "sections": _read_html(path)}
    if ext == ".docx":
        return {"format": "docx", "sections": _read_docx(path)}
    raise ValueError(f"формат БЗ не поддержан: {ext!r} (txt/md/html/docx)")


def _read_txt(path) -> list[dict]:
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    blocks = [b.strip() for b in text.split("\n\n") if b.strip()]
    out = []
    for i, b in enumerate(blocks):
        lines = [x.strip() for x in b.splitlines() if x.strip()]
        if len(lines) > 1 and (len(lines[0]) <= 80 or lines[0].endswith(":")):
            out.append({"heading": lines[0], "level": 1, "pos": i,
                        "text": "\n".join(lines[1:])})
        else:
            out.append({"heading": f"Раздел {i + 1}", "level": 0, "pos": i, "text": b})
    return out or [{"heading": "Документ", "level": 0, "pos": 0, "text": ""}]


def _read_md(path) -> list[dict]:
    out = []
    cur = {"heading": "Начало", "level": 0, "pos": 0, "text": ""}
    for line in Path(path).read_text(encoding="utf-8-sig", errors="replace").splitlines():
        s = line.strip()
        if s.startswith("#"):
            level = len(s) - len(s.lstrip("#"))
            if cur["text"].strip() or cur["heading"] != "Начало":
                out.append(cur)
            cur = {"heading": s.lstrip("#").strip() or "Без названия",
                   "level": min(level, 6), "pos": len(out), "text": ""}
        elif s:
            cur["text"] += (("\n" if cur["text"] else "") + s)
    out.append(cur)
    return out


class _Html(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out: list[dict] = []
        self.cur = {"heading": "Начало", "level": 0, "pos": 0, "text": ""}
        self._head: tuple[int, str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._head = (int(tag[1]), "")

    def handle_endtag(self, tag):
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6") and self._head:
            level, text = self._head
            if self.cur["text"].strip() or self.cur["heading"] != "Начало":
                self.out.append(self.cur)
            self.cur = {"heading": text.strip() or "Без названия",
                        "level": level, "pos": len(self.out), "text": ""}
            self._head = None

    def handle_data(self, data):
        s = data.strip()
        if not s:
            return
        if self._head is not None:
            self._head = (self._head[0], self._head[1] + " " + s)
        else:
            self.cur["text"] += (("\n" if self.cur["text"] else "") + s)


def _read_html(path) -> list[dict]:
    p = _Html()
    p.feed(Path(path).read_text(encoding="utf-8-sig", errors="replace"))
    p.out.append(p.cur)
    return p.out


def _read_docx(path) -> list[dict]:
    try:
        from docx import Document
    except ImportError as e:
        raise ValueError("для .docx нужен python-docx: pip install python-docx") from e
    doc = Document(str(path))
    out = []
    cur = {"heading": "Начало", "level": 0, "pos": 0, "text": ""}

    def _push():
        if cur["text"].strip() or cur["heading"] != "Начало":
            out.append(dict(cur))

    for para in doc.paragraphs:
        s = para.text.strip()
        if not s:
            continue
        style = (para.style.name or "").lower()
        if style.startswith("heading"):
            _push()
            try:
                level = int("".join(c for c in style if c.isdigit()) or 1)
            except ValueError:
                level = 1
            cur = {"heading": s, "level": min(level, 6), "pos": len(out), "text": ""}
        else:
            cur["text"] += (("\n" if cur["text"] else "") + s)
    for table in doc.tables:
        for row in table.rows:
            s = " | ".join(c.text.strip() for c in row.cells if c.text.strip())
            if s:
                cur["text"] += (("\n" if cur["text"] else "") + s)
    _push()
    return out or [{"heading": "Документ", "level": 0, "pos": 0, "text": ""}]
