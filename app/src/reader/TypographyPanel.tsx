/**
 * 「排版」面板 —— 阅读偏好。
 *
 * 五个维度：主题、正文字体、字号、版心宽度、行距。
 * 每改一下立刻生效（改的是 CSS 变量），并写回工作区库，下次打开还在。
 */

import { useEffect, useRef } from "react";
import {
  FONT_LABELS,
  RANGES,
  THEME_LABELS,
  type ReaderSettings,
} from "../lib/settings";

interface Props {
  settings: ReaderSettings;
  onChange: (next: ReaderSettings) => void;
  onClose: () => void;
  onReset: () => void;
}

export function TypographyPanel({ settings, onChange, onClose, onReset }: Props) {
  const panelRef = useRef<HTMLDivElement>(null);

  // 点外面关掉
  useEffect(() => {
    function onPointerDown(event: MouseEvent) {
      if (!panelRef.current?.contains(event.target as Node)) onClose();
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [onClose]);

  const set = <K extends keyof ReaderSettings>(key: K, value: ReaderSettings[K]) =>
    onChange({ ...settings, [key]: value });

  return (
    <div className="typo-panel" ref={panelRef} role="dialog" aria-label="排版设置">
      <div className="typo-head">
        <span>排版</span>
        <button type="button" className="typo-reset" onClick={onReset}>
          恢复默认
        </button>
        <button type="button" onClick={onClose} aria-label="关闭">
          ×
        </button>
      </div>

      <div className="typo-section">
        <div className="typo-label">主题</div>
        <div className="typo-chips">
          {(Object.keys(THEME_LABELS) as ReaderSettings["theme"][]).map((theme) => (
            <button
              key={theme}
              type="button"
              className={`typo-chip theme-${theme}${settings.theme === theme ? " active" : ""}`}
              onClick={() => set("theme", theme)}
              title={THEME_LABELS[theme]}
            >
              {THEME_LABELS[theme]}
            </button>
          ))}
        </div>
      </div>

      <div className="typo-section">
        <div className="typo-label">正文字体</div>
        <div className="typo-chips">
          {(Object.keys(FONT_LABELS) as ReaderSettings["font"][]).map((font) => (
            <button
              key={font}
              type="button"
              className={`typo-chip${settings.font === font ? " active" : ""}`}
              onClick={() => set("font", font)}
            >
              {FONT_LABELS[font]}
            </button>
          ))}
        </div>
      </div>

      <Slider
        label="字号"
        value={settings.scale}
        min={RANGES.scale.min}
        max={RANGES.scale.max}
        step={RANGES.scale.step}
        format={(v) => `${Math.round(v * 100)}%`}
        onChange={(v) => set("scale", v)}
      />

      <Slider
        label="版心宽度"
        value={settings.measure}
        min={RANGES.measure.min}
        max={RANGES.measure.max}
        step={RANGES.measure.step}
        format={(v) => `${v} rem`}
        onChange={(v) => set("measure", v)}
      />

      <Slider
        label="行距"
        value={settings.leading}
        min={RANGES.leading.min}
        max={RANGES.leading.max}
        step={RANGES.leading.step}
        format={(v) => v.toFixed(2)}
        onChange={(v) => set("leading", v)}
      />

      <p className="typo-hint">
        设置自动保存，下次打开仍在。快捷键：<kbd>f</kbd> 沉浸阅读
      </p>
    </div>
  );
}

interface SliderProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  format: (value: number) => string;
  onChange: (value: number) => void;
}

function Slider({ label, value, min, max, step, format, onChange }: SliderProps) {
  return (
    <div className="typo-section">
      <div className="typo-label">
        <span>{label}</span>
        <span className="typo-value">{format(value)}</span>
      </div>
      <input
        type="range"
        className="typo-range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-label={label}
      />
    </div>
  );
}
