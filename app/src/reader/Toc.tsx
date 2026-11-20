/**
 * 左侧目录：按层级缩进的章节树。
 *
 * 高亮跟的是**当前页所在���章节** —— 不管是翻页过去的、点目录过去的，
 * 还是从检索结果跳过去的，目录都跟着走到那一节，并把那一项滚到可见处。
 */

import { useEffect, useRef } from "react";
import type { Section } from "../lib/api";

interface Props {
  sections: Section[];
  /** 当前页所属的章节 id */
  currentSectionId: number | null;
  onSelect: (section: Section) => void;
}

export function Toc({ sections, currentSectionId, onSelect }: Props) {
  const activeRef = useRef<HTMLLIElement>(null);

  // 目录按 ord 顺序排，level 决定缩进。
  const activeIndex = sections.findIndex((s) => s.id === currentSectionId);

  // 高亮项变了就把它滚进视野 —— 检索跳到远处时尤其需要，
  // 否则目录停在一千页开外，用户根本不知道自己跳到了哪儿。
  useEffect(() => {
    if (activeIndex < 0) return;
    activeRef.current?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  return (
    <nav className="toc" aria-label="目录">
      <ol className="toc-list">
        {sections.map((section, index) => {
          const isActive = index === activeIndex;
          return (
            <li
              key={section.id}
              ref={isActive ? activeRef : undefined}
              className={`toc-item level-${section.level}${isActive ? " current" : ""}`}
            >
              <button
                type="button"
                className={`toc-link${isActive ? " current" : ""}`}
                onClick={() => onSelect(section)}
                title={section.path}
                aria-current={isActive ? "true" : undefined}
              >
                <span className="toc-title">{section.title}</span>
                {section.bookPage != null && (
                  <span className="toc-page">{section.bookPage}</span>
                )}
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
