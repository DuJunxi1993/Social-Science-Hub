/** 批注面板：本地笔记。 */

import { useState } from "react";

import { api, type Annotation } from "../lib/api";

interface Props {
  workId: string;
  annotations: Annotation[];
  onChanged: () => void;
  onJump: (unitId: number) => void;
}

export function AnnotationPanel({ workId, annotations, onChanged, onJump }: Props) {
  const [draft, setDraft] = useState({ quote: "", note: "", bookPage: "" });
  const [editingId, setEditingId] = useState<number | null>(null);

  async function save() {
    if (!draft.note.trim() && !draft.quote.trim()) return;
    await api.saveAnnotation({
      id: editingId ?? undefined,
      workId,
      unitId: 0,
      bookPage: draft.bookPage || null,
      gwLine: null,
      quote: draft.quote,
      note: draft.note,
      tags: [],
    });
    setDraft({ quote: "", note: "", bookPage: "" });
    setEditingId(null);
    onChanged();
  }

  return (
    <div className="panel">
      <div className="panel-label">批注（{annotations.length}）</div>

      <div className="annotation-form">
        <textarea
          placeholder="引文（可选）"
          value={draft.quote}
          onChange={(e) => setDraft({ ...draft, quote: e.target.value })}
          rows={2}
        />
        <textarea
          placeholder="笔记"
          value={draft.note}
          onChange={(e) => setDraft({ ...draft, note: e.target.value })}
          rows={3}
        />
        <input
          type="text"
          placeholder="GW 页码"
          value={draft.bookPage}
          onChange={(e) => setDraft({ ...draft, bookPage: e.target.value })}
        />
        <button type="button" onClick={save}>
          {editingId ? "更新" : "保存"}
        </button>
      </div>

      <ul className="annotation-list">
        {annotations.map((item) => (
          <li key={item.id} className="annotation">
            <div className="annotation-head">
              {item.bookPage != null && (
                <button
                  type="button"
                  className="annotation-loc"
                  onClick={() => onJump(item.unitId)}
                >
                  GW {item.bookPage}
                  {item.gwLine != null ? `.${item.gwLine}` : ""}
                </button>
              )}
              <button
                type="button"
                className="annotation-edit"
                onClick={() => {
                  setEditingId(item.id);
                  setDraft({
                    quote: item.quote,
                    note: item.note,
                    bookPage: item.bookPage?.toString() ?? "",
                  });
                }}
              >
                改
              </button>
              <button
                type="button"
                className="annotation-delete"
                onClick={async () => {
                  await api.deleteAnnotation(item.id);
                  onChanged();
                }}
              >
                删
              </button>
            </div>
            {item.quote && <blockquote className="annotation-quote">{item.quote}</blockquote>}
            {item.note && <p className="annotation-note">{item.note}</p>}
          </li>
        ))}
        {annotations.length === 0 && <li className="panel-empty">还没有批注。</li>}
      </ul>
    </div>
  );
}
