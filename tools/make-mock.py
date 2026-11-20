#!/usr/bin/env python3
"""从前端测试用的真实语料生成 mock 数据。

Playwright 的前端测试不连真数据库 —— Tauri 的 IPC 得在真应用里才有。
所以从 ``data/corpus.db`` 里取一小片数据，存成 ``mock-data.json``，
由 ``shoot.js`` 在页面里注入。

用法::

    python tools/make-mock.py            # 生成 tools/mock-data.json
    python tools/make-mock.py --check    # 只看统计，不写文件

语料变了（重建了库、加了新版本）就重新跑一遍。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "data" / "corpus.db"
OUT = Path(__file__).resolve().parent / "mock-data.json"

sys.path.insert(0, str(ROOT / "etl"))

# 检索用的两个词 —— 都要跨版本命中，才测得到「结果按卷分组」
SEARCH_TERMS = ("Verhältniß", "Vernunft")
SECOND_TERMS = ("Aufhebung",)

# 无论搜到什么都要在的卷：三家版本各来一卷
ALWAYS_INCLUDE = ("gw-1", "gw-12", "fsw-1", "sw-I-01")


def snake_to_camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part.capitalize() for part in rest)


def camelize(value):
    """把 sqlite 的行转成前端要的形式（snake_case → camelCase）。"""
    if isinstance(value, dict):
        return {snake_to_camel(k): camelize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [camelize(item) for item in value]
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="只打印统计")
    args = parser.parse_args()

    if not CORPUS.exists():
        print(f"没有语料库：{CORPUS}", file=sys.stderr)
        print("先跑：cd etl && ./.venv/bin/python -m sshex build --work all", file=sys.stderr)
        return 1

    from sshex.search import search

    conn = sqlite3.connect(CORPUS)
    conn.row_factory = sqlite3.Row

    def rows(query: str, *params):
        return [camelize(dict(row)) for row in conn.execute(query, params)]

    def hits(term: str, limit: int = 24):
        out = []
        for hit in search(conn, term, limit=limit):
            row = conn.execute(
                "SELECT id, siglum FROM work WHERE id ="
                " (SELECT work_id FROM unit WHERE id = ?)",
                (hit.unit_id,),
            ).fetchone()
            out.append(
                {
                    "unitId": hit.unit_id,
                    "bookPage": hit.book_page,
                    "gwLine": hit.gw_line,
                    "pdfPage": hit.pdf_page,
                    "section": hit.section,
                    "snippet": hit.snippet,
                    "matches": hit.matches,
                    "score": hit.score,
                    "kind": hit.kind,
                    "workId": row["id"],
                    "siglum": row["siglum"],
                }
            )
        return out

    found = []
    for term in SEARCH_TERMS:
        found.extend(hits(term))
    found.extend(hits(SECOND_TERMS[0]))

    works = sorted({h["workId"] for h in found} | set(ALWAYS_INCLUDE))

    sections_by_work: dict[str, list] = {}
    pages_by_work: dict[str, list] = {}
    units_by_work: dict[str, dict] = {}
    footnotes_by_work: dict[str, list] = {}

    for work in works:
        sections = rows(
            "SELECT id, ord, level, title, path, book_page, pdf_page, unit_id"
            " FROM section WHERE work_id = ? ORDER BY ord",
            work,
        )
        sections_by_work[work] = sections
        pages_by_work[work] = rows(
            "SELECT pdf_page, book_page, page_kind, has_apparatus,"
            " running_header, signature FROM page WHERE work_id = ? ORDER BY pdf_page",
            work,
        )
        footnotes_by_work[work] = rows(
            "SELECT id, unit_id, part, marker, anchor_gw_line, book_page, gw_line,"
            " text, spans FROM footnote WHERE work_id = ?"
            " ORDER BY book_page, gw_line LIMIT 40",
            work,
        )

        # 要装进 mock 的页：头几页 + 目录指到的页 + 检索命中的页
        wanted = {1, 2, 3, 4, 5, 6, 7, 8}
        wanted |= {
            s["pdfPage"] for s in sections[:20] if s.get("pdfPage") is not None
        }
        wanted |= {h["pdfPage"] for h in found if h["workId"] == work}

        units: dict[str, list] = {}
        for pdf_page in sorted(wanted):
            page_units = []
            for row in conn.execute(
                "SELECT * FROM unit WHERE work_id = ? AND pdf_page = ? ORDER BY ord",
                (work, pdf_page),
            ):
                unit = dict(row)
                for key in ("spans", "refs", "lines", "line_map", "meta"):
                    unit[key] = json.loads(unit[key] or "[]")
                page_units.append(camelize(unit))
            if page_units:
                units[str(pdf_page)] = page_units
        units_by_work[work] = units

    data = {
        "list_works": rows(
            "SELECT id, edition, author, siglum, title, short_title, source_title,"
            " series, volume_number, license_attribution, license_database,"
            " license_url, source_url FROM work ORDER BY edition_order, sort_order"
        ),
        "search_corpus": found,
        "search_corpus_b": hits(SECOND_TERMS[0]),
        "sections_by_work": sections_by_work,
        "pages_by_work": pages_by_work,
        "units_by_work": units_by_work,
        "footnotes_by_work": footnotes_by_work,
        "get_settings": {},
        "get_progress": None,
        "list_annotations": [],
        "list_bookmarks": [],
        "list_glossary": [],
    }

    size = len(json.dumps(data, ensure_ascii=False).encode())
    print(f"{len(works)} 卷 · {len(found)} 条检索命中 · {size // 1024} KB")
    if not args.check:
        OUT.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        print(f"已写入 {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
