"""从数字版下载源 TEI。

三家版本，同一套做法：

====================== ====================================================
版本                    站点
====================== ====================================================
``hegel``              https://hegel.idealismedition.com
``fichte``             https://fichte.idealismedition.com
``schelling``          https://schelling.idealismedition.com
====================== ====================================================

都由 Giuliano Infantino 编纂，**CC BY 4.0**；原文本身是公有领域。

**卷目不写死在代码里** —— 每个站点都有一份 ``assets/edition-data.js``，
里面列了全部卷的 id、卷标、书名、版权。我们从那儿读，这样站点更新了
卷目，这边跟着更新，不用改代码。

TEI 的文件名由作品 id 推出来：``gw-12`` → ``GW12``、``fsw-1`` → ``FSW1``、
``sw-I-01`` → ``SWI01`` —— 去掉非字母数字字符再转大写（原站的做法）。

下载的文件缓存在本地，重复 ETL 不再走网络。SHA-256 记进库里，
这样换机器重跑时能确认拿到的是同一份文本。
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

__all__ = [
    "EDITIONS",
    "Edition",
    "edition_names",
    "sigle",
    "tei_url",
    "fetch_tei",
    "fetch_edition_data",
    "works_of",
    "all_works",
]


class Edition:
    """一个数字版。"""

    def __init__(self, key: str, name: str, site: str, author: str) -> None:
        self.key = key
        #: 中文名，界面用
        self.name = name
        #: 站点根
        self.site = site.rstrip("/")
        #: 作者（德文姓名，引用时用）
        self.author = author

    def url(self, path: str) -> str:
        return f"{self.site}/{path.lstrip('/')}"

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<Edition {self.key} {self.name}>"


#: 三家版本。
EDITIONS: dict[str, Edition] = {
    "hegel": Edition(
        "hegel",
        "黑格尔",
        "https://hegel.idealismedition.com",
        "Hegel, Georg Wilhelm Friedrich",
    ),
    "fichte": Edition(
        "fichte",
        "费希特",
        "https://fichte.idealismedition.com",
        "Fichte, Johann Gottlieb",
    ),
    "schelling": Edition(
        "schelling",
        "谢林",
        "https://schelling.idealismedition.com",
        "Schelling, Friedrich Wilhelm Joseph von",
    ),
}


def edition_names() -> dict[str, str]:
    """版本 key → 中文名。"""
    return {key: edition.name for key, edition in EDITIONS.items()}


def sigle(work_id: str) -> str:
    """作品 id → 源 TEI 的文件名（不含扩展名）。

    通用规则（原站的 ``sigle()``）：去掉非字母数字字符，再转大写。
    ``fsw-1`` → ``FSW1``、``sw-I-01`` → ``SWI01``。
    """
    return re.sub(r"[^A-Za-z0-9]", "", work_id).upper()


def sigle_candidates(work_id: str) -> list[str]:
    """可能的文件名，按可能性排序。

    费希特与谢林用通用规则；**黑格尔不一样** —— 它的卷号补零到两位
    （``gw-1`` → ``GW01`` 而不是 ``GW1``）。两家的 ``sigle()`` 实现并不相同，
    所以候选都列出来，让下载时挑能用的那个。
    """
    out = [sigle(work_id)]
    match = re.fullmatch(r"gw-(\d+)", work_id)
    if match:
        padded = f"GW{int(match.group(1)):02d}"
        if padded not in out:
            out.append(padded)
    return out


def tei_url(edition: Edition, work_id: str) -> str:
    return edition.url(f"assets/tei/{sigle_candidates(work_id)[0]}.xml")


def _get(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Social-Science-Hub/0.1 (offline reader; CC BY 4.0 corpus)"
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.URLError as error:
        raise RuntimeError(f"下载 {url} 失败：{error}") from error


def fetch_edition_data(edition: Edition, *, timeout: float = 60.0) -> dict:
    """读站点的 ``edition-data.js``，解出里面的 JSON。

    文件形如 ``window.HEGEL_EDITION = {…};`` —— 把赋值号右边抠出来解析。
    """
    raw = _get(edition.url("assets/edition-data.js"), timeout).decode("utf-8")
    match = re.search(r"window\.HEGEL_EDITION\s*=\s*(\{.*\})\s*;?\s*$", raw, re.S)
    if not match:
        raise RuntimeError(f"{edition.name}：看不懂 edition-data.js 的格式")
    return json.loads(match.group(1))


def works_of(edition: Edition, *, timeout: float = 60.0) -> list[dict]:
    """这个版本的全部卷。

    顺序按站点给的来 —— 站点已经排好了卷次（黑格尔按 GW 号，费希特按
    SW/NW，谢林按 SW I/1、I/2…）。
    """
    data = fetch_edition_data(edition, timeout=timeout)
    return list(data.get("works", []))


def all_works(editions: list[str] | None = None) -> list[tuple[Edition, dict]]:
    """要建的卷：``(版本, 卷信息)`` 的列表。"""
    keys = editions or list(EDITIONS)
    out: list[tuple[Edition, dict]] = []
    for key in keys:
        edition = EDITIONS[key]
        for work in works_of(edition):
            out.append((edition, work))
    return out


def fetch_tei(
    edition: Edition,
    work_id: str,
    cache_dir: str | Path,
    *,
    timeout: float = 180.0,
    refresh: bool = False,
) -> tuple[bytes, str, str]:
    """取一卷的源 TEI。

    返回 ``(内容, 来源 URL, SHA-256)``。已缓存且未要求刷新时直接读本地。
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    # 缓存里按候选名找 —— 黑格尔和别家的命名规则不同
    candidates = sigle_candidates(work_id)
    for name in candidates:
        path = cache_dir / f"{edition.key}-{name}.xml"
        if path.exists() and not refresh:
            data = path.read_bytes()
            return data, edition.url(f"assets/tei/{name}.xml"), hashlib.sha256(data).hexdigest()

    # 都不在缓存里就下载。文件名规则两家不同，挨个试，能用的那个就是它。
    errors = []
    for name in candidates:
        url = edition.url(f"assets/tei/{name}.xml")
        try:
            data = _get(url, timeout)
        except RuntimeError as error:
            errors.append(str(error))
            continue
        path = cache_dir / f"{edition.key}-{name}.xml"
        path.write_bytes(data)
        return data, url, hashlib.sha256(data).hexdigest()

    raise RuntimeError("；".join(errors))
