/**
 * 界面图标。
 *
 * 线条风格统一：1.1px 描边、圆角连接、16px 网格。
 */

/**
 * 侧栏开关的图标。
 *
 * 只有一个形状 —— 方框里侧栏所在的那一侧画上阴影，表示「这一侧」。
 * 侧栏收起时**不换图标**：展开与否由按钮的高亮状态（颜色）区分，
 * 图标跟着变会让按钮在两种状态之间跳来跳去，反而不好认。
 */
export function PanelIcon({ side }: { side: "left" | "right" }) {
  const panelWidth = 5;
  const panelX = side === "left" ? 1.5 : 13.5 - panelWidth;

  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.1"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <rect x="1.5" y="2.5" width="13" height="11" rx="1.5" />
      <rect
        x={panelX}
        y="3.2"
        width={panelWidth}
        height="9.6"
        rx="0.6"
        fill="currentColor"
        fillOpacity="0.75"
        stroke="none"
      />
    </svg>
  );
}

/** 放大镜 —— 检索按钮。点开才变成输入框。 */
export function SearchIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.3"
      strokeLinecap="round"
      aria-hidden="true"
      focusable="false"
    >
      <circle cx="7" cy="7" r="4.6" />
      <path d="M10.6 10.6 L14 14" />
    </svg>
  );
}

/** 关闭 —— 排版面板用。 */
export function CloseIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.3"
      strokeLinecap="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M4 4 L12 12 M12 4 L4 12" />
    </svg>
  );
}
