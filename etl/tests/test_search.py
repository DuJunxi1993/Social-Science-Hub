"""查询解析的测试。

这些用例与 Rust 端（``app/src-tauri/src/search.rs``）的单元测试**一一对应**。
两边的实现是同一套逻辑的两份，行为必须一致 —— ��则同一个查询在命令行里
和在应用里会给出不同的结果。

改动任何一边的时候，记得把对边的用例一起改。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sshex.search import parse_query  # noqa: E402


def test_单个词() -> None:
    q = parse_query("Begriff")
    assert q.fts == '("begriff")'
    assert q.terms == ["begriff"]


def test_隐含的与() -> None:
    q = parse_query("genauer Begriff")
    assert q.fts == '(("genauer") AND ("begriff"))'
    assert q.terms == ["genauer", "begriff"]


def test_短语() -> None:
    q = parse_query('"genauer Begriff"')
    assert q.fts == '"genauer begriff"'
    assert q.terms == ["genauer", "begriff"]


def test_前缀() -> None:
    q = parse_query("Subject*")
    assert q.fts == '("subjekt"*)'
    assert q.terms == []
    assert q.prefix_terms == ["subjekt"]


def test_显式与() -> None:
    q = parse_query("Begriff AND Sein")
    assert q.fts == '(("begriff") AND ("sein"))'


def test_非是二元运算() -> None:
    """FTS5 的 NOT 是二元运算符，不能当前缀用。"""
    q = parse_query("Begriff NOT Sein")
    assert q.fts == '(("begriff") NOT ("sein"))'


def test_括号() -> None:
    """括号必须各自独立成词，不能粘在词上。"""
    q = parse_query("(a OR b) c")
    assert q.fts == '(((("a") OR ("b"))) AND ("c"))'
    assert q.terms == ["a", "b", "c"]


def test_旧拼写归一() -> None:
    q = parse_query("Verhältniß")
    assert q.terms == ["verhältnis"]
    assert q.fts == '("verhältnis")'


def test_异体展开() -> None:
    """异体展开后，FTS5 表达式里应当是「或」。"""
    q = parse_query("nemlich")
    assert "nemlich" in q.terms
    assert "nämlich" in q.terms


def test_精确匹配不展开异体() -> None:
    q = parse_query("=nemlich")
    assert q.terms == ["nemlich"]


def test_片段保留两个命中之间的原文() -> None:
    """两个命中之间的原文必须留在片段里。

    早先的窗口算法把「吸附到词边界」的结果又夹回了上一个命中的末尾，
    于是中间那段从来没进过片段 —— 片段里会看到 „VerhältnißVerhältniß“
    这种两个词粘在一起的样子。
    """
    from sshex.search import _match_positions, _snippet

    text = (
        "Verhältniß der Begriffe speculativ ganz eigenthümlich – "
        "anderes Verhältniß folgt unmittelbar."
    )
    positions = _match_positions(text, ["verhältnis"])
    assert positions == [(0, 10), (64, 74)]

    snippet, ranges = _snippet(text, positions, 90)
    assert "der Begriffe speculativ" in snippet, "中间那段原文被吞了"
    assert snippet.count("Verhältniß") == 2
    assert ranges == [(0, 10), (64, 74)]


def test_空查询() -> None:
    assert parse_query("").fts == ""
    assert parse_query("   ").fts == ""


def test_问号按前缀处理() -> None:
    """``Begrif?`` 找的是 „Begriff“ —— 拿问号之前的部分当前缀。"""
    q = parse_query("Begrif?")
    assert q.fts == '("begrif"*)'
    assert q.prefix_terms == ["begrif"]
    assert q.terms == []
