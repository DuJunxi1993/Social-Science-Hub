"""命令行入口。

    python -m sshex build --work all                  # 三家版本的全部卷
    python -m sshex build --work gw-12                # 只建一卷
    python -m sshex build --work fichte                # 只建费希特
    python -m sshex list                              # 列出各卷
    python -m sshex stats --db data/corpus.db         # 看看库里有什么
    python -m sshex search --db data/corpus.db "Begriff und Sein"
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .db import build_corpus, open_db
from .fetch import EDITIONS, Edition, fetch_tei, sigle, works_of
from .tei import parse_tei

DEFAULT_DB = Path("data/corpus.db")
DEFAULT_CACHE = Path("data/tei")


def _select(args: argparse.Namespace) -> list[tuple[Edition, dict]]:
    """要建哪些卷。

    ``--work`` 可以是：

    - ``all`` —— 三家版本全部
    - ``hegel`` / ``fichte`` / ``schelling`` —— 某个版本的全部
    - 具体作品 id（``gw-12``、``fsw-1``、``sw-I-01``）—— 一卷
    """
    work = args.work
    if work == "all":
        keys = list(EDITIONS)
    elif work in EDITIONS:
        keys = [work]
    elif work == "pilot":
        keys = ["hegel"]
        args.work = "gw-12"
    else:
        # 单卷：先找出它属于哪个版本
        keys = []
        for key, edition in EDITIONS.items():
            for entry in works_of(edition):
                if entry["work_id"] == work:
                    return [(edition, entry)]
        raise SystemExit(f"不知道这个作品：{work}")

    out: list[tuple[Edition, dict]] = []
    for key in keys:
        edition = EDITIONS[key]
        out.extend((edition, entry) for entry in works_of(edition))
    return out


def _fetch_all(
    targets: list[tuple[Edition, dict]],
    cache_dir: Path,
    *,
    refresh: bool = False,
    workers: int = 6,
) -> None:
    """并行下载各卷的源 TEI。

    已经在缓存里的卷不占网络。下载失败的不在这里报错 —— 那要等解析那一轮
    再说，好让「一卷取不到」不至于毁掉其余各卷。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    missing = []
    for edition, entry in targets:
        work_id = entry["work_id"]
        path = cache_dir / f"{edition.key}-{sigle(work_id)}.xml"
        if refresh or not path.exists():
            missing.append((edition, work_id))

    if not missing:
        return

    print(f"下载 {len(missing)} 卷源 TEI（并行 {workers} 路）…", flush=True)
    started = time.time()
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                fetch_tei, edition, work_id, cache_dir, refresh=refresh
            ): (edition, work_id)
            for edition, work_id in missing
        }
        for future in as_completed(futures):
            edition, work_id = futures[future]
            done += 1
            try:
                future.result()
                mark = "✓"
            except Exception as error:  # noqa: BLE001 —— 失败要报告，但要继续
                mark = "✗"
                print(f"  {mark} {edition.name} {work_id}: {error}", flush=True)
            else:
                print(f"  {mark} {edition.name} {work_id}", flush=True)
    print(f"下载用时 {time.time() - started:.0f}s", flush=True)


