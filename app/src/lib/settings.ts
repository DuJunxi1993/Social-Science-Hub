/**
 * 阅读偏好。
 *
 * 五个维度：主题、字体、字号、版心宽度、行距。
 *
 * 这些值最终都落成 CSS 自定义属性（挂在 `<html>` 上），所以「改设置」和
 * 「重排版」是同一件事 —— 没有第二套渲染路径。
 */

export interface ReaderSettings {
  /** 主题：纸色 / 纯白 / 米黄 / 夜间 */
  theme: "paper" | "white" | "sepia" | "night";
  /** 正文字体：衬线 / 无衬线 */
  font: "serif" | "sans";
  /** 字号倍率 */
  scale: number;
  /** 版心宽度（rem） */
  measure: number;
  /** 行距 */
  leading: number;
}

export const DEFAULT_SETTINGS: ReaderSettings = {
  theme: "paper",
  font: "serif",
  scale: 1,
  measure: 34,
  leading: 1.72,
};

export const THEME_LABELS: Record<ReaderSettings["theme"], string> = {
  paper: "纸色",
  white: "纯白",
  sepia: "米黄",
  night: "夜间",
};

export const FONT_LABELS: Record<ReaderSettings["font"], string> = {
  serif: "衬线",
  sans: "无衬线",
};

/** 各项的取值范围 —— 面板上的滑块与校验都从这里取 */
export const RANGES = {
  scale: { min: 0.8, max: 1.5, step: 0.05 },
  measure: { min: 26, max: 56, step: 1 },
  leading: { min: 1.4, max: 2.1, step: 0.02 },
} as const;

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

/** 后端存回来的形状：字段可能缺失，主题/字体是字符串 */
export interface RawSettings {
  theme?: string;
  font?: string;
  scale?: number;
  measure?: number;
  leading?: number;
}

/** 把后端存下来的（可能缺失、可能越界的）值收拾成一份合法的设置 */
export function normalize(raw: RawSettings | null | undefined): ReaderSettings {
  const merged = { ...DEFAULT_SETTINGS, ...(raw ?? {}) } as {
    theme: string;
    font: string;
    scale: number;
    measure: number;
    leading: number;
  };
  return {
    theme:
      merged.theme === "white" || merged.theme === "sepia" || merged.theme === "night"
        ? merged.theme
        : "paper",
    font: merged.font === "sans" ? "sans" : "serif",
    scale: clamp(Number(merged.scale) || DEFAULT_SETTINGS.scale, RANGES.scale.min, RANGES.scale.max),
    measure: clamp(
      Number(merged.measure) || DEFAULT_SETTINGS.measure,
      RANGES.measure.min,
      RANGES.measure.max,
    ),
    leading: clamp(
      Number(merged.leading) || DEFAULT_SETTINGS.leading,
      RANGES.leading.min,
      RANGES.leading.max,
    ),
  };
}

/**
 * 把设置写到 CSS 变量上。
 *
 * 主题走 `data-theme` 属性（CSS 里按属性覆写一整套颜色），其余直接改变量。
 */
export function applySettings(settings: ReaderSettings): void {
  const root = document.documentElement;
  root.dataset.theme = settings.theme;
  root.dataset.readerFont = settings.font;
  root.style.setProperty("--reader-scale", String(settings.scale));
  root.style.setProperty("--reader-measure", `${settings.measure}rem`);
  root.style.setProperty("--reader-leading", String(settings.leading));
}
