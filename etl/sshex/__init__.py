"""黑格尔语料的 ETL 管线。

从 *Digital Hegel Edition* 的源 TEI 出发，产出离线应用可直接使用的 SQLite 库。

    from sshex import fetch_tei, parse_tei, open_db, build_corpus

    data, url, digest = fetch_tei("gw-12", "data/tei")
    volume = parse_tei(data)
    conn = open_db("data/corpus.db", create=True)
    build_corpus(conn, volume, source_url=url, source_sha256=digest)
"""

from .db import build_corpus, open_db
from .fetch import EDITIONS, Edition, fetch_tei, sigle, tei_url, works_of
from .ortho import normalize, normalize_token, tokenize, variants
from .search import parse_query, search
from .tei import Line, Page, Span, Unit, Volume, parse_tei

__version__ = "0.1.0"

__all__ = [
    "EDITIONS",
    "Edition",
    "works_of",
    "Line",
    "Page",
    "Span",
    "Unit",
    "Volume",
    "build_corpus",
    "fetch_tei",
    "normalize",
    "normalize_token",
    "open_db",
    "parse_query",
    "parse_tei",
    "search",
    "sigle",
    "tei_url",
    "tokenize",
    "variants",
]
