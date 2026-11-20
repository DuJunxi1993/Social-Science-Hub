#!/usr/bin/env python3
"""打包语料快照。

语料是这个项目的核心资产，但它有 226 MB —— 太大，进不了 git，也放不进
release assets 的舒适区（虽然技术上放得下）。于是分两层发：

- ``tei-<版本>.tar.gz``  —— 41 个源 TEI，压缩后 17 MB。
  这是**事实来源**：任何人都能拿它重建出完全等价的语料库。
- ``corpus-<版本>.db.gz`` —— 建好的语料库，压缩后 62 MB。
  给不想自己跑 ETL 的人直接用。

外加一份 ``manifest-<版本>.json``：文件校验和、逐卷的来源 URL 与
源文件 sha256、语料的内容指纹。有了它，别人才能验证自己拿到的东西
是不是这一份。

用法::

    python tools/make-snapshot.py                  # 打包当前语料
    python tools/make-snapshot.py --version 1.1    # 指定版本号
    python tools/make-snapshot.py --verify         # 只验已有快照，不重打
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TEI_DIR = DATA / "tei"
CORPUS = DATA / "corpus.db"
DIST = ROOT / "dist"

# 三套数字版 —— 快照必须原样带上 CC BY 4.0 要求的署名
EDITIONS = {
    "hegel": {
        "name": "黑格尔",
        "site": "https://hegel.idealismedition.com",
        "attribution": "Giuliano Infantino, Digitale Hegel-Edition, hegel.idealismedition.com",
    },
    "fichte": {
        "name": "费希特",
        "site": "https://fichte.idealismedition.com",
        "attribution": "Giuliano Infantino, Digitale Fichte-Edition",
    },
    "schelling": {
        "name": "谢林",
        "site": "https://schelling.idealismedition.com",
        "attribution": "Giuliano Infantino, Digitale Schelling-Edition, schelling.idealismedition.com",
    },
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def content_fingerprint(path: Path) -> dict:
    """语料的内容指纹。

    对每个内容单元（连同它所在的卷、页码、层次、行号、跨度）与每条脚注
    按固定顺序哈希。**只管内容，不管 SQLite 的物理布局** —— 这样重建出来
    的库即使字节不同，指纹也一样，能证明内容没变。
    """
    conn = sqlite3.connect(path)
    units = hashlib.sha256()
    count = 0
    for row in conn.execute(
        "SELECT w.edition, w.siglum, u.kind, u.book_page, u.pdf_page,"
        "       u.text, u.lines, u.spans"
        "  FROM unit u JOIN work w ON w.id = u.work_id"
        " ORDER BY w.edition_order, w.sort_order, u.ord"
    ):
        units.update(repr(row).encode())
        count += 1
    footnotes = hashlib.sha256()
    for row in conn.execute("SELECT id, text, spans FROM footnote ORDER BY work_id, id"):
        footnotes.update(repr(row).encode())
    works = conn.execute(
        "SELECT count(*),"
        "       (SELECT count(*) FROM page),"
        "       (SELECT count(*) FROM section),"
        "       (SELECT count(*) FROM footnote)"
        "  FROM work"
    ).fetchone()
    volumes = [
        dict(zip(("id", "edition", "siglum", "title", "source_url", "source_sha256"), row))
        for row in conn.execute(
            "SELECT id, edition, siglum, title, source_url, source_sha256"
            "  FROM work ORDER BY edition_order, sort_order"
        )
    ]
    conn.close()
    return {
        "units": count,
        "works": works[0],
        "pages": works[1],
        "sections": works[2],
        "footnotes": works[3],
        "unit_fingerprint": units.hexdigest(),
        "footnote_fingerprint": footnotes.hexdigest(),
        "volumes": volumes,
    }


def pack_tei(version: str) -> Path:
    out = DIST / f"tei-{version}.tar.gz"
    with tarfile.open(out, "w:gz") as tar:
        tar.add(TEI_DIR, arcname="tei")
    return out


def pack_corpus(version: str) -> Path:
    out = DIST / f"corpus-{version}.db.gz"
    with CORPUS.open("rb") as src, gzip.open(out, "wb", compresslevel=9) as dst:
        shutil.copyfileobj(src, dst, 1024 * 1024)
    return out


def build_manifest(version: str, files: list[Path]) -> dict:
    fingerprint = content_fingerprint(CORPUS)
    per_edition: dict[str, dict] = {}
    for vol in fingerprint["volumes"]:
        bucket = per_edition.setdefault(
            vol["edition"],
            {"name": EDITIONS[vol["edition"]]["name"], "works": 0},
        )
        bucket["works"] += 1

    return {
        "snapshot": version,
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "files": [
            {
                "name": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in files
        ],
        "corpus": {
            "works": fingerprint["works"],
            "pages": fingerprint["pages"],
            "sections": fingerprint["sections"],
            "units": fingerprint["units"],
            "footnotes": fingerprint["footnotes"],
            "unit_fingerprint": fingerprint["unit_fingerprint"],
            "footnote_fingerprint": fingerprint["footnote_fingerprint"],
        },
        "editions": [
            {
                "key": key,
                "name": info["name"],
                "site": info["site"],
                "works": per_edition.get(key, {}).get("works", 0),
                "attribution": info["attribution"],
                "license": "CC BY 4.0",
                "license_url": "https://creativecommons.org/licenses/by/4.0/",
            }
            for key, info in EDITIONS.items()
        ],
        "sources": fingerprint["volumes"],
        "text_license": "公有领域（黑格尔 1831 / 费希特 1814 / 谢林 1854）",
        "notes": [
            "tei 包里是各站的源 TEI，用它重建出的库与 corpus 包逐单元等价。",
            "内容指纹只覆盖内容，不覆盖 SQLite 的物理布局 —— 重建出的库"
            "字节可能不同，指纹相同即证明内容一致。",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="1.0", help="快照版本号")
    parser.add_argument("--verify", action="store_true", help="只验已有快照")
    args = parser.parse_args()

    if not CORPUS.exists():
        print(f"没有语料库：{CORPUS}", file=sys.stderr)
        return 1

    DIST.mkdir(exist_ok=True)

    if args.verify:
        manifest_path = DIST / f"manifest-{args.version}.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        ok = True
        for entry in manifest["files"]:
            path = DIST / entry["name"]
            if not path.exists():
                print(f"  ✗ 缺文件 {entry['name']}")
                ok = False
                continue
            actual = sha256_file(path)
            if actual != entry["sha256"]:
                print(f"  ✗ {entry['name']} 校验和不符")
                ok = False
            else:
                print(f"  ✓ {entry['name']}  {entry['bytes'] // 1024} KB")
        print("快照完好" if ok else "快照有问题")
        return 0 if ok else 1

    print(f"打包语料快照 {args.version} …")
    tei = pack_tei(args.version)
    print(f"  {tei.name}  {tei.stat().st_size // 1024} KB")
    corpus = pack_corpus(args.version)
    print(f"  {corpus.name}  {corpus.stat().st_size // 1024} KB")

    manifest = build_manifest(args.version, [tei, corpus])
    manifest_path = DIST / f"manifest-{args.version}.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  {manifest_path.name}  {manifest_path.stat().st_size // 1024} KB")

    c = manifest["corpus"]
    print(
        f"\n语料：{c['works']} 卷 · {c['pages']} 页 · {c['units']} 单元 · "
        f"{c['sections']} 章节 · {c['footnotes']} 脚注"
    )
    print(f"内容指纹：{c['unit_fingerprint'][:32]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
