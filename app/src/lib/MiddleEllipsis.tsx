/**
 * 省略号。
 *
 * CSS 的 `text-overflow: ellipsis` 只能截**尾部** —— 但读者最想看到的信息
 * 往往在两头，所以这里自己算：量出可用宽度，二分出能保留多少。
 *
 * 三种截法：
 *
 * - **中间省略**（默认）—— 头尾各留一半。适合不分层的长串。
 * - **尾部省略**（`mode="tail"`）—— 保住开头。适合标题：卷号 „GW 12“ 比
 *   末尾的年份更要紧。
 * - **按层级省略**（`separator=" › "`）—— 章节路径用这个。
 *
 *   章节路径是 `卷名 › 章 › 节 › 小节`，第一段是又长又没信息量的卷名，
 *   最后一段才是「我正在读哪一节」。按字符截断会把路径拦腰砍断，断口
 *   落在 „›“ 旁边，读起来是断的。所以先按层级砍：丢掉靠前的层级，
 *   保住最后几段；实在放不下才截最后一段的尾巴（开头是编号和主词，比
 *   结尾要紧）。
 *
 * ## 怎么量宽度
 *
 * 把候选文字临时塞进那个盒子，用 `Range.getBoundingClientRect()` 量它的
 * 宽度，量完还原。
 *
 * 早先的版本是在旁边放一个不可见的探针元素来量。那样有两个毛病：
 * 探针里的文字也在 DOM 里，**选中底栏复制会复制两遍**；而且隐藏元素
 * 仍占一份文本。Range 的办法不留任何多余节点。
 *
 * 临时改 `textContent` 不会闪烁 —— 测量与还原发生在同一次同步任务里，
 * 浏览器还没来得及绘制。
 */

import { useEffect, useRef, useState } from "react";

interface Props {
  text: string;
  className?: string;
  /** 无内容时显示的占位 */
  placeholder?: string;
  /** 截法：中间（默认）还是尾部 */
  mode?: "middle" | "tail";
  /**
   * 分层分隔符。给了就按层级截断：先砍掉靠前的层级，保住最后几段。
   */
  separator?: string;
  /** 悬停时显示的完整文字 */
  title?: string;
}

export function MiddleEllipsis({
  text,
  className,
  placeholder = "…",
  mode = "middle",
  separator,
  title,
}: Props) {
  const boxRef = useRef<HTMLSpanElement>(null);
  const [shown, setShown] = useState(text);

  useEffect(() => {
    const box = boxRef.current;
    if (!box) return;
    const el = box;

    /** 候选文字的宽度（像素） */
    function widthOf(content: string): number {
      const original = el.textContent;
      el.textContent = content;
      const range = document.createRange();
      range.selectNodeContents(el);
      const width = range.getBoundingClientRect().width;
      el.textContent = original;
      return width;
    }

    /** 头部保留 n 个字，后面加省略号 */
    function headTruncated(source: string, available: number): string {
      const chars = Array.from(source);
      let low = 0;
      let high = chars.length;
      let best = 0;
      while (low <= high) {
        const mid = (low + high) >> 1;
        if (widthOf(chars.slice(0, mid).join("") + "…") <= available) {
          best = mid;
          low = mid + 1;
        } else {
          high = mid - 1;
        }
      }
      return best > 0 ? chars.slice(0, best).join("") + "…" : "…";
    }

    function fit() {
      const available = el.clientWidth;
      if (!available) return;

      /** 装得下吗 */
      function fits(content: string): boolean {
        return widthOf(content) <= available;
      }

      // 放得下就全放
      if (fits(text)) {
        setShown(text);
        return;
      }

      // 按层级截断：保住最后几段，一段一段地往前丢
      if (separator) {
        const parts = text.split(separator);
        for (let keep = parts.length - 1; keep >= 1; keep--) {
          const candidate = `…${separator}${parts.slice(-keep).join(separator)}`;
          if (fits(candidate)) {
            setShown(candidate);
            return;
          }
        }
        // 连最后一段都放不下 —— 截它的尾巴（开头是编号和主词）
        setShown(headTruncated(parts[parts.length - 1], available));
        return;
      }

      // 尾部省略
      if (mode === "tail") {
        setShown(headTruncated(text, available));
        return;
      }

      // 中间省略：头尾各留一半
      const chars = Array.from(text);
      let low = 0;
      let high = chars.length;
      let best = 0;

      while (low <= high) {
        const mid = (low + high) >> 1;
        const head = chars.slice(0, mid).join("");
        const tail = chars.slice(chars.length - mid).join("");
        if (fits(mid === 0 ? "…" : `${head}…${tail}`)) {
          best = mid;
          low = mid + 1;
        } else {
          high = mid - 1;
        }
      }

      if (best <= 0) {
        setShown("…");
      } else {
        const head = chars.slice(0, best).join("");
        const tail = chars.slice(chars.length - best).join("");
        setShown(`${head}…${tail}`);
      }
    }

    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(el);
    return () => observer.disconnect();
  }, [text, mode, separator]);

  return (
    <span className={`middle-ellipsis${className ? " " + className : ""}`}>
      <span ref={boxRef} className="middle-ellipsis-box" title={title ?? text}>
        {shown || placeholder}
      </span>
    </span>
  );
}
