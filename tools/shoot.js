/**
 * 用 Playwright 验证前端。
 *
 * 前端在普通浏览器里跑不起来 —— `@tauri-apps/api` 的 invoke 要经 Tauri 的
 * IPC。这里把 IPC 换成一个从真语料库导出的假实现（tools/mock-data.json），
 * 于是 React 的渲染、检索面板、目录、版式切换、侧栏拖动都能在无头浏览器里验证。
 *
 * 用法：node tools/shoot.js [输出目录]
 */

const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const OUT = process.argv[2] || "/tmp/shots";
const DATA = JSON.parse(fs.readFileSync(path.join(__dirname, "mock-data.json"), "utf8"));

// 把 Tauri IPC 换成假实现
const MOCK = `
window.__TAURI_INTERNALS__ = {
  invoke: async (cmd, args) => {
    const D = window.__MOCK__;
    (window.__MOCK_CALLS__ = window.__MOCK_CALLS__ || []).push([cmd, args]);
    switch (cmd) {
      case "list_works": return D.list_works;
      case "get_sections": return (D.sections_by_work || {})[args.workId] || [];
      case "list_pages": return (D.pages_by_work || {})[args.workId] || [];
      case "get_footnotes": return (D.footnotes_by_work || {})[args.workId] || [];
      case "get_page_units":
        return ((D.units_by_work || {})[args.workId] || {})[String(args.pdfPage)] || [];
      case "get_units": return [];
      case "get_unit": return null;
      case "find_by_gw_page": return null;
      case "search_corpus":
        return (args.query || "").includes("Aufhebung") ? D.search_corpus_b : D.search_corpus;
      case "citation": return D.citation;
      case "list_annotations": return D.list_annotations;
      case "save_annotation": return 1;
      case "delete_annotation": return null;
      case "list_bookmarks": return D.list_bookmarks;
      case "add_bookmark": return null;
      case "remove_bookmark": return null;
      case "list_glossary": return D.list_glossary;
      case "save_glossary": return 1;
      case "delete_glossary": return null;
      case "get_progress": return D.get_progress;
      case "set_progress": return null;
      case "corpus_location": return "/tmp/corpus.db";
      case "get_settings": return D.get_settings || {};
      case "set_setting": return null;
      default: throw new Error("mock 未实现：" + cmd);
    }
  },
  transformCallback: (cb) => ({ f: cb }),
};
`;

/**
 * 起一个浏览器。
 *
 * 按顺序试，谁能用就用谁：
 *   1. Playwright 自带的 Chromium —— `npx playwright install chromium` 之后的标准路径
 *   2. 系统装的 Edge
 *   3. 系统装的 Chrome
 *
 * 后两条是给不想下 150 MB 浏览器的人留的：装了 Edge/Chrome 就能直接跑。
 */
