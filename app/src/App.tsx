import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  api,
  type Annotation,
  type Footnote,
  type PageInfo,
  type SearchHit,
  type Section,
  type Unit,
  type Work,
} from "./lib/api";
import { MiddleEllipsis } from "./lib/MiddleEllipsis";
import { CloseIcon, PanelIcon, SearchIcon } from "./lib/icons";
import { applySettings, DEFAULT_SETTINGS, normalize, type ReaderSettings } from "./lib/settings";

/** 版本的中文名 —— 下拉框里按这个分组。 */
const EDITION_LABELS: Record<string, string> = {
  hegel: "黑格尔 · Werke",
  fichte: "费希特 · Werke",
  schelling: "谢林 · Werke",
};
import { Toc } from "./reader/Toc";
import { TypographyPanel } from "./reader/TypographyPanel";
import { UnitView } from "./reader/UnitView";
import { SearchPanel } from "./search/SearchPanel";
import { AnnotationPanel } from "./annotations/AnnotationPanel";
import { GlossaryPanel } from "./annotations/GlossaryPanel";

type Layout = "reading" | "print";
type Panel = "none" | "notes" | "annotations" | "glossary";

const PAGE_JUMP_HINT = "GW 页码";

export default function App() {
  const [works, setWorks] = useState<Work[]>([]);
  const [workId, setWorkId] = useState<string>("gw-12");
  const [sections, setSections] = useState<Section[]>([]);
  const [pages, setPages] = useState<PageInfo[]>([]);
  const [pageIndex, setPageIndex] = useState(0);
  const [units, setUnits] = useState<Unit[]>([]);
  const [footnotes, setFootnotes] = useState<Footnote[]>([]);
  const [annotations, setAnnotations] = useState<Annotation[]>([]);
  const [layout, setLayout] = useState<Layout>("reading");
  const [panel, setPanel] = useState<Panel>("none");
  const [jumpValue, setJumpValue] = useState("");
  const [status, setStatus] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  // 检索范围：只搜当前卷，还是十六卷一起搜
  const [searchScope, setSearchScope] = useState<"volume" | "all">("all");
  // 检索框默认收着，只留一个放大镜 —— 顶栏因此能排成一行
  const [searchExpanded, setSearchExpanded] = useState(false);
  const [searchHits, setSearchHits] = useState<SearchHit[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedFootnote, setSelectedFootnote] = useState<string | null>(null);
  // 跨卷跳转：命中在别的卷时，先切卷，等那一页的单元加载完再滚过去
  const [pendingJump, setPendingJump] = useState<{ unitId: number; pdfPage: number } | null>(null);

  // 侧栏：宽度可拖，开关在底栏
  const [leftWidth, setLeftWidth] = useState(264);
  const [rightWidth, setRightWidth] = useState(330);
  const [leftOpen, setLeftOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(true);
  // 阅读偏好
  const [settings, setSettings] = useState<ReaderSettings>(DEFAULT_SETTINGS);
  const [typoOpen, setTypoOpen] = useState(false);
  // 工具条放不下时，次要按钮折进「更多」菜单
  const toolbarRef = useRef<HTMLElement>(null);
  const [compact, setCompact] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const dragRef = useRef<{ side: "left" | "right"; startX: number; startWidth: number } | null>(
    null,
  );

  // 读入上次的阅读偏好
  useEffect(() => {
    let alive = true;
    api
      .getSettings()
      .then((raw) => {
        if (!alive) return;
        const next = normalize(raw);
        setSettings(next);
        applySettings(next);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  // 改偏好：立刻生效，并写回工作区库
  const updateSettings = useCallback((next: ReaderSettings) => {
    setSettings(next);
    applySettings(next);
    const pairs: [string, string][] = [
      ["theme", next.theme],
      ["font", next.font],
      ["scale", String(next.scale)],
      ["measure", String(next.measure)],
      ["leading", String(next.leading)],
    ];
    for (const [key, value] of pairs) {
      api.setSetting(key, value).catch(() => {});
    }
  }, []);

  // 拖动分隔条改侧栏宽度
  useEffect(() => {
    function onMove(event: MouseEvent) {
      const drag = dragRef.current;
      if (!drag) return;
      const delta = event.clientX - drag.startX;
      if (drag.side === "left") {
        setLeftWidth(Math.min(Math.max(drag.startWidth + delta, 200), 560));
      } else {
        setRightWidth(Math.min(Math.max(drag.startWidth - delta, 260), 720));
      }
    }
    function onUp() {
      dragRef.current = null;
      document.body.classList.remove("is-dragging");
    }
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  function startDrag(side: "left" | "right", event: React.MouseEvent) {
    event.preventDefault();
    dragRef.current = {
      side,
      startX: event.clientX,
      startWidth: side === "left" ? leftWidth : rightWidth,
    };
    document.body.classList.add("is-dragging");
  }

  const immersive = !leftOpen && !rightOpen;

  // 工具条放不下就把次要按钮折进「更多」菜单。
  // 测量前先关掉换行 —— 否则内容会折行，scrollWidth 永远等于 clientWidth。
  useEffect(() => {
    const el = toolbarRef.current;
    if (!el) return;
    const measure = () => {
      const overflows = el.scrollWidth > el.clientWidth + 1;
      setCompact(overflows);
      if (!overflows) setMoreOpen(false);
    };
    const previousWrap = el.style.flexWrap;
    el.style.flexWrap = "nowrap";
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => {
      observer.disconnect();
      el.style.flexWrap = previousWrap;
    };
  }, [works.length, layout, panel, immersive, typoOpen]);

  const toggleImmersive = useCallback(() => {
    const next = !immersive;
    setLeftOpen(!next);
    setRightOpen(!next);
  }, [immersive]);

  const bodyRef = useRef<HTMLDivElement>(null);
  const searchTimer = useRef<number | undefined>(undefined);

  // ── 载入卷 ────────────────────────────────────────────────────────
  useEffect(() => {
    api.listWorks().then((list) => {
      setWorks(list);
      if (list.length && !list.some((w) => w.id === workId)) {
        setWorkId(list[0].id);
      }
    });
  }, [workId]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const [sectionList, pageList, noteList] = await Promise.all([
        api.getSections(workId),
        api.listPages(workId),
        api.getFootnotes(workId),
      ]);
      if (cancelled) return;
      setSections(sectionList);
      setPages(pageList);
      setFootnotes(noteList);

      // 回到上次读到的位置
      const saved = await api.getProgress(workId);
      if (cancelled) return;
      const target =
        saved?.pdfPage != null
          ? pageList.findIndex((p) => p.pdfPage === saved.pdfPage)
          : -1;
      setPageIndex(target >= 0 ? target : 0);
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [workId]);

  useEffect(() => {
    api.listAnnotations(workId).then(setAnnotations).catch(() => setAnnotations([]));
  }, [workId]);

  // ── 载入当前页 ────────────────────────────────────────────────────
  const currentPage = pages[pageIndex];

  useEffect(() => {
    if (!currentPage) {
      setUnits([]);
      return;
    }
    api.getPageUnits(workId, currentPage.pdfPage).then(setUnits).catch(() => setUnits([]));
  }, [workId, currentPage?.pdfPage]);

  // 待跳转的命中：等它所在页的单元加载完，再滚过去
  useEffect(() => {
    if (!pendingJump) return;
    const target = document.getElementById(`unit-${pendingJump.unitId}`);
    if (!target) return;
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    setPendingJump(null);
  }, [pendingJump, units]);

  // 记住读到哪儿
  useEffect(() => {
    if (!currentPage || units.length === 0) return;
    const first = units[0];
    api.setProgress(workId, first.id, first.bookPage, currentPage.pdfPage).catch(() => {});
  }, [workId, currentPage?.pdfPage, units.length]);

  // ── 翻页 ──────────────────────────────────────────────────────────
  const goToIndex = useCallback(
    (index: number) => {
      if (index < 0 || index >= pages.length) return;
      setPageIndex(index);
      setSelectedFootnote(null);
      bodyRef.current?.scrollTo({ top: 0 });
    },
    [pages.length],
  );

  const goToBookPage = useCallback(
    (bookPage: string) => {
      const index = pages.findIndex((p) => p.bookPage === bookPage);
      if (index >= 0) goToIndex(index);
      else setStatus(`这一卷里没有第 ${bookPage} 页`);
    },
    [pages, goToIndex],
  );

  const goToUnit = useCallback(
    (unitId: number) => {
      const unit = units.find((u) => u.id === unitId);
      if (unit) {
        document
          .getElementById(`unit-${unitId}`)
          ?.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    },
    [units],
  );

  // 快捷键
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const typing =
        target &&
        (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable);

      // Esc 一定要管用：即使焦点在输入框里（检索框就是），也要能把面板关掉。
      if (event.key === "Escape") {
        setSearchOpen(false);
        (document.activeElement as HTMLElement | null)?.blur();
        return;
      }
      if (typing) return;

      if (event.key === "/" && !typing) {
        event.preventDefault();
        setSearchOpen(true);
        setSearchExpanded(true);
        return;
      }

      if (event.key === "ArrowRight" || event.key === "PageDown") {
        goToIndex(pageIndex + 1);
      } else if (event.key === "ArrowLeft" || event.key === "PageUp") {
        goToIndex(pageIndex - 1);
      } else if (event.key === "p") {
        setLayout((l) => (l === "reading" ? "print" : "reading"));
      } else if (event.key === "f") {
        toggleImmersive();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pageIndex, goToIndex, toggleImmersive]);

  // ── 检索 ──────────────────────────────────────────────────────────
  const runSearch = useCallback(
    (query: string, scope?: "volume" | "all") => {
      const useScope = scope ?? searchScope;
      setSearchQuery(query);
      // 检索面板随输入打开（以前是输入框获得焦点时打开的，
      // 现在输入框要靠图标展开，这一步挪到这儿）
      setSearchOpen(true);
      if (!query.trim()) {
        setSearchHits([]);
        return;
      }
      window.clearTimeout(searchTimer.current);
      searchTimer.current = window.setTimeout(() => {
        api
          .search(query, useScope === "all" ? null : workId, 80)
          .then(setSearchHits)
          .catch(() => setSearchHits([]));
      }, 180);
    },
    [workId, searchScope],
  );

  const annotationUnitIds = useMemo(
    () => new Set(annotations.map((a) => a.unitId)),
    [annotations],
  );

  // ── 复制规范引用 ──────────────────────────────────────────────────
  const [copied, setCopied] = useState<string | null>(null);

  const copyCitation = useCallback(async (unit: Unit) => {
    try {
      const citation = await api.citation(unit.id);
      await navigator.clipboard.writeText(citation);
      setCopied(citation);
      window.setTimeout(() => setCopied(null), 2200);
    } catch {
      setStatus("复制失败");
    }
  }, []);

  const work = works.find((w) => w.id === workId);

  // 卷目按作者分组 —— 四十多卷平铺在下拉框里没法找
  const workGroups = useMemo(() => {
    const order: string[] = [];
    const groups = new Map<string, { edition: string; label: string; works: Work[] }>();
    for (const w of works) {
      if (!groups.has(w.edition)) {
        const label = EDITION_LABELS[w.edition] ?? w.edition;
        groups.set(w.edition, { edition: w.edition, label, works: [] });
        order.push(w.edition);
      }
      groups.get(w.edition)!.works.push(w);
    }
    return order.map((key) => groups.get(key)!);
  }, [works]);

  // 底栏的书目信息：当前页属于哪个章节、首行的 GW 行号
  const currentSection = useMemo(() => {
    const sectionId = units[0]?.sectionId;
    if (sectionId == null) return null;
    return sections.find((s) => s.id === sectionId) ?? null;
  }, [units, sections]);

  // 当前页属于哪个章节：取这一页上单元最多的那个。
  //
  // 一页可能跨章节边界（比如上一节的尾巴 + 下一节的开头），
  // 拿「单元最多的那个」最接近人的直觉 —— 人在这一页读的大半是哪一节，
  // 目录就高亮哪一节。
  const currentSectionId = useMemo(() => {
    const counts = new Map<number, number>();
    for (const unit of units) {
      if (unit.sectionId == null) continue;
      counts.set(unit.sectionId, (counts.get(unit.sectionId) ?? 0) + 1);
    }
    let best: number | null = null;
    let bestCount = 0;
    for (const [id, count] of counts) {
      if (count > bestCount) {
        best = id;
        bestCount = count;
      }
    }
    return best;
  }, [units]);

  const currentCitationLine = useMemo(() => {
    const first = units[0];
    const line = first?.lines?.[0]?.n;
    return typeof line === "number" ? line : null;
  }, [units]);
  const footnoteById = useMemo(() => {
    const map = new Map<string, Footnote>();
    for (const note of footnotes) map.set(note.id, note);
    return map;
  }, [footnotes]);

  if (works.length === 0) {
    return (
      <div className="boot">
        <p>正在打开语料库……</p>
      </div>
    );
  }

  return (
    <div className="app">
      <header className="toolbar" ref={toolbarRef}>
        <div className="toolbar-group">
          <select
            className="work-select"
            value={workId}
            onChange={(e) => setWorkId(e.target.value)}
            aria-label="选择卷"
          >
            {workGroups.map((group) => (
              <optgroup key={group.edition} label={group.label}>
                {group.works.map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.siglum} · {w.title}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </div>

        <div className="toolbar-group">
          <span className="page-indicator">
            {currentPage?.bookPage != null ? `GW ${currentPage.bookPage}` : currentPage?.pageKind ?? ""}
            <span className="page-of"> / {pages.length} 页</span>
          </span>
        </div>

        <div className="toolbar-group">
          <input
            type="text"
            className="jump-input"
            placeholder={PAGE_JUMP_HINT}
            value={jumpValue}
            onChange={(e) => setJumpValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key !== "Enter") return;
              // 页码可能是阿拉伯数字（"241"）也可能是罗马数字（"V"）——
              // 费希特与谢林的卷首页就是罗马数字。
              const value = jumpValue.trim();
              if (value) goToBookPage(value);
              setJumpValue("");
            }}
            aria-label={PAGE_JUMP_HINT}
          />
        </div>

        <div className="toolbar-group">
          {searchExpanded ? (
            <>
              <input
                type="search"
                className="search-input"
                placeholder="检索（/ 聚焦）"
                value={searchQuery}
                autoFocus
                onChange={(e) => runSearch(e.target.value)}
                onBlur={() => {
                  // 框里没字就收起来
                  if (!searchQuery.trim()) setSearchExpanded(false);
                }}
                aria-label="检索"
              />
              <button
                type="button"
                className="icon-button"
                onClick={() => {
                  setSearchExpanded(false);
                  setSearchOpen(false);
                }}
                title="收起检索框"
                aria-label="收起检索框"
              >
                <CloseIcon />
              </button>
            </>
          ) : (
            <button
              type="button"
              className="icon-button"
              onClick={() => setSearchExpanded(true)}
              title="检索（/ 聚焦）"
              aria-label="检索"
            >
              <SearchIcon />
            </button>
          )}
          <button
            type="button"
            className={searchScope === "all" ? "active" : ""}
            onClick={() => {
              const next = searchScope === "all" ? "volume" : "all";
              setSearchScope(next);
              if (searchQuery.trim()) runSearch(searchQuery, next);
            }}
            title={searchScope === "all" ? "当前：全部十六卷" : "当前：仅当前卷"}
          >
            {searchScope === "all" ? "全部卷" : "本卷"}
          </button>
        </div>

        <div className={`toolbar-group toolbar-secondary${compact ? " hidden" : ""}`}>
          <button
            type="button"
            className={layout === "print" ? "active" : ""}
            onClick={() => setLayout(layout === "print" ? "reading" : "print")}
            title="切换印刷版式（快捷键 p）"
          >
            印刷版式
          </button>
          <button
            type="button"
            className={panel === "notes" ? "active" : ""}
            onClick={() => setPanel(panel === "notes" ? "none" : "notes")}
          >
            脚注
          </button>
          <button
            type="button"
            className={panel === "annotations" ? "active" : ""}
            onClick={() => setPanel(panel === "annotations" ? "none" : "annotations")}
          >
            批注
          </button>
          <button
            type="button"
            className={panel === "glossary" ? "active" : ""}
            onClick={() => setPanel(panel === "glossary" ? "none" : "glossary")}
          >
            词表
          </button>
          <button
            type="button"
            className={typoOpen ? "active" : ""}
            onClick={() => setTypoOpen(!typoOpen)}
            title="排版：字号、版心宽度、行距、主题"
          >
            排版
          </button>
          <button
            type="button"
            className={immersive ? "active" : ""}
            onClick={toggleImmersive}
            title="沉浸阅读：收起两侧栏（快捷键 f）"
          >
            沉浸
          </button>
        </div>

        {compact && (
          <div className="toolbar-more">
            <button
              type="button"
              className={moreOpen ? "active" : ""}
              onClick={() => setMoreOpen(!moreOpen)}
              title="更多视图选项"
              aria-label="更多视图选项"
            >
              ⋯
            </button>
            {moreOpen && (
              <div className="more-menu" role="menu">
                <button
                  type="button"
                  role="menuitem"
                  className={layout === "print" ? "active" : ""}
                  onClick={() => {
                    setLayout(layout === "print" ? "reading" : "print");
                    setMoreOpen(false);
                  }}
                >
                  印刷版式
                </button>
                <button
                  type="button"
                  role="menuitem"
                  className={panel === "notes" ? "active" : ""}
                  onClick={() => {
                    setPanel(panel === "notes" ? "none" : "notes");
                    setMoreOpen(false);
                  }}
                >
                  脚注
                </button>
                <button
                  type="button"
                  role="menuitem"
                  className={panel === "annotations" ? "active" : ""}
                  onClick={() => {
                    setPanel(panel === "annotations" ? "none" : "annotations");
                    setMoreOpen(false);
                  }}
                >
                  批注
                </button>
                <button
                  type="button"
                  role="menuitem"
                  className={panel === "glossary" ? "active" : ""}
                  onClick={() => {
                    setPanel(panel === "glossary" ? "none" : "glossary");
                    setMoreOpen(false);
                  }}
                >
                  词表
                </button>
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setTypoOpen(true);
                    setMoreOpen(false);
                  }}
                >
                  排版…
                </button>
                <button
                  type="button"
                  role="menuitem"
                  className={immersive ? "active" : ""}
                  onClick={() => {
                    toggleImmersive();
                    setMoreOpen(false);
                  }}
                >
                  沉浸阅读
                </button>
              </div>
            )}
          </div>
        )}
      </header>

      {status && (
        <div className="status-bar" onClick={() => setStatus("")}>
          {status}
        </div>
      )}

      <div
        className="layout"
        style={{
          // 分隔条的宽度走 CSS 变量 —— 粗细是设计的一部分，别在��里写死
          gridTemplateColumns: `${leftOpen ? leftWidth : 0}px ${
            leftOpen ? "var(--w-splitter)" : "0px"
          } 1fr ${rightOpen ? "var(--w-splitter)" : "0px"} ${rightOpen ? rightWidth : 0}px`,
        }}
      >
        <aside className={`sidebar${leftOpen ? "" : " collapsed"}`}>
          <div className="sidebar-label">目录</div>
          <Toc
            sections={sections}
            currentSectionId={currentSectionId}
            onSelect={(section) => {
              if (section.pdfPage != null) {
                const index = pages.findIndex((p) => p.pdfPage === section.pdfPage);
                if (index >= 0) goToIndex(index);
              }
            }}
          />
        </aside>

        <div
          className={`splitter${leftOpen ? "" : " splitter-hidden"}`}
          role="separator"
          aria-orientation="vertical"
          aria-hidden={!leftOpen}
          onMouseDown={(e) => startDrag("left", e)}
          title="拖动调整目录栏宽度"
        />

        <div className="reader-wrap">
          <button
            type="button"
            className="page-nav page-nav-prev"
            onClick={() => goToIndex(pageIndex - 1)}
            disabled={pageIndex <= 0}
            title="前一页（←）"
            aria-label="前一页"
          >
            ‹
          </button>
          <button
            type="button"
            className="page-nav page-nav-next"
            onClick={() => goToIndex(pageIndex + 1)}
            disabled={pageIndex >= pages.length - 1}
            title="后一页（→）"
            aria-label="后一页"
          >
            ›
          </button>

        <main className="reader" ref={bodyRef}>
          <div className="page-head">
            {currentPage?.runningHeader && (
              <span className="running-head">{currentPage.runningHeader}</span>
            )}
            {currentPage?.signature && (
              <span className="signature">{currentPage.signature}</span>
            )}
            {currentPage?.hasApparatus && (
              <span className="apparatus-mark" title="此页有编者校勘说明">
                校勘
              </span>
            )}
          </div>

          {units.length === 0 && (
            <p className="empty">这一页没有正文。</p>
          )}

          {units.map((unit) => (
            <UnitView
              key={unit.id}
              unit={unit}
              layout={layout}
              annotationUnitIds={annotationUnitIds}
              onCopyCitation={copyCitation}
              onFootnoteClick={(target) => {
                setSelectedFootnote(target);
                setPanel("notes");
              }}
            />
          ))}

          {copied && <div className="toast">已复制：{copied}</div>}

          {selectedFootnote && footnoteById.get(selectedFootnote) && (
            <div className="inline-footnote">
              <strong>{footnoteById.get(selectedFootnote)!.marker ?? ""}</strong>{" "}
              {footnoteById.get(selectedFootnote)!.text}
            </div>
          )}
        </main>
        </div>

        <div
          className={`splitter${rightOpen ? "" : " splitter-hidden"}`}
          role="separator"
          aria-orientation="vertical"
          aria-hidden={!rightOpen}
          onMouseDown={(e) => startDrag("right", e)}
          title="拖动调整面板栏宽度"
        />

        <aside className={`sidepanel${rightOpen ? "" : " collapsed"}`}>
          {panel === "notes" && (
            <div className="panel">
              <div className="panel-label">脚注（{footnotes.length}）</div>
              <ul className="footnote-list">
                {footnotes.map((note) => (
                  <li
                    key={note.id}
                    className={`footnote${selectedFootnote === note.id ? " current" : ""}`}
                    onClick={() => setSelectedFootnote(note.id)}
                  >
                    <span className="footnote-marker">{note.marker ?? note.id}</span>
                    <span className="footnote-text">{note.text}</span>
                    <span className="footnote-loc">
                      GW {note.bookPage}
                      {note.gwLine != null ? `.${note.gwLine}` : ""}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {panel === "annotations" && (
            <AnnotationPanel
              workId={workId}
              annotations={annotations}
              onChanged={() => api.listAnnotations(workId).then(setAnnotations)}
              onJump={(unitId) => goToUnit(unitId)}
            />
          )}
          {panel === "glossary" && <GlossaryPanel />}
          {panel === "none" && (
            <div className="panel panel-empty">
              <p>右侧面板：脚注、批注、词表。</p>
              <p className="hint">快捷键：/ 检索 · p 切换版式 · ← → 翻页</p>
            </div>
          )}
        </aside>
      </div>

      {typoOpen && (
        <TypographyPanel
          settings={settings}
          onChange={updateSettings}
          onClose={() => setTypoOpen(false)}
          onReset={() => updateSettings(DEFAULT_SETTINGS)}
        />
      )}

      {searchOpen && (
        <SearchPanel
          query={searchQuery}
          hits={searchHits}
          onQueryChange={runSearch}
          onClose={() => setSearchOpen(false)}
          onJump={(hit) => {
            setSearchOpen(false);
            if (hit.workId !== workId) {
              // 命中在别的卷：切卷，等新卷的页加载完再定位
              setPendingJump({ unitId: hit.unitId, pdfPage: hit.pdfPage });
              setWorkId(hit.workId);
              return;
            }
            const index = pages.findIndex((p) => p.pdfPage === hit.pdfPage);
            if (index >= 0) goToIndex(index);
            window.setTimeout(() => goToUnit(hit.unitId), 60);
          }}
        />
      )}

      <footer className="statusline">
        <button
          type="button"
          className={`status-toggle${leftOpen ? " active" : ""}`}
          onClick={() => setLeftOpen(!leftOpen)}
          title={leftOpen ? "收起目录栏" : "展开目录栏"}
          aria-label={leftOpen ? "收起目录栏" : "展开目录栏"}
          aria-pressed={leftOpen}
        >
          <PanelIcon side="left" />
        </button>

        <div className="status-info">
          <span className="status-author">
            {EDITION_LABELS[work?.edition ?? "hegel"]?.split(" · ")[0] ?? "黑格尔"}
          </span>
          {work && (
            <MiddleEllipsis
              className="status-work"
              text={`${work.siglum} · ${work.title}`}
              mode="tail"
            />
          )}
          {currentPage?.bookPage != null && (
            <span className="status-page">
              第 {currentPage.bookPage} 页
              {currentCitationLine != null && ` · 第 ${currentCitationLine} 行`}
            </span>
          )}
          {currentSection && (
            <MiddleEllipsis
              className="status-section"
              text={currentSection.path}
              separator=" › "
            />
          )}
        </div>

        <button
          type="button"
          className={`status-toggle${rightOpen ? " active" : ""}`}
          onClick={() => setRightOpen(!rightOpen)}
          title={rightOpen ? "收起面板栏" : "展开面板栏"}
          aria-label={rightOpen ? "收起面板栏" : "展开面板栏"}
          aria-pressed={rightOpen}
        >
          <PanelIcon side="right" />
        </button>
      </footer>
    </div>
  );
}
