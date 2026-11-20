"""检索层。

分两步：

1. **找单元** —— FTS5 在归一后的词表上匹配，得到命中的是哪些单元、排在什么位置。
2. **指出原文在哪** —— FTS5 只能回答「这个单元里有这个词」，答不出「在第几个
   字符」。所以把命中的单元正文重新切词、逐词归一，再看哪些词命中 —— 高亮与
   KWIC 上下文都从**原文**取，不从归一文本取。

这一层与 Rust 端（``app/src-tauri/src/search.rs``）是同一套逻辑的两份实现，
行为必须一致：同一份查询在两边给出同样的命中、同样的高亮区间。

查询语法（与数字版原站的思路一致，但实现换成 SQLite）：

=================== ==========================================================
``a b``             两词都出现（隐含 AND）
``a AND b``         同上
``a OR b``          任一
``a NOT b``         有 a 无 b
``"genauer Begriff"`` 短语
``Begriff*``        前缀
``a NEAR b``        相邻（``nah`` 是同一个意思）
``=begriff``        精确匹配，不展开屈折
=================== ==========================================================
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

from .ortho import all_variants, normalize_token, tokenize_normalized, variants

__all__ = ["search", "parse_query", "Query", "SearchHit"]

#: 记号：引号里的短语算一个，括号各自独立，其余按空白切。
#:
#: 括号必须**单独**成词 —— 否则 ``(a OR b) c`` 会被切成 ``(a``、``OR``、
#: ``b)``、``c``，那个 ``b)`` 里的括号就跟着词走了。
_TOKEN = re.compile(r'"[^"]*"|[()]|[^\s()]+')


# --------------------------------------------------------------------------
# 查询解析
# --------------------------------------------------------------------------


@dataclass
class Query:
    """解析后的查询。"""

    fts: str                     # 交给 FTS5 的表达式
    terms: list[str] = field(default_factory=list)   # 参与高亮的归一词（精确）
    prefix_terms: list[str] = field(default_factory=list)  # 前缀词（``词*``）
    exact: bool = False          # 是否只做了精确匹配（未展开异体）


def _quote(term: str) -> str:
    """FTS5 字符串字面量：双引号内部按 ``""`` 转义。"""
    return '"' + term.replace('"', '""') + '"'


def parse_query(query: str) -> Query:
    """把用户输入变成 FTS5 表达式与高亮词表。"""
    parser = _Parser(query)
    fts = parser.parse_or()
    return Query(
        fts=fts,
        terms=parser.terms,
        prefix_terms=parser.prefix_terms,
        exact=not parser.expanded,
    )


class _Parser:
    """递归下降的查询解析器。

    FTS5 的 ``NOT`` 是**二元**运算符（``A NOT B``），所以它跟 ``AND`` 一样
    在同一层处理，不能当成前缀。
    """

    def __init__(self, query: str) -> None:
        self.tokens = _TOKEN.findall(query or "")
        self.pos = 0
        self.terms: list[str] = []
        self.prefix_terms: list[str] = []
        self.expanded = False

    def peek(self) -> str | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def push_term(self, word: str) -> None:
        if word and word not in self.terms:
            self.terms.append(word)

    def push_prefix_term(self, word: str) -> None:
        if word and word not in self.prefix_terms:
            self.prefix_terms.append(word)

    def parse_or(self) -> str:
        """or_expr := and_expr (OR and_expr)*"""
        left = self.parse_and()
        if not left:
            return ""
        while (token := self.peek()) and token.upper() == "OR":
            self.pos += 1
            right = self.parse_and()
            if not right:
                break
            left = f"({left} OR {right})"
        return left

    def parse_and(self) -> str:
        """and_expr := atom ((AND | NOT)? atom)*"""
        left = self.parse_atom()
        if not left:
            return ""
        while True:
            token = self.peek()
            if token is None or token == ")" or token.upper() == "OR":
                break
            if token.upper() == "AND":
                self.pos += 1
                operator = "AND"
            elif token.upper() == "NOT":
                self.pos += 1
                operator = "NOT"
            else:
                operator = "AND"
            right = self.parse_atom()
            if not right:
                break
            left = f"({left} {operator} {right})"
        return left

    def parse_atom(self) -> str:
        """atom := '(' or_expr ')' | "短语" | 词"""
        if self.pos >= len(self.tokens):
            return ""
        token = self.tokens[self.pos]

        if token == "(":
            self.pos += 1
            inner = self.parse_or()
            if self.peek() == ")":
                self.pos += 1
            return f"({inner})" if inner else ""

        if token.startswith('"'):
            phrase = token.strip('"')
            words = [
                normalize_token(w)
                for w in re.findall(r"[^\W_]+", phrase)
            ]
            self.pos += 1
            if not words:
                return ""
            for word in words:
                self.push_term(word)
            return _quote(" ".join(words))

        # 普通词
        self.pos += 1
        exact = token.startswith("=")
        raw = token.lstrip("=")
        # `*` 与 `?` 都按前缀处理：FTS5 不支持单字符通配，但
        # ``Begrif?`` 想找的是 „Begriff“ 这类词 —— 拿问号之前的部分
        # 当前缀，恰好覆盖得到。
        prefix = raw.endswith("*") or "?" in raw
        stem = raw.rstrip("*")
        stem = stem.split("?", 1)[0]

        word = normalize_token(stem)
        if not word:
            return ""

        forms = [word]
        if not exact:
            extra = variants(word)
            if extra:
                forms.extend(extra)
                self.expanded = True

        if prefix:
            for form in forms:
                self.push_prefix_term(form)
            return "(" + " OR ".join(_quote(w) + "*" for w in forms) + ")"

        for form in forms:
            self.push_term(form)
        return "(" + " OR ".join(_quote(w) for w in forms) + ")"


# --------------------------------------------------------------------------
# 检索
# --------------------------------------------------------------------------


@dataclass
class SearchHit:
    unit_id: int
    work_id: str
    siglum: str
    book_page: str | None
    gw_line: int | None
    pdf_page: int
    section: str
    snippet: str
    #: 命中词在 ``snippet`` 中的区间 —— 前端据此高亮，不要在文本里塞标记
    matches: list[tuple[int, int]] = field(default_factory=list)
    score: float = 0.0
    kind: str = ""


def search(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int = 50,
    work_id: str | None = None,
    context: int = 90,
) -> list[SearchHit]:
    """检索并返回带原文片段的命中。"""
    parsed = parse_query(query)
    if not parsed.fts:
        return []

    sql = """
        SELECT f.rowid AS unit_id, bm25(unit_fts) AS score,
               u.book_page, u.pdf_page, u.kind, u.text, u.line_map,
               u.work_id, w.siglum, s.path AS section
        FROM unit_fts f
        JOIN unit u ON u.id = f.rowid
        JOIN work w ON w.id = u.work_id
        LEFT JOIN section s ON s.id = u.section_id
        WHERE unit_fts MATCH ?
    """
    params: list = [parsed.fts]
    if work_id:
        sql += " AND u.work_id = ?"
        params.append(work_id)
    sql += " ORDER BY score LIMIT ?"
    params.append(limit * 3)  # 多取一些，后面要按片段质量再筛

    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        return []

    hits: list[SearchHit] = []
    for row in rows:
        positions = _match_positions(row["text"], parsed.terms, parsed.prefix_terms)
        if not positions and row["kind"] == "paragraph":
            continue
        snippet, matches = _snippet(row["text"], positions, context)
        gw_line = _line_for_position(
            row["line_map"], positions[0][0] if positions else None
        )
        hits.append(
            SearchHit(
                unit_id=row["unit_id"],
                work_id=row["work_id"],
                siglum=row["siglum"],
                book_page=row["book_page"],
                gw_line=gw_line,
                pdf_page=row["pdf_page"],
                section=row["section"] or "",
                snippet=snippet,
                matches=matches,
                score=-row["score"],
                kind=row["kind"],
            )
        )
        if len(hits) >= limit:
            break
    return hits


def _match_positions(
    text: str,
    terms: list[str],
    prefix_terms: list[str] | None = None,
) -> list[tuple[int, int]]:
    """命中词在原文中的 ``(起点, 终点)``。

    词的位置**现算**：把单元正文重新切词、逐词归一，再看哪些词命中。

    为什么不另存一张「词 → 偏移」的表？存了要一百多兆（十六卷近两百万个词，
    连索引共 101 MB，占全库的 58%）—— 而 FTS5 已经告诉我们「这个单元命中了」，
    剩下的只是在这个单元的一千三百来个字里找那几个词。现算一次是微秒级的，
    比从磁盘读一百万行快得多。
    """
    if not terms and not prefix_terms:
        return []
    prefix_terms = prefix_terms or []
    out: list[tuple[int, int]] = []
    for word, start, end in tokenize_normalized(text):
        if word in terms or any(word.startswith(t) for t in prefix_terms):
            out.append((start, end))
    return out


def _snippet(
    text: str, positions: list[tuple[int, int]], context: int
) -> tuple[str, list[tuple[int, int]]]:
    """从原文截一段上下文，并给出命中词在片段中的区间。

    返回 ``(片段, 区间表)``。区间是相对**片段**起点的偏移 —— 前端拿它
    直接套 ``<mark>``，不必在文本里找标记。
    """
    if not positions:
        return text[: context * 2].strip(), []

    merged: list[list[int]] = []
    for start, end in positions:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    out: list[str] = []
    matches: list[tuple[int, int]] = []
    cursor = 0
    length = 0
    for start, end in merged:
        if start - cursor > context * 2:
            # 离得远：只取命中前的一小段，中间用省略号跳过。
            out.append("… ")
            length += 2
            window_start = max(cursor, _snap_left(text, start - context))
            chunk = text[cursor:window_start]
            out.append(chunk)
            length += len(chunk)
        else:
            # 离得近：两个命中之间的原文**整段留下**。
            #
            # （早先这里的窗口起点算错了：把「吸附到词边界」的结果又夹回
            #  上一个命中的末尾，于是中间那段从来没被加进片段 ——
            #  片段里会出现 „VerhältnißVerhältniß“ 这种两个词粘在一起的样子。）
            chunk = text[cursor:start]
            out.append(chunk)
            length += len(chunk)
        out.append(text[start:end])
        matches.append((length, length + (end - start)))
        length += end - start
        cursor = end
    if cursor < len(text):
        tail = text[cursor : cursor + context]
        cut = _snap_right(text, cursor + len(tail))
        out.append(text[cursor:cut])
    return "".join(out).strip(), matches


def _snap_left(text: str, index: int) -> int:
    """把起点往左挪到词边界，免得片段从半个词开始。"""
    index = max(0, min(index, len(text)))
    while index > 0 and text[index - 1].isalnum():
        index -= 1
    return index


def _snap_right(text: str, index: int) -> int:
    """把终点往右挪到词边界。"""
    index = max(0, min(index, len(text)))
    while index < len(text) and text[index].isalnum():
        index += 1
    return index


def _line_for_position(line_map_json: str, position: int | None) -> int | None:
    """位置落在印刷层的哪一行。

    ``line_map`` 是 ``[[起点, 终点, GW 行号], ...]``，由 TEI 解析时建立：
    阅读层的每个字符都记着它属于哪条印刷行。
    """
    if position is None:
        return None
    import json

    try:
        line_map = json.loads(line_map_json or "[]")
    except json.JSONDecodeError:
        return None
    for start, end, number in line_map:
        if start <= position < end:
            return number
    return None
