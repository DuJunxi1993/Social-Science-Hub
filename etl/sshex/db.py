"""SQLite 落库层。

产物是一个自包含的 ``corpus.db``：语料、版面、检索索引全在一个文件里，
Tauri 应用把它当作只读资源打包，首启动复制到应用数据目录。

**用户数据不放在这里。** 批注、书签、个人词库属于用户，属于应用数据目录里
另一个可写的库。语料升级（换一卷、重新 ETL）不该动用户的笔记。

检索用 FTS5。索引里存的是**归一后**的词（``Verhältniß`` → ``verhältnis``），
显示的永远是原文 —— 见 :mod:`sshex.ortho`。
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Iterable

from .ortho import tokenize_normalized
from .tei import Unit, Volume

__all__ = ["SCHEMA", "open_db", "build_corpus", "CorpusStats"]

SCHEMA = """
PRAGMA foreign_keys = ON;

-- ── 卷 ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS work (
    id                TEXT PRIMARY KEY,
    -- 版本：hegel / fichte / schelling
    edition           TEXT NOT NULL DEFAULT 'hegel',
    -- 版本内的卷次。站点给的卷目本来就是排好序的，ETL 直接记下序号。
    edition_order     INTEGER NOT NULL DEFAULT 0,
    sort_order        INTEGER NOT NULL DEFAULT 0,
    -- 作者：Hegel, Georg Wilhelm Friedrich
    author            TEXT,
    siglum            TEXT NOT NULL,
    series            TEXT,
    volume_number     TEXT,
    title             TEXT,
    short_title       TEXT,
    source_title      TEXT,
    publisher         TEXT,
    license_text      TEXT,
    license_database  TEXT,
    license_url       TEXT,
    license_attribution TEXT,
    license_excludes  TEXT,
    source_url        TEXT,
    source_sha256     TEXT,
    built_at          TEXT
);

-- ── 印刷页 ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS page (
    work_id        TEXT NOT NULL REFERENCES work(id),
    pdf_page       INTEGER NOT NULL,
    book_page      TEXT,
    page_kind      TEXT,
    has_apparatus  INTEGER NOT NULL DEFAULT 0,
    running_header TEXT,
    signature      TEXT,
    PRIMARY KEY (work_id, pdf_page)
);

-- ── 章节 ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS section (
    id        INTEGER PRIMARY KEY,
    work_id   TEXT NOT NULL REFERENCES work(id),
    ord       INTEGER NOT NULL,
    level     INTEGER NOT NULL,
    title     TEXT NOT NULL,
    path      TEXT NOT NULL,
    book_page TEXT,
    pdf_page  INTEGER,
    unit_id   INTEGER
);

