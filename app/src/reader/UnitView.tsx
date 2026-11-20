/**
 * 一个内容单元的两种呈现。
 *
 * * **阅读层** —— 连排正文。疏排（强调）加字距，脚注号做成可点的上标。
 * * **印刷层** —— 复刻原书：逐行、行号在左边、断行照旧。
 *
 * 同一份语料，两种视图随时切换 —— 核对引文时用印刷层更靠谱，因为
 * 引用是「GW 12, 241.36」这样的「页.行」，行号必须对得上。
 */

import type { Mark, Unit } from "../lib/api";
import { lineSegments, segmentize } from "../lib/text";

interface Props {
  unit: Unit;
  layout: "reading" | "print";
  onFootnoteClick?: (target: string) => void;
  onUnitClick?: (unit: Unit) => void;
  onCopyCitation?: (unit: Unit) => void;
  annotationUnitIds?: Set<number>;
}

function Emph({ emph, children }: { emph: boolean; children: React.ReactNode }) {
  return emph ? <span className="sperrsatz">{children}</span> : <>{children}</>;
}

export function UnitView({
  unit,
  layout,
  onFootnoteClick,
  onUnitClick,
  onCopyCitation,
  annotationUnitIds,
}: Props) {
  const annotated = annotationUnitIds?.has(unit.id) ?? false;

  if (unit.kind === "heading" || unit.kind === "subheading") {
    const segments = segmentize(unit.text, unit.spans, unit.refs);
    const Tag = unit.kind === "heading" ? "h2" : "h3";
    return (
      <Tag className={`unit unit-heading level-${unit.kind === "heading" ? 1 : 2}`} id={`unit-${unit.id}`}>
        {segments.map((seg, i) => (
          <Emph key={i} emph={seg.emph}>
            {seg.text}
          </Emph>
        ))}
      </Tag>
    );
  }

  if (unit.kind === "quote") {
    return (
      <blockquote className="unit unit-quote" id={`unit-${unit.id}`}>
        {segmentize(unit.text, unit.spans, unit.refs).map((seg, i) => (
          <Emph key={i} emph={seg.emph}>
            {seg.text}
          </Emph>
        ))}
      </blockquote>
    );
  }

  if (layout === "print") {
    return (
      <div className="unit unit-print" id={`unit-${unit.id}`}>
        {unit.lines.map((line, i) => (
          <div key={i} className="dipl-line">
            <span className="dipl-nr">{line.n}</span>
            <span className="dipl-text">
              {lineSegments(line.t, line.s).map((seg, j) => (
                <Emph key={j} emph={seg.emph}>
                  {seg.text}
                </Emph>
              ))}
            </span>
          </div>
        ))}
      </div>
    );
  }

  const segments = segmentize(unit.text, unit.spans, unit.refs);
  return (
    <div className="unit-wrap">
      <p
        className={`unit unit-paragraph${annotated ? " has-annotation" : ""}`}
        id={`unit-${unit.id}`}
        onClick={() => onUnitClick?.(unit)}
      >
        {segments.map((seg, i) =>
          seg.ref ? (
            <RefMark
              key={i}
              mark={seg.ref}
              onFootnoteClick={onFootnoteClick}
            >
              {seg.text}
            </RefMark>
          ) : (
            <Emph key={i} emph={seg.emph}>
              {seg.text}
            </Emph>
          ),
        )}
      </p>
      {onCopyCitation && (
        <button
          type="button"
          className="copy-citation"
          title="复制规范引用（GW 卷, 页.行）"
          onClick={() => onCopyCitation(unit)}
        >
          引用
        </button>
      )}
    </div>
  );
}

function RefMark({
  mark,
  onFootnoteClick,
  children,
}: {
  mark: Mark;
  onFootnoteClick?: (target: string) => void;
  children: React.ReactNode;
}) {
  const isFootnote = mark.k === "fnref";
  return (
    <a
      className={`ref-mark ${isFootnote ? "ref-footnote" : "ref-xref"}`}
      href="#"
      title={isFootnote ? "脚注" : "互引"}
      onClick={(event) => {
        event.preventDefault();
        event.stopPropagation();
        if (mark.target) onFootnoteClick?.(mark.target);
      }}
    >
      {children}
    </a>
  );
}
