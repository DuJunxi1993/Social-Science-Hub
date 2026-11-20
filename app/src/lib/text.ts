/**
 * 把单元的文本切成带标记的片段。
 *
 * 语料里「疏排」（强调）与「引用」（脚注号、互引）是两套独立的区间，
 * 它们可能落在同一段文字上。所以这里先收集所有边界点，把文本切成
 * 不重叠的小段，每段带上自己的属性 —— 前端就不必处理区间重叠。
 *
 * **偏移的单位**：ETL 用 Python 的字符下标（一个码位一个数）。这里
 * ``String.slice`` 按 UTF-16 码元计数 —— 两者只在**星平面**字符
 * （U+10000 以上）上才会分家。GW 12 全卷没有星平面字符（已实测），
 * 所以目前两边一致；将来引入别的卷时，若出现星平面字符，ETL 那边
 * 要改成按 UTF-16 计数。
 */

import type { Mark } from "./api";

export interface Segment {
  text: string;
  /** 原文是否疏排（强调） */
  emph: boolean;
  /** 落在这一段里的引用（如果有） */
  ref?: Mark;
}

export function segmentize(text: string, spans: Mark[], refs: Mark[]): Segment[] {
  if (!text) return [];
  if (!spans.length && !refs.length) return [{ text, emph: false }];

  const points = new Set<number>([0, text.length]);
  for (const mark of [...spans, ...refs]) {
    if (mark.s >= 0 && mark.e <= text.length && mark.e > mark.s) {
      points.add(mark.s);
      points.add(mark.e);
    }
  }
  const sorted = [...points].sort((a, b) => a - b);

  const segments: Segment[] = [];
  for (let i = 0; i < sorted.length - 1; i += 1) {
    const start = sorted[i];
    const end = sorted[i + 1];
    if (start === end) continue;
    const emph = spans.some((m) => m.s <= start && end <= m.e);
    const ref = refs.find((m) => m.s <= start && end <= m.e);
    segments.push({ text: text.slice(start, end), emph, ref });
  }
  return segments;
}

/** 印刷层的行同样要切分（每行自带疏排区间）。 */
export function lineSegments(
  text: string,
  spans: Mark[],
): Segment[] {
  return segmentize(text, spans, []);
}

/** 规范引用串：`GW 12, 241.36`。 */
export function formatCitation(siglum: string, bookPage: number | null, gwLine: number | null): string {
  if (bookPage == null) return siglum;
  if (gwLine == null) return `${siglum}, ${bookPage}`;
  return `${siglum}, ${bookPage}.${gwLine}`;
}
