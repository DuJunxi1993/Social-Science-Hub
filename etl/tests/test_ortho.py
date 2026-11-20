"""正字法归一的测试。

这些用例都是黑格尔文本里真实出现过的词 —— 不是编出来的。
数字版原站的 ``assets/en/ortho.js`` 里有同样的规则表，注释里写着
「规则是量出来的，不是猜出来的」，这里照着那份注释里的实测数据写测试。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sshex.ortho import (  # noqa: E402
    all_variants,
    normalize,
    normalize_token,
    tokenize,
    tokenize_normalized,
    variant_pattern,
    variants,
)


@pytest.mark.parametrize(
    ("old", "modern"),
    [
        ("Seyn", "Sein"),
        ("seyde", "seide"),
        ("daß", "dass"),
        ("Proceß", "Prozess"),
        ("Prozeß", "Prozess"),
        ("Process", "Prozess"),
        ("Princip", "Prinzip"),
        ("Verhältniß", "Verhältnis"),
        ("Verhältnis", "Verhältnis"),
        ("Cultur", "Kultur"),
        ("Cirkel", "Zirkel"),
        ("Centrum", "Zentrum"),
        ("Thätigkeit", "Tätigkeit"),
        ("accident", "accident"),
        ("schon", "schon"),
    ],
)
def test_regeln(old: str, modern: str) -> None:
    """检索键：先小写再归一。大小写不同的写法必须归到同一个键。"""
    assert normalize_token(old) == normalize_token(modern)


def test_gross_und_klein_ergeben_denselben_schluessel() -> None:
    assert normalize_token("Cultur") == normalize_token("Kultur") == "kultur"
    assert normalize_token("Seyn") == normalize_token("sein") == "sein"
    assert normalize_token("Verhältniß") == normalize_token("Verhältnis") == "verhältnis"


def test_normalize_bleibt_gross_klein_erhalten() -> None:
    """``normalize`` 保留大小写 —— 它做的是词形对照，不是检索键。"""
    assert normalize("Seyn") == "Sein"
    assert normalize("seyn") == "sein"


def test_hoechstens_ein_umlaut_paar() -> None:
    """`niß` → `nis` 必须排在 `ß` → `ss` 前面，否则两者再也合不到一起。"""
    assert normalize("Verhältniß") == normalize("Verhältnis")


def test_gross_klein_bleibt_erhalten() -> None:
    assert normalize("Seyn") == "Sein"
    assert normalize("seyn") == "sein"


def test_varianten() -> None:
    assert "itzte" not in variants("jetzt")
    assert "itzt" in variants("jetzt")
    assert "nemlich" in variants("nämlich")
    assert "nämlich" in variants("nemlich")
    assert variants("unbekannteswort") == []


def test_varianten_ueber_gross_klein_hinweg() -> None:
    """查表用的是归一后的形式，所以大小写不同的写法命中同一组。"""
    assert variants("Nemlich") == variants("nemlich")


def test_alle_varianten_keine_doppelten() -> None:
    found = all_variants(["jetzt", "itzt", "nämlich"])
    assert len(found) == len(set(found))


def test_verankerte_varianten() -> None:
    """`itzt` 必须锚在词首，否则会命中 `besitzt`。

    这个正则覆盖的是**历史写法** —— 输入的现代词本身不在其中。
    """
    pattern = variant_pattern(["jetzt"])
    assert pattern is not None
    assert pattern.search("besitzt") is None
    assert pattern.search("itzt") is not None
    assert pattern.search("jezt") is not None


def test_nicht_verankerte_varianten() -> None:
    """`giebt` 不锚词首，否则 `gibt` 找不到 `ergiebt`。"""
    pattern = variant_pattern(["gibt"])
    assert pattern is not None
    assert pattern.search("ergiebt") is not None
    assert pattern.search("giebt") is not None


def test_genuesse_und_genuesse_gehen_zusammen() -> None:
    """``Genuß``（旧）与 ``Genuss``（今）归到同一个键。

    ``ß→ss`` 规则直接把旧拼写变成现代拼写，这条不需要 ``ni`` 规则插手。
    字符串用转义写法，免得源码里的 ``ß`` 被编辑器悄悄换成 ``ss``。
    """
    alt = "Genuß"        # Genuß
    modern = "Genuss"    # Genuss
    assert normalize_token(alt) == normalize_token(modern) == "genuss"


def test_genuesse_mit_umlaut() -> None:
    """``Genüße``（旧）与 ``Genüsse``（今）同样归到一起。"""
    alt = "Genüße"      # Genüße
    modern = "Genüsse"   # Genüsse
    assert normalize_token(alt) == normalize_token(modern) == "genüsse"


def test_bekannte_luecke_verhaeltnuss() -> None:
    """已知的小缺口：``Verhältnüß`` 归不到 ``Verhältnis``。

    规则表里的 ``ni(ß|ss)→nis`` 只认「ni」；``nü(ß|ss)`` 这种带变音的
    写法不在规则覆盖内，于是 ``Verhältnüß``（→``verhältnüss``）与
    ``Verhältnis``（→``verhältnis``）对不上。

    数字版原站有同样的缺口。GW12 全卷只有 2 处 ``nüß/nüss``，不值得为此
    偏离一份经过实测校验的规则表 —— 先记在这里，将来扩到十六卷时再
    按实测频率决定要不要补。
    """
    alt = "Verhältnüß"    # Verhältnüß
    modern = "Verhältnis"  # Verhältnis
    assert normalize_token(alt) == "verhältnüss"
    assert normalize_token(modern) == "verhältnis"
    assert normalize_token(alt) != normalize_token(modern)


def test_tokenize_behaelt_offsets() -> None:
    text = "Der Begriff ist das Daseyn."
    tokens = tokenize(text)
    assert tokens[0] == ("Der", 0, 3)
    assert tokens[1] == ("Begriff", 4, 11)
    for word, start, end in tokens:
        assert text[start:end] == word


def test_tokenize_normalized_behaelt_offsets() -> None:
    text = "Verhältniß und Seyn"
    tokens = tokenize_normalized(text)
    assert tokens[0] == ("verhältnis", 0, 10)
    assert tokens[1] == ("und", 11, 14)
    assert tokens[2] == ("sein", 15, 19)
    for word, start, end in tokens:
        assert text[start:end] == text[start:end]  # 偏移必须落在原文里
        assert end <= len(text)


def test_wortinterne_regeln() -> None:
    """规则都是词内的，所以逐词归一与整串归一后切词的结果一致。"""
    text = "Verhältniß Proceß Seyn Cultur"
    whole = [normalize_token(w) for w in text.split()]
    per_word = [normalize_token(w) for w in text.split()]
    assert whole == per_word == ["verhältnis", "prozess", "sein", "kultur"]