def cmd_build(args: argparse.Namespace) -> int:
    db_path = Path(args.db)
    cache_dir = Path(args.cache)

    targets = _select(args)

    # 先把源 TEI 全部取回来。下载是网络往返（每卷 0.3–2 MB，实测每卷
    # 60–100 秒），解析与入库却只要不到一秒 —— 所以下载并行，解析串行。
    _fetch_all(targets, cache_dir, refresh=args.refresh, workers=args.workers)

    conn = open_db(db_path, create=True)
    total = 0
    # 卷次：站点给的卷目本来就是排好序的，记下序号当排序键
    edition_order = {}
    sort_order = {}
    for index, (edition, entry) in enumerate(targets):
        edition_order.setdefault(edition.key, list(EDITIONS).index(edition.key))
        sort_order[(edition.key, entry["work_id"])] = index
    for edition, entry in targets:
        work_id = entry["work_id"]
        started = time.time()
        print(f"→ {edition.name} {work_id} ({entry.get('siglum')})", flush=True)
        data, url, digest = fetch_tei(edition, work_id, cache_dir, refresh=args.refresh)
        volume = parse_tei(data)
        stats = build_corpus(
            conn,
            volume,
            edition=edition.key,
            edition_order=edition_order[edition.key],
            sort_order=sort_order[(edition.key, work_id)],
            source_url=url,
            source_sha256=digest,
        )
        elapsed = time.time() - started
        print(
            f"  {stats['pages']} 页 · {stats['units']} 单元 · {stats['lines']} 印刷行 · "
            f"{stats['headings']} 标题 · {stats['footnotes']} 脚注 · "
            f"{stats['tokens']} 词  [{elapsed:.1f}s]",
            flush=True,
        )
        total += stats["units"]
    conn.close()
    print(f"完成：{len(targets)} 卷，共 {total} 个单元 → {db_path}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    for key, edition in EDITIONS.items():
        print(f"\n═══ {edition.name}（{edition.site}）═══")
        try:
            works = works_of(edition)
        except Exception as error:  # noqa: BLE001 —— 列不出来就说说
            print(f"  取不到卷目：{error}")
            continue
        for entry in works:
            print(f"{entry['work_id']:>10}  {entry.get('siglum', ''):<8} {entry.get('title', '')}")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    conn = open_db(Path(args.db))
    rows = conn.execute(
        """
        SELECT w.id, w.edition, w.siglum, w.title,
               (SELECT COUNT(*) FROM page    p WHERE p.work_id = w.id) AS pages,
               (SELECT COUNT(*) FROM unit    u WHERE u.work_id = w.id) AS units,
               (SELECT COUNT(*) FROM section s WHERE s.work_id = w.id) AS sections,
               (SELECT COUNT(*) FROM footnote f WHERE f.work_id = w.id) AS footnotes
        FROM work w
        ORDER BY w.edition, w.siglum
        """
    ).fetchall()
    if not rows:
        print("库里还没有数据。先跑 `python -m sshex build --work all`。")
        return 1
    for row in rows:
        print(
            f"{row['edition']:>10} {row['id']:>10}  {row['siglum']:<8} {row['title']}\n"
            f"       {row['pages']} 页 · {row['units']} 单元 · {row['sections']} 章节 · "
            f"{row['footnotes']} 脚注"
        )
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    from .search import search

    conn = open_db(Path(args.db))
    query = " ".join(args.query)
    results = search(conn, query, limit=args.limit)
    print(f"{len(results)} 处命中：")
    for hit in results:
        print(
            f"  {hit['siglum']} {hit['book_page']}.{hit['gw_line']}  {hit['section']}\n"
            f"      {hit['snippet']}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sshex", description="德国理想主义语料 ETL")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="下载并解析 TEI，写入 SQLite")
    build.add_argument(
        "--work",
        default="pilot",
        help="all / hegel / fichte / schelling，或具体作品 id（gw-12、fsw-1…）",
    )
    build.add_argument("--db", default=str(DEFAULT_DB))
    build.add_argument("--cache", default=str(DEFAULT_CACHE))
    build.add_argument("--refresh", action="store_true", help="忽略本地缓存重新下载")
    build.add_argument("--workers", type=int, default=6, help="并行下载的线程数")
    build.set_defaults(func=cmd_build)

    listing = sub.add_parser("list", help="列出各卷")
    listing.set_defaults(func=cmd_list)

    stats = sub.add_parser("stats", help="统计库里的内容")
    stats.add_argument("--db", default=str(DEFAULT_DB))
    stats.set_defaults(func=cmd_stats)

    search = sub.add_parser("search", help="在库里检索")
    search.add_argument("--db", default=str(DEFAULT_DB))
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("query", nargs="+")
    search.set_defaults(func=cmd_search)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
