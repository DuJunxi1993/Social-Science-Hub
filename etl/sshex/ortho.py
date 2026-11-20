"""德语旧正字法归一（Schreibungsausgleich）。

本模块是黑格尔数字版 ``assets/en/ortho.js`` 的 Python 移植，规则表与语义完全一致。

**归一只作用于「检索键」，绝不改动显示文本。** 黑格尔保留 1816 年的拼写
（``Seyn``、``daß``、``Verhältniß``、``Proceß``、``Princip``），今天的读者
敲 ``Sein``、``dass``、``Verhältnis``。不做归一就什么都搜不到；做了归一而
忘了保留原文，显示出来的就会是被现代化过的黑格尔，那才是真正的错误。

两类偏差：

* :data:`REGELN` —— **有规律**的：``ey→ei``、``ß→ss``、``th→t``、``c→k/z``。
  它们对没见过的词一样成立。
* :data:`VARIANTEN` —— **无规律**的：``nemlich``/``nämlich``、``itzt``/``jetzt``。
  没有哪条字符规则能把它们连起来，只能列表。

所有规则都是**词内**的（lookbehind / lookahead 都不越过词边界），因此可以
先分词、再逐词归一 —— 这样归一后的词仍能一一对应回原文的字符区间，
高亮不会错位。这一点是本模块与 ``ortho.js`` 的唯一实现差异，而且是刻意的。
"""

from __future__ import annotations

import re
from typing import Iterable, Sequence

__all__ = [
    "REGELN",
    "VARIANTEN",
    "normalize",
    "normalize_token",
    "variants",
    "all_variants",
    "tokenize",
    "tokenize_normalized",
]


# --------------------------------------------------------------------------
# 规则表
# --------------------------------------------------------------------------

#: 有规律的替换。顺序有意义：``ni(?:ß|ss)`` 必须排在 ``ß→ss`` 前面，
#: 否则 ``Verhältniß`` 变成 ``verhältniss``，而 ``Verhältnis`` 变成
#: ``verhältnis`` —— 两者再也合不到一起。
REGELN: Sequence[tuple[str, str]] = (
    # ``ni(ß|ss)`` → ``nis``：Verhältniß / Verhältnis / verhältnüß
    (r"ni(?:ß|ss)(?![a-zäöü])", "nis"),
    # ``c`` 在清辅音前读 z（Centrum、Cirkel），否则读 k（Cultur、Princip、
    # Prädicat）。不能跟在 s / c 后面，否则 ``sch``、``ck``、``acc-`` 会被打散。
    (r"(?<![sc])c(?=[aou])", "k"),
    (r"(?<![sc])c(?=[ei])", "z"),
    (r"ey", "ei"),
    (r"ay", "ai"),
    (r"ß", "ss"),
    (r"th(?=[aeiouäöü])", "t"),
    (r"ct", "kt"),
    (r"ph", "f"),
    (r"iren\b", "ieren"),
)

#: 无规律的异体。第一个成员是「现代形」，其余是黑格尔时代的写法。
#: 每行后面的数字是该历史形式在全部十六卷中的实测页数 —— 删掉任何一行前
#: 请先看看它值多少页。
VARIANTEN: Sequence[tuple[str, ...]] = (
    ("jetzt", "itzt", "izt", "jezt"),        # itzt 339, izt 21, jezt 9
    ("nämlich", "nemlich", "nehmlich"),      # nemlich 772
    ("gibt", "giebt"),                       # giebt 86
    ("andere", "andre"),                     # andre 554
    ("unsere", "unsre"),                     # unsre 29
    ("ungeachtet", "ohngeachtet"),           # ohngeachtet 3
    ("sowohl", "sowol"),
)

#: 这些异体必须锚在词首。只做子串匹配的话 ``itzt`` 会命中 ``besitzt``、
#: ``andre`` 会命中 ``wandre``。但也不能全都锚死 —— 否则 ``gibt`` 能找到
#: ``ergibt``，``giebt`` 却找不到 ``ergiebt``，同一个问题会因写法不同而
#: 差出上百页。
_PREFIX_ANCHORED = frozenset({"itzt", "izt", "jezt", "andre", "unsre"})


