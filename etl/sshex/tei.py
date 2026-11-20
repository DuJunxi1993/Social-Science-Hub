"""TEI 解析：从黑格尔数字版的源 TEI 派生双层文本结构。

数据来源：``https://hegel.idealismedition.com/assets/tei/GWnn.xml``（16 卷）。
该 TEI 是这一版唯一的真源；阅读层与印刷层都由它派生，而不是各存一份。

**两层**

* **阅读层**（``text``）—— 连排的正文。行末连字符（``<pc>``）被还原成整词，
  印刷上的换行变成空格或段落。
* **印刷层**（``lines``）—— 复刻原书：每一行带 GW 行号，行内保留疏排标记。

同一份标记同时产出两层，这是原版 ``assets/en/tei-leser.js`` 的做法
（它是 Python 端 ``tei_quelle.py`` 的镜像），这里按同一套规则重写，
但输出结构更丰富：强调（疏排）以**字符区间**而不是 ``*`` 标记保存，
前端可以直接渲染，不必再解析一次。

标记速查（依据 GW12 的实际用法）：

===================== ==========================================================
``<pb>``              页界。``@n`` = GW 印刷页码，``@facs="#page=N"`` = PDF 页码
``<fw>``              书眉（页顶）。属于版面元数据，不是正文
``<milestone>``       帖码（``unit="vorlage"``）；谢林还用它标 Antiqua 排版区间
``<space>``           填空行（``ana="#j.leer-text"``）
``<head>``            标题；``type="sub"`` 为副标题
``<p>``               正文段落
``<note>``            脚注（``xml:id``、``n`` 标记、``prev``/``next`` 链）
``<lb>``              印刷行首。``@n`` = GW 行号，``break="no"`` = 非真实断行
``<hi rendition="#g">`` 疏排（强调）
``<seg rend="g-umgekehrt">`` 疏排中的反白部分（取消强调）
``<pc force="weak">`` 行末连字符
``<choice>``          原字/规范字；印刷层取 ``orig``，阅读层取 ``reg``
``<ref>`` / ``<ptr>`` 互引
===================== ==========================================================
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Iterator, Literal

__all__ = ["Volume", "Page", "Unit", "Span", "Line", "parse_tei"]

TEI_NS = "http://www.tei-c.org/ns/1.0"

UnitKind = Literal[
    "heading", "subheading", "paragraph", "quote", "footnote", "spacer"
]


# --------------------------------------------------------------------------
# 数据结构
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Span:
    """一段带标记的字符区间（相对所属单元的文本）。"""

    start: int
    end: int
    kind: str  # 'emph' | 'fnref' | 'xref'
    target: str | None = None   # fnref/xref 的目标 id
    label: str | None = None    # 引用的显示文本（如脚注号 "¹"）


@dataclass
class Line:
    """印刷层的一行。"""

    number: int          # GW 行号
    text: str
    spans: list[Span] = field(default_factory=list)


@dataclass
class Unit:
    """页面上的一个内容单元。"""

    kind: UnitKind
    text: str = ""
    spans: list[Span] = field(default_factory=list)
    refs: list[dict] = field(default_factory=list)
    lines: list[Line] = field(default_factory=list)
    #: 阅读层每个字符归属的印刷行：``(起点, 终点, GW 行号)``
    line_map: list[tuple[int, int, int]] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    @property
    def is_spacer(self) -> bool:
        return self.kind == "spacer"


@dataclass
class Page:
    """一个印刷页（PDF 页）。

    ``book_page`` 是书上的印刷页码。正文页是阿拉伯数字（„241“），卷首的
    页是罗马数字（„V“、„XXVII“）—— 引用 „SW I, V.3“ 指的就是卷首那一页，
    所以两种都得留着，不能一律当整数。
    """

    pdf_page: int
    book_page: str | None
    kind: str = "body"
    has_apparatus: bool = False
    running_header: str = ""
    signature: str = ""
    units: list[Unit] = field(default_factory=list)


@dataclass
class Volume:
    """一卷的完整结构。"""

    metadata: dict
    pages: list[Page] = field(default_factory=list)
    toc_printed: list[dict] = field(default_factory=list)
    toc_headings: list[dict] = field(default_factory=list)

    @property
    def units(self) -> Iterator[tuple[Page, Unit]]:
        for page in self.pages:
            for unit in page.units:
                yield page, unit


# --------------------------------------------------------------------------
# XML 辅助
# --------------------------------------------------------------------------


def _local(tag: str) -> str:
    return tag.rpartition("}")[2]


def _pdf_page_from_facs(facs: str) -> int:
    """从 ``<pb>`` 的 ``@facs`` 取扫描页码。

    三家版本的写法不一样：

    - 黑格尔 ``facs="#page=10"``
    - 费希特、谢林 ``facs="https://www.digitale-sammlungen.de/de/view/bsb…?page=5"``

    都是取 ``page=`` 后面的数字。
    """
    if "page=" not in facs:
        return 0
    tail = facs.rpartition("page=")[2]
    digits = ""
    for ch in tail:
        if ch.isdigit():
            digits += ch
        else:
            break
    return int(digits) if digits else 0


def _book_page(raw: str | None) -> str | None:
    """印刷页码，原样留着。

    正文页是阿拉伯数字，卷首的页是罗马数字 —— 都按字符串存。
    """
    if raw is None:
        return None
    raw = raw.strip()
    return raw or None


def _children(el: ET.Element) -> list[ET.Element]:
    return [c for c in el if isinstance(c.tag, str)]


def _first(el: ET.Element, name: str) -> ET.Element | None:
    for c in el:
        if isinstance(c.tag, str) and _local(c.tag) == name:
            return c
    return None


def _find(el: ET.Element, path: str) -> ET.Element | None:
    """``'teiHeader/fileDesc'`` 这样的简单路径；可选 ``[@attr="wert"]``。"""
    current: ET.Element | None = el
    for part in path.split("/"):
        match = re.fullmatch(r"([A-Za-z]+)(?:\[@([A-Za-z:]+)=\"([^\"]*)\"\])?", part)
        if not match:
            return None
        name, attr, value = match.group(1), match.group(2), match.group(3)
        found = None
        for c in current if current is not None else []:
            if isinstance(c.tag, str) and _local(c.tag) == name:
                if attr is None or c.get(attr) == value:
                    found = c
                    break
        current = found
        if current is None:
            return None
    return current


def _text_of(el: ET.Element | None) -> str:
    if el is None:
        return ""
    return "".join(el.itertext())


def _iter_content(el: ET.Element) -> Iterator[tuple[str, object]]:
    """按文档顺序产出 ``('text', 字符串)`` 与 ``('elem', 元素)``。"""
    if el.text:
        yield "text", el.text
    for child in el:
        if not isinstance(child.tag, str):
            continue
        yield "elem", child
        if child.tail:
            yield "text", child.tail


# --------------------------------------------------------------------------
# 事件流：把单元的标记转成有序事件
# --------------------------------------------------------------------------

# 事件三元组：
#   ('z', 文本, 疏排标志)   一段普通文字
#   ('lb', 行号, 标志, 是否首行)
#   ('lit', '**')           无法辨识的字
#   ('ref', 文本, 目标, 标志)  一个引用（脚注锚点或互引）
_EVENT_Z = "z"
_EVENT_LB = "lb"
_EVENT_LIT = "lit"
_EVENT_REF = "ref"


def _events(
    el: ET.Element,
    layer: Literal["z", "l"],
    emphasis: int,
    out: list,
    state: dict,
) -> None:
    """遍历一个单元，产出事件。

    ``layer='z'`` 为印刷层，``layer='l'`` 为阅读层。

    两层的差别集中在四处，都是印刷决定的：

    * ``<choice>``：印刷层取 ``orig``（原字），阅读层取 ``reg``（规范字）。
    * ``<pc>``：印刷层保留连字符，阅读层丢掉它（词要接起来）。
    * ``<seg>``：``type="marke"`` 之类的版面标记只在印刷层出现。
    * ``<lb>``：印刷层每个行首都换行；阅读层只有真正的断行才换行。
    """
    for kind, node in _iter_content(el):
        if kind == "text":
            if node:
                out.append((_EVENT_Z, node, emphasis))
            continue

        tag = _local(node.tag)

        if tag == "hi":
            # `<hi rendition="#g">Wort</hi>`：文字在 ``.text`` 里，没有子元素。
            # 只有**完全空**的 ``<hi>`` 才是「字迹不可辨」。
            if not (node.text or _children(node)):
                out.append((_EVENT_LIT, "**", emphasis))
            else:
                _events(node, layer, 1, out, state)

        elif tag == "choice":
            wanted = "orig" if layer == "z" else "reg"
            for branch in _children(node):
                if _local(branch.tag) == wanted:
                    _events(branch, layer, emphasis, out, state)

        elif tag == "milestone":
            # 谢林用它在段落里标出「Antiqua（罗马体）起止」——
            # 纯排版标记，没有文字，两层都不出现。
            # （原站的检索索引里它变成 ``[^aq+]`` / ``[^aq-]`` 标记；
            #  我们的阅读层不需要它。）
            continue

        elif tag == "lb":
            first_line = not state["lb_seen"]
            state["lb_seen"] = True
            line_number = int(node.get("n", "0"))
            if layer == "z":
                flag = emphasis ^ (1 if node.get("rend") == "g-umgekehrt" else 0)
                out.append((_EVENT_LB, line_number, 0 if first_line else flag, first_line))
            else:
                # 阅读层：行首事件仍然发出，好把正文里的每个字符归到它的
                # 印刷行上；换行本身变成一个分隔符。
                if not first_line and node.get("break") != "no":
                    kind_attr = node.get("type")
                    if kind_attr == "absatz":
                        sep = "\n\n"
                    elif kind_attr == "zeile":
                        sep = "\n"
                    else:
                        sep = " "
                    out.append((_EVENT_Z, sep, emphasis))
                out.append((_EVENT_LB, line_number, emphasis, first_line))

        elif tag == "pc":
            # 行末连字符：印刷上留着，阅读时接回整词。
            if layer == "z":
                _events(node, layer, emphasis, out, state)

        elif tag == "seg":
            if node.get("rend") == "g-umgekehrt":
                # 疏排中的反白：印刷层取消强调，阅读层保持。
                _events(node, layer, emphasis ^ 1 if layer == "z" else emphasis, out, state)
            elif layer == "z":
                _events(node, layer, emphasis, out, state)

        elif tag == "ref":
            if layer == "z":
                _events(node, layer, emphasis, out, state)
            else:
                # 阅读层不把脚注号当普通文字，而是标成可点击的引用区间。
                target = node.get("target")
                label = _text_of(node)
                if target and label:
                    out.append((_EVENT_REF, label, target.lstrip("#"), emphasis))
                elif label:
                    out.append((_EVENT_Z, label, emphasis))

        elif tag == "ptr":
            target = node.get("target")
            label = _text_of(node)
            if target:
                out.append((_EVENT_REF, label, target.lstrip("#"), emphasis))

        elif tag == "figure":
            out.append((_EVENT_Z, "⟨Zeichnung⟩", emphasis))

        elif tag in ("orig", "reg"):
            _events(node, layer, emphasis, out, state)

        else:
            raise ValueError(f"单元内出现未知的元素：<{tag}>")


def _pieces(el: ET.Element, layer: Literal["z", "l"]) -> list[tuple[int, str, int, str | None]]:
    """把单元展开成 ``(行序号, 文本, 疏排标志, 引用目标)`` 的流水。

    行序号为 -1 表示首个行首之前的内容 —— 阅读层照收，印刷层不计。

    疏排标志在行首处**延续**到下一行：行末的疏排词和下一行开头的疏排词
    是同一个区间，参考实现 (``tei-leser.js``) 也是这样处理的。
    """
    events: list = []
    _events(el, layer, 0, events, {"lb_seen": False})

    out: list[tuple[int, str, int, str | None]] = []
    line = -1
    previous = 0
    for event in events:
        if event[0] == _EVENT_LB:
            line += 1
            previous = event[2]
            continue
        if event[0] == _EVENT_LIT:
            out.append((line, "**", previous, None))
            continue
        if event[0] == _EVENT_REF:
            out.append((line, event[1], previous, event[2]))
            continue
        previous = event[2]
        out.append((line, event[1], previous, None))
    return out


def _reading_layer(
    el: ET.Element, open_ended: bool = False
) -> tuple[str, list[Span], list[dict], list[tuple[int, int, int]]]:
    """阅读层：连排正文 + 强调区间 + 引用 + 行区间表。

    行区间表是 ``(起点, 终点, GW 行号)``：把阅读层的每个字符归到它的
    印刷行上。有了它，检索命中 anywhere 都能报出「GW 第几页第几行」。
    """
    pieces = [(text, flag, ref, line) for line, text, flag, ref in _pieces(el, "l")]
    numbers = _line_numbers(el)
    return _assemble(pieces, open_ended, numbers)


def _print_layer(el: ET.Element, open_ended: bool = False) -> list[Line]:
    """印刷层：逐行，带 GW 行号与行内强调区间。"""
    pieces = _pieces(el, "z")

    buckets: dict[int, list[tuple[str, int, str | None, int]]] = {}
    order: list[int] = []
    for line, text, flag, ref in pieces:
        if line < 0:
            continue
        if line not in buckets:
            buckets[line] = []
            order.append(line)
        buckets[line].append((text, flag, ref, line))

    # 行号取自行首事件；_pieces 已经把行首编号丢掉了，这里从事件流补回。
    numbers = _line_numbers(el)

    result: list[Line] = []
    for line in order:
        text, spans, _, _ = _assemble(buckets[line], open_ended, numbers)
        result.append(Line(number=numbers.get(line, 0), text=text, spans=spans))
    return result


def _line_numbers(el: ET.Element) -> dict[int, int]:
    """行首序号 → GW 行号。"""
    events: list = []
    _events(el, "z", 0, events, {"lb_seen": False})
    numbers: dict[int, int] = {}
    index = -1
    for event in events:
        if event[0] == _EVENT_LB:
            index += 1
            numbers[index] = event[1]
    return numbers


def _assemble(
    pieces: list[tuple[str, int, str | None, int]],
    open_ended: bool,
    numbers: dict[int, int] | None = None,
) -> tuple[str, list[Span], list[dict], list[tuple[int, int, int]]]:
    """把 ``(文本, 疏排标志, 引用目标, 行序号)`` 片段拼成整段文本。

    产出：文本、强调区间、引用、行区间表。强调与引用分开存：两者可能落在
    同一段文字上（疏排词里嵌着脚注号），分开之后前端不必处理区间重叠。
    """
    parts: list[str] = []
    spans: list[Span] = []
    refs: list[dict] = []
    line_spans: list[tuple[int, int, int]] = []
    position = 0
    start = 0
    flag: int | None = None

    for text, emphasis, ref, line in pieces:
        if not text:
            continue
        if emphasis != flag:
            if flag:
                spans.append(Span(start, position, "emph"))
            flag = emphasis
            start = position
        piece_start = position
        parts.append(text)
        position += len(text)

        if numbers is not None:
            gw_line = numbers.get(line)
            if gw_line is not None:
                if line_spans and line_spans[-1][2] == gw_line and line_spans[-1][1] == piece_start:
                    line_spans[-1] = (line_spans[-1][0], position, gw_line)
                else:
                    line_spans.append((piece_start, position, gw_line))

        if ref:
            kind = "fnref" if ref.startswith("fn-") else "xref"
            refs.append(
                {
                    "s": piece_start,
                    "e": position,
                    "k": kind,
                    "target": ref,
                    "label": text,
                }
            )

    if flag:
        spans.append(Span(start, position, "emph"))

    joined = "".join(parts)
    if not open_ended:
        trimmed = joined.rstrip()
        if len(trimmed) != len(joined):
            # 末尾空白被去掉后，强调区间可能越界；收到文本长度之内。
            spans = [s for s in spans if s.start < len(trimmed)]
            spans = [Span(s.start, min(s.end, len(trimmed)), s.kind) for s in spans]
            refs = [r for r in refs if r["s"] < len(trimmed)]
            for ref in refs:
                ref["e"] = min(ref["e"], len(trimmed))
            line_spans = [(a, min(b, len(trimmed)), c) for a, b, c in line_spans if a < len(trimmed)]
        joined = trimmed
    return joined, spans, refs, line_spans


# --------------------------------------------------------------------------
# 主解析
# --------------------------------------------------------------------------

_UNIT_TAGS = {"head", "p", "quote", "note", "space"}


def parse_tei(source: str | bytes) -> Volume:
    """把 TEI 文档解析成 :class:`Volume`。"""
    if isinstance(source, str):
        source = source.encode("utf-8")
    root = ET.fromstring(source)

    metadata = _read_metadata(root)
    text_el = _find(root, "text")
    if text_el is None:
        raise ValueError("TEI 中没有 <text>")
    front = _find(text_el, "front")
    body = _find(text_el, "body")
    if body is None:
        raise ValueError("TEI 中没有 <body>")

    volume = Volume(
        metadata=metadata,
        toc_printed=_read_toc(front, "toc_printed"),
        toc_headings=_read_toc(front, "toc_headings"),
    )

    page: Page | None = None
    for element in _walk(body):
        tag = _local(element.tag)
        if tag == "pb":
            facs = element.get("facs") or ""
            pdf_page = _pdf_page_from_facs(facs)
            book_page = _book_page(element.get("n"))
            page = Page(
                pdf_page=pdf_page,
                book_page=book_page,
                kind=element.get("type") or "body",
                has_apparatus=element.get("subtype") == "apparat",
            )
            volume.pages.append(page)
            continue
        if page is None:
            continue
        if tag == "fw":
            page.running_header = _text_of(element)
            continue
        if tag == "milestone":
            page.signature = element.get("n") or ""
            continue
        if tag not in _UNIT_TAGS:
            continue
        if tag == "note" and element.get("type") == "erfassung":
            # 「录入说明」—— 关于这份数字版怎么做的注，不是书里的内容
            continue
        page.units.append(_read_unit(element, tag))

    return volume


def _walk(el: ET.Element) -> Iterator[ET.Element]:
    """按文档顺序遍历 ``<body>`` 下的内容单元。

    ``<div>`` 只是分组，递归进入；其余元素按顺序产出。
    """
    for child in _children(el):
        tag = _local(child.tag)
        if tag == "div":
            yield from _walk(child)
        else:
            yield child


def _read_metadata(root: ET.Element) -> dict:
    header = _find(root, "teiHeader/fileDesc")
    if header is None:
        return {}
    bibl = _find(header, "sourceDesc/bibl")
    pub = _find(header, "publicationStmt")
    licence = _find(pub, "availability/licence") if pub is not None else None
    scope = _find(bibl, "biblScope") if bibl is not None else None

    return {
        "work_id": _text_of(_find(pub, 'idno[@type="work_id"]') if pub is not None else None),
        "siglum": _text_of(_find(pub, 'idno[@type="siglum"]') if pub is not None else None),
        "series": _text_of(_find(bibl, 'title[@type="series"]') if bibl is not None else None),
        "volume_number": scope.get("n") if scope is not None else None,
        "author": _text_of(_find(header, "titleStmt/author/persName")),
        "title": _text_of(_find(header, 'titleStmt/title[@type="main"]')),
        "short_title": _text_of(_find(header, 'titleStmt/title[@type="short"]')),
        "source_title": _text_of(_find(bibl, 'title[@type="source"]') if bibl is not None else None),
        "publisher": _text_of(_find(bibl, "publisher") if bibl is not None else None),
        "license_text": _text_of(_find(licence, 'p[@n="text"]') if licence is not None else None),
        "license_database": _text_of(_find(licence, 'p[@n="database"]') if licence is not None else None),
        "license_url": licence.get("target") if licence is not None else None,
        "license_attribution": _text_of(
            _find(licence, 'p[@n="attribution"]') if licence is not None else None
        ),
        "license_excludes": _text_of(
            _find(licence, 'p[@n="excludes"]') if licence is not None else None
        ),
    }


def _read_toc(front: ET.Element | None, subtype: str) -> list[dict]:
    if front is None:
        return []
    div = _find(front, f'div[@subtype="{subtype}"]')
    if div is None:
        return []
    lst = _find(div, "list")
    if lst is None:
        return []
    entries: list[dict] = []
    for item in _children(lst):
        ref = _first(item, "ref")
        if ref is None:
            continue
        entry = {"title": _text_of(ref)}
        if ref.get("n"):
            entry["page"] = _book_page(ref.get("n"))
        if item.get("n"):
            entry["level"] = int(item.get("n"))
        entries.append(entry)
    return entries


def _read_unit(element: ET.Element, tag: str) -> Unit:
    ana = (element.get("ana") or "").split()
    meta: dict = {}

    if tag == "space":
        unit = Unit(kind="spacer", text="")
        if "#j.leer-zeilen" in ana:
            meta["empty_lines"] = True
        return unit

    kind: UnitKind = {
        "head": "subheading" if element.get("type") == "sub" else "heading",
        "p": "paragraph",
        "quote": "quote",
        "note": "footnote",
    }[tag]

    if tag == "note":
        # 脚注的 id 有两部分：``fn-233-1`` 是脚注本身，``fn-233-1.t2`` 是它的
        # 第二段（脚注太长，印在下一页）。``prev``/``next`` 把这些段串起来。
        #
        # **主键要用完整的 id** —— 早先只取 ``.t`` 前的部分，于是第二段
        # 把第一段顶掉了（``INSERT OR REPLACE``），一条长脚注只剩下最后一段。
        footnote_id = (element.get("{http://www.w3.org/XML/1998/namespace}id") or "")
        base = footnote_id.split(".t")[0]
        meta["footnote_id"] = footnote_id
        meta["footnote_base_id"] = base
        meta["footnote_part_id"] = footnote_id
        for link in ("prev", "next"):
            value = element.get(link)
            if value:
                meta[f"{link}_id"] = value.lstrip("#")
        if element.get("n"):
            meta["marker"] = element.get("n")
        elif "#j.marke-null" in ana:
            meta["marker"] = None
        if element.get("type"):
            meta["place_kind"] = element.get("type")
        if element.get("place"):
            meta["position"] = element.get("place")
        if element.get("target"):
            target = element.get("target")
            if "-z" in target:
                meta["anchor_gw_line"] = int(target.rpartition("-z")[2])
        for value in ana:
            if value.startswith("#j.teil-"):
                meta["part"] = int(value[len("#j.teil-"):])
            elif value.startswith("#j.fortgesetzt-"):
                meta["continued_from_page"] = int(value[len("#j.fortgesetzt-"):])

    rendition = (element.get("rendition") or "").split()
    if "#anmerkung" in rendition:
        meta["is_editorial_note"] = True
    for value in rendition:
        if value.startswith("#grad"):
            meta["grade"] = int(value[len("#grad"):])
        elif value.startswith("#halten-"):
            meta["halten"] = value[len("#halten-"):]

    open_reading = "#j.lesung-offen" in ana
    open_lines = "#j.zeilen-offen" in ana

    text, spans, refs, line_map = _reading_layer(element, open_reading)
    lines = _print_layer(element, open_lines)

    return Unit(
        kind=kind,
        text=text,
        spans=spans,
        refs=refs,
        lines=lines,
        line_map=line_map,
        meta=meta,
    )
