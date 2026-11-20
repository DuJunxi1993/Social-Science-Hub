/** 检索面板：命中列表 + 原文片段。 */

import { useEffect, useRef } from "react";

import type { SearchHit } from "../lib/api";

interface Props {
  query: string;
  hits: SearchHit[];
  onQueryChange: (query: string) => void;
  onClose: () => void;
  onJump: (hit: SearchHit) => void;
}

/** 片段里命中词的位置（后端给的区间），据此高亮。 */
function Highlighted({ text, ranges }: { text: string; ranges: [number, number][] }) {
  if (!ranges.length) return <>{text}</>;
  const parts: React.ReactNode[] = [];
  let cursor = 0;
  ranges.forEach(([start, end], i) => {
    if (start > cursor) parts.push(text.slice(cursor, start));
    parts.push(
      <mark key={i} className="hit">
        {text.slice(start, end)}
      </mark>,
    );
    cursor = end;
  });
  if (cursor < text.length) parts.push(text.slice(cursor));
  return <>{parts}</>;
}

export function SearchPanel({ query, hits, onQueryChange, onClose, onJump }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  // 跨卷检索时，命中来自好几卷 —— 同一卷的连续命中归成一段，
  // 免得十六卷的条目把上下文冲掉。
  const groups = hits.reduce<{ siglum: string; hits: SearchHit[] }[]>((acc, hit) => {
    const last = acc[acc.length - 1];
    if (last && last.siglum === hit.siglum) last.hits.push(hit);
    else acc.push({ siglum: hit.siglum, hits: [hit] });
    return acc;
  }, []);

  return (
    <div className="search-overlay" onClick={onClose}>
      <div className="search-panel" onClick={(e) => e.stopPropagation()}>
        <div className="search-head">
          <input
            ref={inputRef}
            type="search"
            className="search-panel-input"
            value={query}
            placeholder='检索语法：a b · "短语" · a OR b · a NOT b · 前缀* · NEAR'
            onChange={(e) => onQueryChange(e.target.value)}
          />
          <span className="search-count">{hits.length} 处</span>
          <button type="button" onClick={onClose}>
            关闭
          </button>
        </div>

        <ul className="search-results">
          {groups.map((group, index) => (
            <li key={`${group.siglum}-${index}`} className="search-group">
              <div className="search-group-head">{group.siglum}</div>
              {group.hits.map((hit) => (
                <button
                  key={hit.unitId}
                  type="button"
                  className="search-hit"
                  onClick={() => onJump(hit)}
                >
                  <span className="hit-loc">
                    GW {hit.bookPage}
                    {hit.gwLine != null ? `.${hit.gwLine}` : ""}
                  </span>
                  <span className="hit-section">{hit.section}</span>
                  <span className="hit-snippet">
                    <Highlighted text={hit.snippet} ranges={hit.matches} />
                  </span>
                </button>
              ))}
            </li>
          ))}
          {query.trim() && hits.length === 0 && (
            <li className="search-empty">没有命中。</li>
          )}
        </ul>
      </div>
    </div>
  );
}
