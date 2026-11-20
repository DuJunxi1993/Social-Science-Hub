/** 术语表：德文 → 中文。本地保存，不随语料升级而丢失。 */

import { useEffect, useState } from "react";

import { api, type GlossaryEntry } from "../lib/api";

export function GlossaryPanel() {
  const [entries, setEntries] = useState<GlossaryEntry[]>([]);
  const [draft, setDraft] = useState({ termDe: "", termZh: "", note: "" });
  const [editingId, setEditingId] = useState<number | null>(null);
  const [filter, setFilter] = useState("");

  function reload() {
    api.listGlossary().then(setEntries).catch(() => setEntries([]));
  }

  useEffect(reload, []);

  const visible = entries.filter((entry) => {
    if (!filter.trim()) return true;
    const needle = filter.toLowerCase();
    return (
      entry.termDe.toLowerCase().includes(needle) ||
      entry.termZh.toLowerCase().includes(needle)
    );
  });

  async function save() {
    if (!draft.termDe.trim()) return;
    await api.saveGlossary({
      id: editingId ?? undefined,
      termDe: draft.termDe.trim(),
      termZh: draft.termZh,
      note: draft.note,
    });
    setDraft({ termDe: "", termZh: "", note: "" });
    setEditingId(null);
    reload();
  }

  return (
    <div className="panel">
      <div className="panel-label">术语表（{entries.length}）</div>

      <div className="annotation-form">
        <input
          type="text"
          placeholder="德文原词"
          value={draft.termDe}
          onChange={(e) => setDraft({ ...draft, termDe: e.target.value })}
        />
        <input
          type="text"
          placeholder="中文对应"
          value={draft.termZh}
          onChange={(e) => setDraft({ ...draft, termZh: e.target.value })}
        />
        <input
          type="text"
          placeholder="说明"
          value={draft.note}
          onChange={(e) => setDraft({ ...draft, note: e.target.value })}
        />
        <button type="button" onClick={save}>
          {editingId ? "更新" : "保存"}
        </button>
      </div>

      <input
        type="search"
        className="glossary-filter"
        placeholder="过滤"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
      />

      <ul className="glossary-list">
        {visible.map((entry) => (
          <li key={entry.id} className="glossary-entry">
            <div className="glossary-term">
              <span className="de">{entry.termDe}</span>
              {entry.termZh && <span className="zh">{entry.termZh}</span>}
            </div>
            {entry.note && <p className="glossary-note">{entry.note}</p>}
            <div className="glossary-actions">
              <button
                type="button"
                onClick={() => {
                  setEditingId(entry.id);
                  setDraft({
                    termDe: entry.termDe,
                    termZh: entry.termZh,
                    note: entry.note,
                  });
                }}
              >
                改
              </button>
              <button
                type="button"
                onClick={async () => {
                  await api.deleteGlossary(entry.id);
                  reload();
                }}
              >
                删
              </button>
            </div>
          </li>
        ))}
        {visible.length === 0 && <li className="panel-empty">还没有词条。</li>}
      </ul>
    </div>
  );
}
