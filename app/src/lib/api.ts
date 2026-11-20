/**
 * 与 Rust 后端的接口。
 *
 * 所有数据都从本地 SQLite 来，没有一个网络请求 —— 应用是离线的。
 */

import { invoke } from "@tauri-apps/api/core";
import type { RawSettings } from "./settings";

/** 语料里的一段标记区间。 */
export interface Mark {
  s: number;
  e: number;
  k: string;
  target?: string;
  label?: string;
}

export interface Work {
  id: string;
  /** 版本：hegel / fichte / schelling */
  edition: string;
  /** 作者（德文姓名） */
  author: string | null;
  siglum: string;
  title: string;
  shortTitle: string | null;
  sourceTitle: string | null;
  series: string | null;
  volumeNumber: string | null;
  licenseAttribution: string | null;
  licenseDatabase: string | null;
  licenseUrl: string | null;
  sourceUrl: string | null;
}

export interface Section {
  id: number;
  ord: number;
  level: number;
  title: string;
  path: string;
  bookPage: string | null;
  pdfPage: number | null;
  unitId: number | null;
}

export interface Unit {
  id: number;
  ord: number;
  pdfPage: number;
  bookPage: string | null;
  sectionId: number | null;
  kind: "heading" | "subheading" | "paragraph" | "quote" | "footnote";
  text: string;
  spans: Mark[];
  refs: Mark[];
  lines: { n: number; t: string; s: Mark[] }[];
  lineMap: [number, number, number][];
  meta: Record<string, unknown>;
}

export interface PageInfo {
  pdfPage: number;
  bookPage: string | null;
  pageKind: string;
  hasApparatus: boolean;
  runningHeader: string;
  signature: string;
}

export interface Footnote {
  id: string;
  unitId: number | null;
  part: number | null;
  marker: string | null;
  anchorGwLine: number | null;
  bookPage: string | null;
  gwLine: number | null;
  text: string;
  spans: Mark[];
}

export interface SearchHit {
  unitId: number;
  /** 命中所在的卷 —— 跨卷检索时要告诉用户是哪一卷 */
  workId: string;
  siglum: string;
  bookPage: string | null;
  gwLine: number | null;
  /** 命中所在的 PDF 页 —— 跨卷跳转时用来定位 */
  pdfPage: number;
  section: string;
  snippet: string;
  /** 命中词在 `snippet` 中的区间 —— 前端据此高亮，不要在文本里塞标记 */
  matches: [number, number][];
  score: number;
  kind: string;
}

export interface Annotation {
  id: number;
  workId: string;
  unitId: number;
  bookPage: string | null;
  gwLine: number | null;
  quote: string;
  note: string;
  tags: string[];
  createdAt: string;
  updatedAt: string;
}

export interface Bookmark {
  id: number;
  workId: string;
  unitId: number;
  label: string;
  createdAt: string;
}

export interface GlossaryEntry {
  id: number;
  termDe: string;
  termZh: string;
  note: string;
  createdAt: string;
  updatedAt: string;
}

export interface Progress {
  workId: string;
  unitId: number | null;
  bookPage: string | null;
  pdfPage: number | null;
}

export const api = {
  listWorks: () => invoke<Work[]>("list_works"),
  getSections: (workId: string) => invoke<Section[]>("get_sections", { workId }),
  getPageUnits: (workId: string, pdfPage: number) =>
    invoke<Unit[]>("get_page_units", { workId, pdfPage }),
  getUnits: (workId: string, fromOrd: number, count: number) =>
    invoke<Unit[]>("get_units", { workId, fromOrd, count }),
  getUnit: (unitId: number) => invoke<Unit>("get_unit", { unitId }),
  findByBookPage: (workId: string, bookPage: string) =>
    invoke<Unit | null>("find_by_book_page", { workId, bookPage }),
  listPages: (workId: string) => invoke<PageInfo[]>("list_pages", { workId }),
  getFootnotes: (workId: string) => invoke<Footnote[]>("get_footnotes", { workId }),
  search: (query: string, workId: string | null, limit = 50) =>
    invoke<SearchHit[]>("search_corpus", { query, workId, limit }),
  citation: (unitId: number) => invoke<string>("citation", { unitId }),

  listAnnotations: (workId: string | null) =>
    invoke<Annotation[]>("list_annotations", { workId }),
  saveAnnotation: (input: {
    id?: number;
    workId: string;
    unitId: number;
    bookPage?: string | null;
    gwLine?: number | null;
    quote?: string;
    note?: string;
    tags?: string[];
  }) => invoke<number>("save_annotation", { input }),
  deleteAnnotation: (id: number) => invoke<void>("delete_annotation", { id }),

  listBookmarks: () => invoke<Bookmark[]>("list_bookmarks"),
  addBookmark: (workId: string, unitId: number, label: string) =>
    invoke<void>("add_bookmark", { workId, unitId, label }),
  removeBookmark: (unitId: number) => invoke<void>("remove_bookmark", { unitId }),

  listGlossary: () => invoke<GlossaryEntry[]>("list_glossary"),
  saveGlossary: (input: {
    id?: number;
    termDe: string;
    termZh?: string;
    note?: string;
  }) => invoke<number>("save_glossary", { input }),
  deleteGlossary: (id: number) => invoke<void>("delete_glossary", { id }),

  getProgress: (workId: string) => invoke<Progress | null>("get_progress", { workId }),
  setProgress: (
    workId: string,
    unitId: number | null,
    bookPage: string | null,
    pdfPage: number | null,
  ) => invoke<void>("set_progress", { workId, unitId, bookPage, pdfPage }),

  corpusLocation: () => invoke<string>("corpus_location"),
  getSettings: () => invoke<RawSettings>("get_settings"),
  setSetting: (key: string, value: string) => invoke<void>("set_setting", { key, value }),
};