async function launchBrowser() {
  const attempts = [
    { label: "Playwright 自带的 Chromium", options: {} },
    { label: "系统 Edge", options: { channel: "msedge" } },
    { label: "系统 Chrome", options: { channel: "chrome" } },
  ];
  const failures = [];
  for (const attempt of attempts) {
    try {
      return await chromium.launch(attempt.options);
    } catch (error) {
      failures.push(`${attempt.label}：${String(error.message).split("\n")[0]}`);
    }
  }
  throw new Error(
    "起不来浏览器。依次试过：\n  " + failures.join("\n  ") +
      "\n装一个就行：npx playwright install chromium",
  );
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await launchBrowser();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

  const errors = [];
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(String(e)));

  await page.addInitScript(
    ({ mock, data }) => {
      window.__MOCK__ = data;
      eval(mock);
    },
    { mock: MOCK, data: DATA },
  );

  await page.goto("http://localhost:5173", { waitUntil: "networkidle" });
  await page.waitForSelector(".toolbar", { timeout: 15000 });
  await page.waitForTimeout(1200);

  const shot = async (name) => {
    await page.screenshot({ path: path.join(OUT, `${name}.png`) });
    console.log("  →", path.join(OUT, `${name}.png`));
  };

  const problems = [];
  const check = (ok, message) => {
    console.log(`  ${ok ? "✓" : "✗"} ${message}`);
    if (!ok) problems.push(message);
  };

  // ── ① 卷目按数字排序 ──────────────────────────────────────────
  console.log("① 卷目排序");
  const volumes = await page.$$eval(".work-select option", (els) =>
    els.map((el) => el.textContent.trim()),
  );
  check(volumes.length === 41, `共 ${volumes.length} 卷`);

  // 按作者分组
  const volumeGroups = await page.$$eval(".work-select optgroup", (els) =>
    els.map((el) => ({
      label: el.getAttribute("label"),
      items: [...el.querySelectorAll("option")].map((o) => o.textContent.trim()),
    })),
  );
  check(
    volumeGroups.length === 3,
    `卷目按作者分三组：${volumeGroups.map((g) => g.label).join(" / ")}`,
  );

  // 黑格尔组内按卷号数字升序
  const hegel = volumeGroups.find((g) => g.label?.includes("黑格尔"));
  const numbers = (hegel?.items ?? []).map((v) =>
    parseInt(v.match(/GW (\d+)/)?.[1] ?? "0", 10),
  );
  check(
    numbers.every((n, i) => i === 0 || n > numbers[i - 1]),
    `黑格尔组按卷号升序：${numbers.join(", ")}`,
  );
  check(numbers[0] === 1 && numbers[numbers.length - 1] === 21, "黑格尔 16 卷都在");

  // 费希特：SW 在前，NW 在后
  const fichte = volumeGroups.find((g) => g.label?.includes("费希特"));
  const fichteSigs = (fichte?.items ?? []).map((v) => v.split(" ·")[0]);
  check(
    fichteSigs.indexOf("NW I") > fichteSigs.indexOf("SW VIII"),
    `费希特 SW 在前 NW 在后：${fichteSigs.join(" ")}`,
  );
  check(fichteSigs.length === 11, `费希特 ${fichteSigs.length} 卷`);

  // 谢林：SW I/1 … I/10，然后 SW II/1 … II/4
  const schelling = volumeGroups.find((g) => g.label?.includes("谢林"));
  const schellingSigs = (schelling?.items ?? []).map((v) => v.split(" ·")[0]);
  check(
    schellingSigs.indexOf("SW II/1") > schellingSigs.indexOf("SW I/10"),
    `谢林 SW I 在前 SW II 在后：${schellingSigs.join(" ")}`,
  );
  check(schellingSigs.length === 14, `谢林 ${schellingSigs.length} 卷`);
  await shot("01-reader");

  // ── ② 工具条按钮不换行 ────────────────────────────────────────
  console.log("② 标题栏");
  const wrap = await page.$$eval(".toolbar button", (els) =>
    els
      .filter((el) => el.getBoundingClientRect().height > 34)
      .map((el) => el.textContent.trim()),
  );
  check(wrap.length === 0, `没有折行的按钮${wrap.length ? "：" + wrap.join(",") : ""}`);

  // 顶栏必须只有一行
  const rows = await page.$eval(".toolbar", (el) => {
    const kids = [...el.children].filter((c) => getComputedStyle(c).display !== "none");
    const rects = kids.map((c) => c.getBoundingClientRect());
    const top = Math.min(...rects.map((r) => r.top));
    const bottom = Math.max(...rects.map((r) => r.bottom));
    const tallest = Math.max(...rects.map((r) => r.height));
    return { span: bottom - top, tallest, height: el.getBoundingClientRect().height };
  });
  // 所有控件都落在同一条竖直带里，才算一行
  check(
    rows.span < rows.tallest * 1.6,
    `顶栏只有一行（竖向跨度 ${Math.round(rows.span)}px，最高的控件 ${Math.round(rows.tallest)}px）`,
  );

  // 悬浮翻页按钮在阅读区两侧
  const nav = await page.$$eval(".page-nav", (els) =>
    els.map((el) => {
      const r = el.getBoundingClientRect();
      const reader = document.querySelector(".reader").getBoundingClientRect();
      return {
        cls: el.className,
        left: Math.round(r.left),
        right: Math.round(r.right),
        readerLeft: Math.round(reader.left),
        readerRight: Math.round(reader.right),
        opacity: getComputedStyle(el).opacity,
      };
    }),
  );
  check(nav.length === 2, `阅读区两侧各有一个翻页按钮（${nav.length} 个）`);
  check(
    nav[0] && nav[0].left >= nav[0].readerLeft && nav[1] && nav[1].right <= nav[1].readerRight,
    "翻页按钮在阅读区边缘内侧",
  );
  check(
    nav.every((n) => n.opacity === "0"),
    `翻页按钮平时是隐形的（不挡正文）${nav.map((n) => n.opacity).join(",")}`,
  );
  // 翻页按钮不能压在滚动条上
  const clear = await page.evaluate(() => {
    const reader = document.querySelector(".reader");
    const wrap = document.querySelector(".reader-wrap");
    const next = document.querySelector(".page-nav-next");
    const sb = reader.offsetWidth - reader.clientWidth;
    const nr = next.getBoundingClientRect();
    const wr = wrap.getBoundingClientRect();
    return { sb, gap: Math.round(wr.right - nr.right) };
  });
  check(
    clear.gap >= clear.sb,
    `右侧翻页按钮避开了滚动条（滚动条 ${clear.sb}px，按钮留出 ${clear.gap}px）`,
  );

  await page.hover(".reader-wrap");
  await page.waitForTimeout(300);
  const shown = await page.$eval(".page-nav-next", (el) => getComputedStyle(el).opacity);
  check(shown === "1", `鼠标移入阅读区后翻页按钮浮现（opacity ${shown}）`);

  const toolbarBox = await page.$eval(".toolbar", (el) => {
    const r = el.getBoundingClientRect();
    const kids = [...el.children].map((c) => c.getBoundingClientRect());
    const left = Math.min(...kids.map((k) => k.left));
    const right = Math.max(...kids.map((k) => k.right));
    return { width: r.width, left, right, center: (left + right) / 2 };
  });
  const offCenter = Math.abs(toolbarBox.center - toolbarBox.width / 2);
  check(offCenter < 24, `工具条内容居中（偏移 ${offCenter.toFixed(0)}px）`);

  // ── ③ 侧栏可拖动、可收起 ──────────────────────────────────────
  console.log("③ 侧栏");

  // 分隔线要细
  const splitterWidth = await page.$eval(".splitter", (el) =>
    Math.round(el.getBoundingClientRect().width));
  check(splitterWidth <= 4, `分隔线很细（${splitterWidth}px）`);

  // 目录要跟着当前页高亮。
  // 第一卷开头是书名页（不属于任何章节），所以先点目录跳到有章节的地方。
  const tocItems = await page.$$(".toc-link");
  await tocItems[4].click();
  await page.waitForTimeout(900);
  const tocCurrent = await page.$$eval(".toc-link.current", (els) =>
    els.map((el) => el.textContent.trim()));
  check(tocCurrent.length === 1, `目录有且只有一项高亮（${tocCurrent.length} 项）`);
  check(!!tocCurrent[0], `点目录跳转后高亮的是「${tocCurrent[0]}」`);
  const before = await page.$eval(".layout", (el) => getComputedStyle(el).gridTemplateColumns);
  const splitter = await page.$(".splitter");
  const box = await splitter.boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + 300);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 90, box.y + 300, { steps: 8 });
  await page.mouse.up();
  await page.waitForTimeout(300);
  const after = await page.$eval(".layout", (el) => getComputedStyle(el).gridTemplateColumns);
  check(before !== after, `拖动改变了侧栏宽度：${before} → ${after}`);
  await shot("02-resized");

  await page.click(".statusline .status-toggle:first-of-type");
  await page.waitForTimeout(300);
  const leftHidden = await page.$eval(".sidebar", (el) => el.getBoundingClientRect().width);
  check(leftHidden < 2, `左栏已收起（宽 ${leftHidden}px）`);

  await page.click(".statusline .status-toggle:last-of-type");
  await page.waitForTimeout(300);
  const rightHidden = await page.$eval(".sidepanel", (el) => el.getBoundingClientRect().width);
  check(rightHidden < 2, `右栏已收起（宽 ${rightHidden}px）`);
  await shot("03-immersive");

  await page.click(".statusline .status-toggle:first-of-type");
  await page.click(".statusline .status-toggle:last-of-type");
  await page.waitForTimeout(300);

  // 收起侧栏时文档不能多出横向滚动条。
  // grid 子项默认 `min-width: auto`，侧栏收起后内容仍撑着轨道，
  // 文档就会宽出那么 1px —— 窗口底部冒出一条横向滚动条。
  for (const width of [1244, 1920, 2488]) {
    await page.setViewportSize({ width, height: 900 });
    await page.waitForTimeout(350);
    const over = await page.evaluate(() => {
      const de = document.documentElement;
      const scrollers = [];
      for (const el of document.querySelectorAll("*")) {
        const cs = getComputedStyle(el);
        if ((cs.overflowX === "auto" || cs.overflowX === "scroll") &&
            el.scrollWidth > el.clientWidth + 0.5) {
          scrollers.push((el.className || "").toString().slice(0, 20));
        }
      }
      return { doc: de.scrollWidth - de.clientWidth, scrollers };
    });
    check(over.doc <= 0, `宽 ${width}：文档不溢出（多出 ${over.doc}px）`);
    check(over.scrollers.length === 0, `宽 ${width}：没有横向滚动容器 ${over.scrollers.join(",")}`);
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForTimeout(300);

  // ── ④ 底栏书目信息 ────────────────────────────────────────────
  console.log("④ 底栏");
  const status = await page.$eval(".statusline", (el) => el.textContent);
  check(/黑格尔/.test(status), "底栏有作者");
  check(/GW \d+/.test(status), "底栏有卷次");
  check(/第 \d+ 页/.test(status), "底栏有页码");
  check(!/离线运行/.test(status), "底栏没有「离线运行」");

  // 底栏不该在中间留一大段空白：卷名按自然宽度摆着，
  // 余量全给章节路径，余量留在最右端。
  const gap = await page.evaluate(() => {
    const info = document.querySelector(".status-info");
    const kids = [...info.children].map((el) => {
      const r = el.getBoundingClientRect();
      return { cls: (el.className || "").toString().slice(0, 20), left: r.left, right: r.right };
    });
    const gaps = [];
    for (let i = 1; i < kids.length; i++) {
      gaps.push(Math.round(kids[i].left - kids[i - 1].right));
    }
    return { gaps, infoWidth: Math.round(info.getBoundingClientRect().width) };
  });
  check(
    gap.gaps.every((g) => g <= 24),
    `底栏各项之间没有大空隙（间隙 ${gap.gaps.join(", ")}px）`,
  );

  // 底栏不能有横向滚动条
  const scroll = await page.$eval(".statusline", (el) => ({
    overflowX: el.scrollWidth - el.clientWidth,
    infoOverflow: (() => {
      const info = el.querySelector(".status-info");
      return info.scrollWidth - info.clientWidth;
    })(),
  }));
  check(scroll.overflowX <= 1, `底栏没有横向滚动条（溢出 ${scroll.overflowX}px）`);
  check(scroll.infoOverflow <= 1, `书目区没有横向滚动条（溢出 ${scroll.infoOverflow}px）`);

  // 开关是纯图标：无文字、无外框
  const toggles = await page.$$eval(".status-toggle", (els) =>
    els.map((el) => ({
      text: el.textContent.trim(),
      border: getComputedStyle(el).borderTopWidth,
      hasIcon: !!el.querySelector("svg"),
      width: el.getBoundingClientRect().width,
    })),
  );
  check(
    toggles.length === 2 && toggles.every((t) => t.text === "" && t.hasIcon),
    `两个开关都是纯图标（文字：${toggles.map((t) => JSON.stringify(t.text)).join(",")}）`,
  );
  check(
    toggles.every((t) => parseFloat(t.border) === 0),
    `开关没有外框（border: ${toggles.map((t) => t.border).join(",")}）`,
  );

  // 图标形状固定：展开收起都画同一侧，不靠换图标表达状态
  const shapes = await page.$$eval(".status-toggle svg", (els) =>
    els.map((el) => el.innerHTML.replace(/\s+/g, "")),
  );
  check(
    shapes.length === 2 && shapes[0] !== shapes[1],
    "两个图标形状不同（左/右各一），但每侧只有一个形状",
  );
  const iconBefore = shapes[0];
  await page.click(".statusline .status-toggle:first-of-type");
  await page.waitForTimeout(250);
  const iconAfter = (await page.$$eval(".status-toggle svg", (els) =>
    els.map((el) => el.innerHTML.replace(/\s+/g, "")),
  ))[0];
  check(iconBefore === iconAfter, "收起侧栏后图标不变（状态只靠高亮区分）");
  await page.click(".statusline .status-toggle:first-of-type");
  await page.waitForTimeout(250);

  // 中间省略号：把窗口收窄，章节路径应当从中间截断
  const fullPath = await page.$eval(".status-section .middle-ellipsis-box", (el) => el.title);
  await page.setViewportSize({ width: 720, height: 900 });
  await page.waitForTimeout(500);
  const narrow = await page.$eval(".status-section .middle-ellipsis-box", (el) => el.textContent);
  const fits = await page.$eval(".status-section .middle-ellipsis-box", (el) => ({
    w: el.clientWidth,
    sw: el.scrollWidth,
  }));
  check(fits.sw <= fits.w + 1, `窄窗口下章节路径没有溢出（${fits.sw} ≤ ${fits.w}）`);
  check(
    !narrow.includes("…") || narrow.length < fullPath.length,
    `窄窗口下章节路径被截断：${JSON.stringify(narrow.slice(0, 46))}`,
  );
  // 章节路径按**层级**截断：保住最后一级，断口落在「›」边上
  const segments = fullPath.split(" › ");
  const last = segments[segments.length - 1];
  check(narrow.includes("… › "), `窄窗口下按层级截断：${JSON.stringify(narrow.slice(0, 60))}`);
  check(
    narrow.endsWith(last) || narrow.replace(/…$/, "").endsWith(last),
    `最后一级「${last}」完整保留`,
  );
  const kept = narrow.replace(/^… › /, "");
  check(
    segments.some((seg) => kept === seg || kept.endsWith(seg)),
    "断口落在层级边界上（不是拦腰砍断）",
  );
  // 悬停应能看到完整路径
  const tip = await page.$eval(".status-section .middle-ellipsis-box", (el) => el.title);
  check(tip === fullPath, "悬停显示完整路径");

  // 量宽度的探针不该留在 DOM 里 —— 早先它在，底栏的文字会被复制两遍
  const probes = await page.$$eval(".middle-ellipsis-probe", (els) => els.length);
  check(probes === 0, `没有多余的探针元素（${probes} 个）`);
  const statusText = await page.$eval(".statusline", (el) => el.textContent);
  const occurrences = statusText.split(fullPath).length - 1;
  check(
    occurrences <= 1,
    `底栏文字没有被复制两遍（完整路径出现 ${occurrences} 次）`,
  );

  // 宽窗口下应完整显示
  await page.setViewportSize({ width: 1800, height: 900 });
  await page.waitForTimeout(400);
  const wide = await page.$eval(".status-section .middle-ellipsis-box", (el) => el.textContent);
  check(wide === fullPath, `宽窗口下路径完整显示：${JSON.stringify(wide.slice(0, 40))}`);

  await page.setViewportSize({ width: 720, height: 900 });
  await page.waitForTimeout(400);
  await shot("06-narrow-status");
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForTimeout(400);

  // ── ⑤ 批注文本框只调高度 ──────────────────────────────────────
  console.log("⑤ 批注文本框");
  await page.click("button:has-text('批注')");
  await page.waitForTimeout(400);
  const resize = await page.$eval(".annotation-form textarea", (el) => getComputedStyle(el).resize);
  check(resize === "vertical", `文本框只能调高度（resize: ${resize}）`);
  const overflow = await page.$eval(".annotation-form textarea", (el) => {
    const r = el.getBoundingClientRect();
    const parent = el.parentElement.getBoundingClientRect();
    return r.width > parent.width + 1;
  });
  check(!overflow, "文本框宽度没有溢出侧栏");
  await shot("04-annotations");

  // ── ⑥ 排版面板 ────────────────────────────────────────────────
  console.log("⑥ 排版");
  await page.click("button:has-text('排版')");
  await page.waitForTimeout(400);
  check(await page.$(".typo-panel") !== null, "排版面板打开了");

  const base = await page.$eval(".unit-paragraph", (el) => ({
    size: parseFloat(getComputedStyle(el).fontSize),
    leading: parseFloat(getComputedStyle(el).lineHeight) /
             parseFloat(getComputedStyle(el).fontSize),
    measure: Math.round(document.querySelector(".unit-wrap").getBoundingClientRect().width),
  }));

  // 字号滑块
  await page.$eval(".typo-range", (el) => {
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
    setter.call(el, "1.4");
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await page.waitForTimeout(350);
  const bigger = await page.$eval(".unit-paragraph", (el) =>
    parseFloat(getComputedStyle(el).fontSize));
  check(bigger > base.size, `字号滑块放大了正文（${base.size}px → ${bigger}px）`);

  // 行距滑块（第三个）
  await page.$eval(".typo-range:nth-of-type(1)", () => {});
  await page.$$eval(".typo-range", (els) => {
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
    const el = els[2];
    setter.call(el, "2.0");
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await page.waitForTimeout(350);
  const leadAfter = await page.$eval(".unit-paragraph", (el) =>
    parseFloat(getComputedStyle(el).lineHeight) / parseFloat(getComputedStyle(el).fontSize));
  check(leadAfter > base.leading + 0.1, `行距滑块拉开了行距（${base.leading.toFixed(2)} → ${leadAfter.toFixed(2)}）`);

  // 版心宽度（第二个）
  const widthBefore = await page.$eval(".unit-wrap", (el) =>
    Math.round(el.getBoundingClientRect().width));
  await page.$$eval(".typo-range", (els) => {
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
    const el = els[1];
    setter.call(el, "52");
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await page.waitForTimeout(350);
  const widthAfter = await page.$eval(".unit-wrap", (el) =>
    Math.round(el.getBoundingClientRect().width));
  check(widthAfter > widthBefore, `版心变宽了（${widthBefore}px → ${widthAfter}px）`);

  const measures = await page.$$eval(".typo-range", (els) => els.length);
  check(measures === 3, `面板有三个滑块（字号/宽度/行距），实际 ${measures}`);

  // 主题
  await page.click(".typo-chip.theme-night");
  await page.waitForTimeout(350);
  const night = await page.evaluate(() => ({
    theme: document.documentElement.dataset.theme,
    bg: getComputedStyle(document.body).backgroundColor,
  }));
  check(night.theme === "night", "切到了夜间主题");
  check(night.bg !== "rgb(247, 245, 240)", `夜间主题背景变了（${night.bg}）`);
  await shot("07-night");
  await page.click(".typo-chip.theme-paper");
  await page.waitForTimeout(300);

  // 设置要存下去
  const saved = await page.evaluate(() =>
    [...(window.__MOCK_CALLS__ || [])].filter((c) => c[0] === "set_setting").map((c) => c[1]));
  check(saved.length > 0, `设置已写回（${saved.length} 项）`);

  await page.click('.typo-head button[aria-label="关闭"]');
  await page.waitForTimeout(250);
  check(await page.$(".typo-panel") === null, "面板能关掉");

  // ── ⑦ 检索 ────────────────────────────────────────────────────
  console.log("⑦ 检索");
  // 检索现在是图标，点开才变输入框
  check(
    (await page.$(".search-input")) === null,
    "检索框默认收着（顶栏只有一个放大镜）",
  );
  await page.click('.icon-button[aria-label="检索"]');
  await page.waitForTimeout(250);
  check((await page.$(".search-input")) !== null, "点图标后检索框展开");
  await page.fill(".search-input", "Verhältniß");
  await page.waitForTimeout(900);
  const hits = await page.$$eval(".search-hit", (els) =>
    els.slice(0, 5).map((el) => ({
      loc: el.querySelector(".hit-loc")?.textContent,
      marked: el.querySelectorAll("mark.hit").length,
    })),
  );
  check(hits.length > 0, `检索有 ${hits.length} 处命中`);
  check(hits.every((h) => h.marked > 0), "每处命中都有高亮");
  const groups = await page.$$eval(".search-group-head", (els) => els.map((e) => e.textContent));
  check(groups.length > 0, `结果按卷分组：${groups.slice(0, 5).join(", ")}`);

  // 点检索结果跳到另一页，目录的高亮要跟过去
  const beforeJump = await page.$eval(".toc-link.current", (el) => el.textContent.trim());
  await page.click(".search-hit");
  await page.waitForTimeout(1200);
  const afterJump = await page.$eval(".toc-link.current", (el) => el.textContent.trim());
  check(
    afterJump.length > 0,
    `检索跳转后目录有高亮：「${afterJump}」`,
  );
  // 高亮项应当落在目录的可视范围内（目录自己滚过去了）
  const inView = await page.$eval(".toc-link.current", (el) => {
    const r = el.getBoundingClientRect();
    const box = el.closest(".sidebar").getBoundingClientRect();
    return r.top >= box.top - 2 && r.bottom <= box.bottom + 2;
  });
  check(inView, `高亮项已滚进目录可视区（跳转前是「${beforeJump}」）`);
  await shot("05-search");

  console.log("\n渲染结果：", await page.evaluate(() => ({
    unitCount: document.querySelectorAll(".unit").length,
    sperrsatz: document.querySelectorAll(".sperrsatz").length,
  })));
  console.log(errors.length ? `控制台错误 ${errors.length} 条:` : "控制台无错误");
  errors.slice(0, 6).forEach((e) => console.log("  !", e));

  await browser.close();
  console.log(problems.length ? `\n${problems.length} 项未通过` : "\n全部检查通过");
  process.exit(errors.length || problems.length ? 1 : 0);
})();
