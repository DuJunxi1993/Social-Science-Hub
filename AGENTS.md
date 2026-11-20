# AGENTS.md — 社科研读（Social Science Hub）

## 这是什么

德国理想主义三家的**离线**中文研读平台。黑格尔 16 卷、费希特 11 卷、
谢林 14 卷 —— 共 41 卷，20547 页，76478 个内容单元，5617 条脚注。

底本是 Giuliano Infantino 编纂的三套数字版（TEI XML，CC BY 4.0）。本项目
不翻译那些网站，而是拿它们的**源数据**重新做：TEI → SQLite（建库在
`etl/`）→ Tauri 桌面应用（`app/`）。

分支：`main` —— 只有这一个分支。

## 建库 / 跑起来

| 目的 | 命令 |
|------|------|
| 建全部 41 卷的语料库 | `cd etl && ./.venv/bin/python -m sshex build --work all --db ../data/corpus.db --cache ../data/tei` |
| 只建一卷 | 同上，把 `--work all` 换成 `--work gw-12` / `fsw-1` / `sw-I-01` |
| 看语料统计 | `cd etl && ./.venv/bin/python -m sshex stats` |
| 命令行检索 | `cd etl && ./.venv/bin/python -m sshex search Aufhebung` |
| 跑桌面应用 | `cd app && npm run app` |
| 打包 | `cd app && npm run app:build` |

语料库**不入版本库**（226 MB），由 ETL 生成。

## 测试

| 范围 | 命令 | 数量 |
|------|------|------|
| ETL | `cd etl && ./.venv/bin/python -m pytest tests/ -q` | 43 |
| Rust | `cd app/src-tauri && cargo test --release` | 33（15 项跑在真语料库上） |
| 前端 | `cd tools && node shoot.js /tmp/shots` | 66 |

前端的夹具 `tools/mock-data.json` 是**生成物**，从真语料库切出来。重建了
语料库就重新生成：`etl/.venv/bin/python tools/make-mock.py`。

## 几个坑

**TEI 文件名两家不同。** 黑格尔把卷号补零到两位（`gw-1` → `GW01.xml`），
费希特与谢林不补（`fsw-1` → `FSW1.xml`，`sw-I-01` → `SWI01.xml`）。
`fetch.py` 里两个候选都试。卷目本身**不写死** —— 每次建库从各站点的
`assets/edition-data.js` 读。

**页码是字符串，不是整数。** 卷首页是罗马数字（`V`、`XXVII`），正文页才是
阿拉伯数字。所以 `book_page` 一律 TEXT，引用串是 `SW I, V.3` 而不是 `SW I, 5.3`。

**脚注 id 只在一卷之内唯一。** `fn-135-1` 里的 135 是页码 —— 每卷都有自己的
`fn-135-1`。主键必须是 `(work_id, id)`，光用 id 的话后建的卷会把先建的卷的
脚注顶掉（建 41 卷能少一半脚注，而每卷单独看都是对的）。

**长脚注分多段。** `fn-233-1.t2` 是 `fn-233-1` 的续段（印在下一页），
`prev`/`next` 串起各段。主键用完整 id，用 `.t` 前的部分会把主段顶掉。

**边注也是脚注。** `type="rand"`（边注）、`darunter`（行下）、`ueber`（行上）
都被正文锚点引用，一并收进脚注表 —— 否则脚注数比原站少一大截。

**谢林有 Antiqua 标记。** `<milestone unit="schrift" type="antiqua-*"/>` 嵌在
段落里，不跳过会报错。

**`cargo test` 和 `tauri dev` 抢锁。** 后台跑着 `tauri dev` 时 `cargo test`
会一直挂着 —— 先停掉前者。

**本机装了 Edge 就能跑前端测试**，不必下 Playwright 的浏览器
（`tools/shoot.js` 按序尝试：自带 Chromium → 系统 Edge → 系统 Chrome）。

## 检索层有两份实现

Python（`etl/sshex/search.py`）和 Rust（`app/src-tauri/src/search.rs`），
行为必须一致：同一个查询在命令行里和在应用里要给出同样的命中、同样的
高亮区间。两边的测试用例一一对应 —— 改了一边，另一边也得改。

## 正确性怎么验

用原站当尺子：原站自己的检索索引（`assets/suche/<work>.json`）里存着每个
单元的阅读层文字，逐字比对。改了解析逻辑就重跑一遍。

两处已知的、**不算错**的差异：站用 `*…*` 标疏排（我们用 span 标）；站把
脚注锚点整个丢掉（我们原样留着）。