-- ── 内容单元 ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS unit (
    id          INTEGER PRIMARY KEY,
    work_id     TEXT NOT NULL REFERENCES work(id),
    ord         INTEGER NOT NULL,
    pdf_page    INTEGER NOT NULL,
    book_page   TEXT,
    section_id  INTEGER REFERENCES section(id),
    kind        TEXT NOT NULL,
    text        TEXT NOT NULL DEFAULT '',
    spans       TEXT NOT NULL DEFAULT '[]',
    refs        TEXT NOT NULL DEFAULT '[]',
    line_map    TEXT NOT NULL DEFAULT '[]',
    lines       TEXT NOT NULL DEFAULT '[]',
    meta        TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS unit_work_page ON unit (work_id, pdf_page, ord);
CREATE INDEX IF NOT EXISTS unit_section    ON unit (section_id);
CREATE INDEX IF NOT EXISTS unit_book_page  ON unit (work_id, book_page);

-- ── 脚注 ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS footnote (
    -- 完整的 xml:id —— ``fn-233-1`` 或它的第二段 ``fn-233-1.t2``。
    --
    -- **主键是 (work_id, id)，不是光 id。** 脚注的 id 里带着页码
    -- （``fn-135-1`` = 第 135 页第 1 条），只在**一卷之内**唯一 ——
    -- 每一卷都有自己的 ``fn-135-1``。光拿 id 当主键，后建的卷会把
    -- 先建的卷的脚注顶掉（四十一卷建下来，脚注能少一半）。
    id             TEXT NOT NULL,
    -- 去掉 ``.tN`` 后的 id：把同一条脚注的各段归到一起
    base_id        TEXT,
    work_id        TEXT NOT NULL REFERENCES work(id),
    unit_id        INTEGER REFERENCES unit(id),
    part           INTEGER,
    -- 脚注的位置：页脚 / 边注 / 行下 / 行上（空 = 页脚）
    place_kind     TEXT,
    marker         TEXT,
    anchor_gw_line INTEGER,
    book_page      TEXT,
    gw_line        INTEGER,
    prev_id        TEXT,
    next_id        TEXT,
    text           TEXT NOT NULL DEFAULT '',
    spans          TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (work_id, id)
);
CREATE INDEX IF NOT EXISTS footnote_base ON footnote (work_id, base_id);
CREATE INDEX IF NOT EXISTS footnote_unit ON footnote (unit_id);

-- ── 互引 ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS xref (
    id       INTEGER PRIMARY KEY,
    work_id  TEXT NOT NULL REFERENCES work(id),
    unit_id  INTEGER REFERENCES unit(id),
    kind     TEXT NOT NULL,
    target   TEXT,
    label    TEXT
);
CREATE INDEX IF NOT EXISTS xref_unit ON xref (unit_id);

-- ── 印刷目录（书前的目录页） ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS toc_printed (
    id       INTEGER PRIMARY KEY,
    work_id  TEXT NOT NULL REFERENCES work(id),
    ord      INTEGER NOT NULL,
    level    INTEGER,
    title    TEXT NOT NULL,
    book_page TEXT
);

-- ── 全文索引 ──────────────────────────────────────────────────────────
-- 存归一后的词。rowid 对应 unit.id。
CREATE VIRTUAL TABLE IF NOT EXISTS unit_fts USING fts5(
    text,
    tokenize = 'unicode61 remove_diacritics 2'
);

-- 这里**没有**「词 → 偏移」表。
--
-- 检索命中后要指出原文的哪一段，乍看需要一张带偏移的词表（十六卷近两百万
-- 个词，连索引要 101 MB，占全库的 58%）。但 FTS5 已经告诉我们「这个单元
-- 命中了」，剩下的只是在一千三百来个字里找那几个词 —— 检索时现切现算，
-- 是微秒级的，比从磁盘读一百万行快得多，库也瘦了一百多兆。
"""


class CorpusStats(dict):
    """ETL 结果摘要。"""


def open_db(path: str | Path, *, create: bool = False) -> sqlite3.Connection:
    """打开（必要时创建）语料库。"""
    path = Path(path)
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


# --------------------------------------------------------------------------
# 写入
# --------------------------------------------------------------------------


def _spans_json(spans: Iterable) -> str:
    return json.dumps(
        [{"s": s.start, "e": s.end, "k": s.kind} for s in spans], ensure_ascii=False
    )


def _lines_json(lines: Iterable) -> str:
    return json.dumps(
        [
            {
                "n": line.number,
                "t": line.text,
                "s": [{"s": s.start, "e": s.end, "k": s.kind} for s in line.spans],
            }
            for line in lines
        ],
        ensure_ascii=False,
    )


def build_corpus(
    conn: sqlite3.Connection,
    volume: Volume,
    *,
    edition: str = "hegel",
    edition_order: int = 0,
    sort_order: int = 0,
    source_url: str = "",
    source_sha256: str = "",
) -> CorpusStats:
    """把一卷写进库。

    已经是同一卷时先清掉旧数据，保证 ETL 可以反复跑。
    """
    meta = volume.metadata
    work_id = meta.get("work_id") or ""
    if not work_id:
        raise ValueError("TEI 里没有 work_id")

    # 删除顺序要照顾外键：先删指向 unit 的，再删 unit，最后删被 unit 指向的 section。
    conn.execute("DELETE FROM unit_fts WHERE rowid IN (SELECT id FROM unit WHERE work_id = ?)", (work_id,))
    conn.execute("DELETE FROM xref WHERE work_id = ?", (work_id,))
    conn.execute("DELETE FROM footnote WHERE work_id = ?", (work_id,))
    conn.execute("DELETE FROM unit WHERE work_id = ?", (work_id,))
    conn.execute("DELETE FROM section WHERE work_id = ?", (work_id,))
    conn.execute("DELETE FROM page WHERE work_id = ?", (work_id,))
    conn.execute("DELETE FROM toc_printed WHERE work_id = ?", (work_id,))
    conn.execute("DELETE FROM work WHERE id = ?", (work_id,))

    conn.execute(
        """
        INSERT INTO work (id, edition, edition_order, sort_order, author, siglum,
                          series, volume_number, title, short_title, source_title,
                          publisher, license_text, license_database, license_url,
                          license_attribution, license_excludes, source_url,
                          source_sha256, built_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
        """,
        (
            work_id,
            edition,
            edition_order,
            sort_order,
            meta.get("author"),
            meta.get("siglum") or "",
            meta.get("series"),
            meta.get("volume_number"),
            meta.get("title"),
            meta.get("short_title"),
            meta.get("source_title"),
            meta.get("publisher"),
            meta.get("license_text"),
            meta.get("license_database"),
            meta.get("license_url"),
            meta.get("license_attribution"),
            meta.get("license_excludes"),
            source_url,
            source_sha256,
        ),
    )

    stats = CorpusStats(
        work_id=work_id,
        pages=0,
        units=0,
        lines=0,
        headings=0,
        footnotes=0,
        tokens=0,
        sections=0,
    )

    # 章节不从正文的标题推层级 —— 那样会得到一棵平的、重复的树。
    # **书前的印刷目录（``toc_printed``）是权威**：它自带层级（``item/@n``）
    # 和 GW 页码（``ref/@n``），就是这本书自己印的目录。
    #
    # 层级关系按「栈」重建：遇到 level L 的条目，先把栈里所有 >= L 的弹出，
    # 剩下的最后一条就是父节点。
    section_specs: list[dict] = []
    stack: list[tuple[int, str]] = []

    for entry in volume.toc_printed:
        level = entry.get("level") or 1
        title = entry["title"].strip()
        book_page = entry.get("page")
        if not title:
            continue
        stack = [(lv, t) for lv, t in stack if lv < level]
        path = " › ".join([t for _, t in stack] + [title])
        stack.append((level, title))
        section_specs.append(
            {
                "level": level,
                "title": title,
                "path": path,
                "book_page": book_page,
                "pdf_page": None,
                "unit_id": None,
            }
        )

    unit_ord = 0
    # (unit_id, book_page, pdf_page, title)
    heading_units: list[tuple[int, int | None, int | None, str]] = []

    for page in volume.pages:
        conn.execute(
            """
            INSERT INTO page (work_id, pdf_page, book_page, page_kind, has_apparatus,
                              running_header, signature)
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                work_id,
                page.pdf_page,
                page.book_page,
                page.kind,
                1 if page.has_apparatus else 0,
                page.running_header,
                page.signature,
            ),
        )
        stats["pages"] += 1

        for unit in page.units:
            if unit.kind == "spacer":
                continue

            cursor = conn.execute(
                """
                INSERT INTO unit (work_id, ord, pdf_page, book_page, section_id, kind,
                                  text, spans, refs, line_map, lines, meta)
                VALUES (?,?,?,?,NULL,?,?,?,?,?,?,?)
                """,
                (
                    work_id,
                    unit_ord,
                    page.pdf_page,
                    page.book_page,
                    unit.kind,
                    unit.text,
                    _spans_json(unit.spans),
                    json.dumps(unit.refs, ensure_ascii=False),
                    json.dumps(
                        [[a, b, c] for a, b, c in unit.line_map], ensure_ascii=False
                    ),
                    _lines_json(unit.lines),
                    json.dumps(unit.meta, ensure_ascii=False),
                ),
            )
            unit_id = int(cursor.lastrowid)
            unit_ord += 1
            stats["units"] += 1
            stats["lines"] += len(unit.lines)

            if unit.kind in ("heading", "subheading"):
                stats["headings"] += 1
                heading_units.append((unit_id, page.book_page, page.pdf_page, unit.text.strip()))

            # 脚注
            if unit.kind == "footnote":
                footnote_id = unit.meta.get("footnote_id")
                if footnote_id:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO footnote
                            (id, base_id, work_id, unit_id, part, place_kind, marker,
                             anchor_gw_line, book_page, gw_line, prev_id, next_id,
                             text, spans)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            footnote_id,
                            unit.meta.get("footnote_base_id"),
                            work_id,
                            unit_id,
                            unit.meta.get("part"),
                            unit.meta.get("place_kind"),
                            unit.meta.get("marker"),
                            unit.meta.get("anchor_gw_line"),
                            page.book_page,
                            unit.lines[0].number if unit.lines else None,
                            unit.meta.get("prev_id"),
                            unit.meta.get("next_id"),
                            unit.text,
                            _spans_json(unit.spans),
                        ),
                    )
                    stats["footnotes"] += 1

            # 全文索引与词表。
            # 只索引正文页：目录页（``type="toc"``）、书名页（``title_page``）
            # 里的文字进了索引，搜“Inhalt”“Verlag”会满屏噪声 —— 数字版
            # 原站也是这么取舍的。但这些页**照常可读**，只是不进索引。
            if page.kind == "body":
                normalized = tokenize_normalized(unit.text)
                conn.execute(
                    "INSERT INTO unit_fts (rowid, text) VALUES (?,?)",
                    (unit_id, " ".join(word for word, _, _ in normalized)),
                )
                stats["tokens"] += len(normalized)
            else:
                stats["skipped_pages"] = stats.get("skipped_pages", 0) + 1

    # 章节落库
    section_ids: list[int] = []
    for ord_, spec in enumerate(section_specs):
        cursor = conn.execute(
            """
            INSERT INTO section (work_id, ord, level, title, path, book_page, pdf_page, unit_id)
            VALUES (?,?,?,?,?,?,NULL,NULL)
            """,
            (work_id, ord_, spec["level"], spec["title"], spec["path"], spec["book_page"]),
        )
        section_ids.append(int(cursor.lastrowid))
        spec["id"] = int(cursor.lastrowid)
    stats["sections"] = len(section_specs)

    # 给每个章节找到它在正文里的落点。
    #
    # 两条路子：
    #   a) **按标题配对** —— 目录里写 „DRUCKSCHRIFTEN“，正文里也有同名标题，
    #      就以那个标题单元为落点。有些卷的分部标题在目录里没有页码
    #      （GW 15 的三个分部就是），只能靠配对找到位置。
    #   b) **按页码找该页第一个标题** —— 目录把 „Erstes Kapitel. Der Begriff“
    #      写在一行，正文里却是 „ERSTES KAPITEL.“ 和 „DER BEGRIFF.“ 两行，
    #      配不上，就落到那页的第一个标题上。
    heading_index: dict[str, tuple[int, int | None, int | None]] = {}
    for unit_id, unit_book_page, unit_pdf_page, title in heading_units:
        key = _normalize_title(title)
        if key and key not in heading_index:
            heading_index[key] = (unit_id, unit_book_page, unit_pdf_page)

    first_heading_on_page: dict[int | None, tuple[int, int | None, int | None]] = {}
    for unit_id, unit_book_page, unit_pdf_page, _title in heading_units:
        if unit_book_page not in first_heading_on_page:
            first_heading_on_page[unit_book_page] = (unit_id, unit_book_page, unit_pdf_page)

    for spec in section_specs:
        anchor = None
        matched = heading_index.get(_normalize_title(spec["title"]))
        if matched:
            anchor = matched
        elif spec["book_page"] is not None:
            anchor = first_heading_on_page.get(spec["book_page"])
        if anchor is None:
            continue

        unit_id, anchor_gw, anchor_pdf = anchor
        spec["unit_id"] = unit_id
        if spec["book_page"] is None:
            spec["book_page"] = anchor_gw
        spec["pdf_page"] = anchor_pdf
        conn.execute(
            "UPDATE section SET unit_id = ?2, pdf_page = ?3, book_page = ?4 WHERE id = ?1",
            (spec["id"], spec["unit_id"], spec["pdf_page"], spec["book_page"]),
        )

    # 单元归到章节：章节的落点之后、下一个落点之前，都属于这个章节。
    anchor_rows = [
        (spec["id"], spec["unit_id"]) for spec in section_specs if spec["unit_id"]
    ]
    if anchor_rows:
        conn.execute("DROP TABLE IF EXISTS temp.section_anchor")
        conn.execute(
            "CREATE TEMP TABLE section_anchor (section_id INTEGER, unit_id INTEGER)"
        )
        conn.executemany("INSERT INTO section_anchor VALUES (?, ?)", anchor_rows)

        conn.execute(
            """
            UPDATE unit SET section_id = (
                SELECT sa.section_id FROM section_anchor sa
                WHERE sa.unit_id <= unit.id
                ORDER BY sa.unit_id DESC LIMIT 1
            )
            WHERE EXISTS (SELECT 1 FROM section_anchor sa WHERE sa.unit_id <= unit.id)
            """
        )
        conn.execute("DROP TABLE IF EXISTS temp.section_anchor")

    for ord_, entry in enumerate(volume.toc_printed):
        conn.execute(
            "INSERT INTO toc_printed (work_id, ord, level, title, book_page) VALUES (?,?,?,?,?)",
            (work_id, ord_, entry.get("level"), entry["title"], entry.get("page")),
        )

    conn.commit()
    return stats



def _normalize_title(title: str) -> str:
    """标题配对用的归一：大小写、标点、空白都不算数。

    目录里写 „Erstes Kapitel. Der Begriff“，正文里印成 „ERSTES KAPITEL.“
    —— 配对时不能被大小写和句点绊住。
    """
    text = re.sub(r"[\s\u00a0]+", " ", title or "").strip().lower()
    return text.strip(" .:;,·—–-()")


def _normalized_text(text: str) -> str:
    """把文本转成「词 词 词」的形式供 FTS5 索引。

    FTS5 的 ``unicode61`` 会按非字母数字切词；我们先把每个词归一并用空格
    连接，切词结果与原文一致，但词形已是现代拼写。
    """
    from .ortho import tokenize_normalized

    return " ".join(token for token, _, _ in tokenize_normalized(text))