def _compile(rules: Iterable[tuple[str, str]], flags: int = 0) -> list[tuple[re.Pattern[str], str]]:
    return [(re.compile(pattern, flags), repl) for pattern, repl in rules]


_COMPILED = _compile(REGELN)


def normalize(text: str) -> str:
    """对任意字符串应用全部规则（**保持原大小写**）。

    这是 ``ortho.js`` 中同名函数的直接对应物。它保留大小写，因此适合
    做「词形对照」；做检索键时要用 :func:`normalize_token`。
    """
    result = text
    for pattern, repl in _COMPILED:
        result = pattern.sub(repl, result)
    return result


def normalize_token(token: str) -> str:
    """把一个词变成**检索键**：先转小写，再套用全部规则。

    顺序很要紧。数字版原站是 ``key(form) = normalize(form.toLowerCase())``：
    先小写再归一。规则表里的 ``c→k/z``、``th→t``、``ph→f`` 都是小写字母
    的规则 —— 若先归一，词首的大写 ``C``（``Cultur``）就永远等不上
    小写规则，与现代拼写 ``Kultur`` 也就对不上了。

    与 :func:`normalize` 的另一处区别：本函数假定输入已经是一个词（不含
    标点与空白）。由于所有规则都只越过词内边界，结果与整串归一后按词
    切分的结果一致，但词长可能变化（``ß``→``ss`` 加一个字符）。
    """
    result = token.lower()
    for pattern, repl in _COMPILED:
        result = pattern.sub(repl, result)
    return result


#: 异体表：归一后的词 → 整组异体。
_VARIANT_TABLE: dict[str, tuple[str, ...]] = {}
for _group in VARIANTEN:
    for _word in _group:
        _VARIANT_TABLE[normalize(_word.lower())] = _group


def variants(word: str) -> list[str]:
    """与 ``word`` 属于同一异体组的其余写法；没有则返回空表。

    查表用的是归一后的形式，所以 ``Nemlich``、``nemlich``、``nämlich``
    命中同一组。
    """
    key = normalize((word or "").lower())
    group = _VARIANT_TABLE.get(key)
    if not group:
        return []
    normalized = normalize(word.lower())
    return [v for v in group if normalize(v.lower()) != normalized]


def all_variants(words: Iterable[str]) -> list[str]:
    """一批词的全部异体，去重。"""
    out: list[str] = []
    for word in words:
        for variant in variants(word):
            if variant not in out:
                out.append(variant)
    return out


def variant_pattern(
    words: Iterable[str], flags: int = re.IGNORECASE
) -> re.Pattern[str] | None:
    """覆盖全部异体的正则；没有异体时返回 ``None``。

    需要锚在词首的异体加 ``\\b``，其余不锚 —— 见 :data:`_PREFIX_ANCHORED`。
    """
    alle = all_variants(words)
    if not alle:
        return None
    parts = []
    for variant in alle:
        escaped = re.escape(variant)
        parts.append((r"\b" if variant in _PREFIX_ANCHORED else "") + escaped)
    return re.compile("(?:" + "|".join(parts) + ")", flags)


# --------------------------------------------------------------------------
# 分词
# --------------------------------------------------------------------------

#: 词 = 字母或数字的极大连续段。与 FTS5 的 ``unicode61`` 分词器保持一致，
#: 这样「我们分出的词」和「FTS5 索引里的词」是同一个东西。
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


def tokenize(text: str) -> list[tuple[str, int, int]]:
    """把文本切成 ``(词, 起点, 终点)``。

    起点/终点是**原文**的字符偏移，可直接用来高亮。
    """
    return [(m.group(0), m.start(), m.end()) for m in _TOKEN_RE.finditer(text)]


def tokenize_normalized(text: str) -> list[tuple[str, int, int]]:
    """同 :func:`tokenize`，但词已归一。

    返回的三元组是 ``(归一后的词, 原文起点, 原文终点)``。
    """
    return [(normalize_token(word), start, end) for word, start, end in tokenize(text)]
