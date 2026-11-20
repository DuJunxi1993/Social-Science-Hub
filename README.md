# 社科研读 · Social Science Hub

以德国理想主义三家的数字版为底本的**离线**中文研读工具。

底本来自 Giuliano Infantino 编纂的三套数字版（均 **CC BY 4.0**；原文属公有领域）：

| 版本 | 站点 | 卷 |
|---|---|---|
| 黑格尔 | [hegel.idealismedition.com](https://hegel.idealismedition.com) | 16 |
| 费希特 | [fichte.idealismedition.com](https://fichte.idealismedition.com) | 11 |
| 谢林 | [schelling.idealismedition.com](https://schelling.idealismedition.com) | 14 |

本项目不是把那几个网站翻译一遍，而是拿它们的**源数据**重新做：

- 语料以 **SQLite** 落地，离线可用，检索由 FTS5 承担
- 德语旧正字法（`Seyn`/`daß`/`Verhältniß`）与现代拼写互查
- 双层呈现：**阅读层**（连排正文）与**印刷层**（复刻原书行号断行）
- 用户数据（批注、书签、术语表、阅读进度、阅读偏好）独立存储，语料升级不丢

## 目录结构

```
etl/                  语料 ETL（Python）
  sshex/
    ortho.py          德语旧正字法归一
    tei.py            TEI 解析 → 双层文本结构
    db.py             SQLite schema 与写入
    search.py         查询解析与检索
    fetch.py          从数字版下载源 TEI
    cli.py            命令行入口
  tests/              43 个用例
app/                  桌面应用（Tauri v2 + React/TS）
  src/                前端
  src-tauri/          Rust 后端（33 个用例，含针对真语料库的集成测试）
tools/                前端验证脚本（Playwright，66 项检查）
data/                 ETL 产物（corpus.db、tei/）
```

## 快速开始

仓库里只有代码。语料从[语料快照](#语料快照)取（推荐），或直接从原站重建。

```bash
# 1. 拿语料 —— 从快照取
curl -LO https://github.com/DuJunxi1993/Social-Science-Hub/releases/download/corpus-1.0/tei-1.0.tar.gz
tar xzf tei-1.0.tar.gz && mv tei data/
#   或者只要建好的库（省掉 ETL）：
#   curl -LO .../corpus-1.0.db.gz && gunzip corpus-1.0.db.gz && mv corpus.db data/

# 2. 装依赖
cd etl && python3 -m venv .venv && ./.venv/bin/pip install -e '.[dev]'
cd ../app && npm install

# 3. 跑桌面应用
npm run app          # 开发模式（Vite + Rust）
npm run app:build    # 打包 .app / .dmg
```

直接从原站重建（拿到的会是原站当时的样子，不是快照）：

```bash
cd etl && ./.venv/bin/python -m sshex build --work all \
    --db ../data/corpus.db --cache ../data/tei
```

> **沙箱里的两个坑**：`~/.cargo` 与 `~/.npm` 可能没有写权限。用
> `CARGO_HOME=../.cargo-home` 与 `npm install --cache ./.npm-cache` 绕开。

## 测试

```bash
cd etl && ./.venv/bin/python -m pytest tests/ -q          # 43 个
cd app/src-tauri && cargo test --release                    # 33 个（含集成测试）
```

Rust 侧的集成测试直接打开 `data/corpus.db` 跑完整链路：旧拼写能否查到、
命中带不上 GW 行号、短语与布尔、章节路径带不带层级、跨卷检索、每卷的
结构是否自洽。

**检索层有两份实现** —— Python（`etl/sshex/search.py`）和 Rust
（`app/src-tauri/src/search.rs`），行为必须一致：同一个查询在命令行里和在
应用里要给出同样的命中、同样的高亮区间。两边的测试用例一一对应。

前端用 Playwright 验证（`tools/shoot.js`）：把 Tauri 的 IPC 换成从真语料库
导出的假实现，于是渲染、检索、目录、版式切换都能在无头浏览器里跑：

```bash
cd tools && npm install --cache ./.npm-cache
npx playwright install chromium        # 首次要下浏览器（约 150 MB）
node shoot.js /tmp/shots
```

夹具 `tools/mock-data.json` 是**生成物**，不入版本库 —— 从真语料库里切一片
出来。重建了语料库就重新生成：

```bash
etl/.venv/bin/python tools/make-mock.py
```

## 语料库里有什么

**三家版本、四十一卷**：

| 版本 | 卷 | 站点 | 印刷页 | 单元 | 章节 | 脚注 |
|---|---|---|---|---|---|---|
| 黑格尔 | 16 | hegel.idealismedition.com | 6242 | 24232 | 1318 | 1614 |
| 费希特 | 11 | fichte.idealismedition.com | 6424 | 22460 | 676 | 582 |
| 谢林 | 14 | schelling.idealismedition.com | 7881 | 29786 | 944 | 3421 |
| **合计** | **41** | | **20547** | **76478** | **2938** | **5617** |

脚注数与原站各版的统计**逐卷完全一致**（1614 / 582 / 3421）。
脚注分三种：页脚注、边注（``type="rand"``）、行下注与行上注 ——
后三种印在版心边缘，同样被正文里的锚点引用，所以一并收进脚注表。

三家都是 Giuliano Infantino 编纂的数字版，**CC BY 4.0**；原文本身是公有领域。
卷目不写死在代码里 —— 每次建库都从各站点的 ``assets/edition-data.js`` 读，
站点更新了卷目这边跟着更新。

以 GW 12《Wissenschaft der Logik》(1816) 为例：310 页、1259 个单元、
10537 个印刷行、86 个章节。

数据模型（`data/corpus.db`）：

```
work      一卷的元数据与授权信息
page      印刷页：GW 页码、PDF 页码、书眉、帖码
section   章节树（层级来自各卷自己的印刷目录）
unit      内容单元：正文 + 疏排区间 + 引用 + 印刷行 + 行区间表
footnote  脚注（含 prev/next 链）
xref      互引
toc_printed  书前的印刷目录
unit_fts  FTS5 全文索引（存归一后的词）
```

**页码是字符串，不是整数。** 卷首的页是罗马数字（„V“、„XXVII“），
正文页才是阿拉伯数字 —— 引用 „SW I, V.3“ 指的就是卷首那一页。
所以 `book_page` 一律按文本存。

**没有「词 → 偏移」表。** 检索命中后要指出原文的哪一段，乍看需要一张带偏移
的词表（十六卷近两百万个词，连索引要 101 MB，占全库的 58%）。但 FTS5 已经
告诉我们「这个单元命中了」，剩下的只是在一千三百来个字里找那几个词 —— 检索
时现切现算，是微秒级的。去掉那张表，库从 173 MB 瘦到 71 MB。

**两套坐标系**：PDF 页码（扫描本）与 GW 页码（印刷页）。
引用格式是 `GW 12, 241.36`（页.行），所以每个单元都存了行区间表，
任意一个命中位置都能反查它落在第几行。

## 语料快照

语料是这个项目的核心资产，却有 226 MB —— 进不了 git，放进仓库也不合适。
于是它以**快照**的形式单独发布：一旦某一版发出去，那个时间点的语料就固化了，
不再依赖原站是否还在、是否还改版。

最新一版：[语料快照 1.0](https://github.com/DuJunxi1993/Social-Science-Hub/releases/tag/corpus-1.0)

| 文件 | 体积 | 说明 |
|---|---|---|
| `tei-1.0.tar.gz` | 17 MB | **41 个源 TEI** —— 事实来源 |
| `corpus-1.0.db.gz` | 63 MB | 建好的语料库，解压即用 |
| `manifest-1.0.json` | 14 KB | 校验和、逐卷来源、内容指纹 |

```bash
# 不想跑 ETL：直接用建好的库
gunzip corpus-1.0.db.gz && mkdir -p data && mv corpus.db data/

# 要改解析逻辑：从源 TEI 重建
tar xzf tei-1.0.tar.gz
cd etl && ./.venv/bin/python -m sshex build --work all \
    --db ../data/corpus.db --cache ../data/tei
```

`manifest` 里有两个东西：**文件校验和**（确认下载没损坏）与**内容指纹**
（确认重建出的库内容等价）。指纹覆盖每个内容单元与每条脚注，按固定顺序
哈希，**只管内容不管 SQLite 的物理布局** —— 重建出的库字节可能不同，
指纹一样即证明内容一致。

自己打快照：

```bash
etl/.venv/bin/python tools/make-snapshot.py --version 1.1
```

## 与原站的关系

原站的 `assets/en/tei-leser.js` 是一份 13.7 KB 的 JavaScript，把源 TEI 派生成
阅读层与印刷层。本项目的 `etl/sshex/tei.py` 按同一套规则重写了一遍，
并用原站自己产出的搜索索引（`assets/suche/gw-12.json`）做交叉校验：

| 校验项 | 结果 |
|---|---|
| 单元数 | 1169 / 1169 一致 |
| 印刷行号序列 | 1169 / 1169 逐条一致 |
| 阅读层正文 | 逐条一致，仅 2 处有差 |

那 2 处差是**原站会丢字**的地方：脚注锚点的文字是 `∗)`，
原站在阅读层把这个 `)` 一并丢掉了；本项目保留它，并把锚点存成可点击的
引用区间。其余全部逐字相同。

差异之处还有两处是刻意的：

- **目录页不进检索索引**（原站同样如此）——「Inhalt」「Verlag」这类词会把
  检索结果淹没。但目录页照常可读。
- **归一只作用于检索键**，显示的永远是黑格尔 1816 年的原文。

## 检索语法

```
a b                 两词都出现（隐含 AND）
a AND b  /  OR      布尔
a NOT b             有 a 无 b
"genauer Begriff"   短语
Begriff*            前缀
a NEAR b            邻近（nah / vor 同义）
=begriff            精确匹配，不展开异体
```

正字法归一让这些都能查到：`Sein`→`Seyn`、`daß`/`dass`、
`Verhältniß`/`Verhältnis`、`Proceß`/`Prozess`、`Cultur`/`Kultur`，
以及异体组 `jetzt`/`itzt`、`nämlich`/`nemlich`、`gibt`/`giebt`。

规则表与原站 `assets/en/ortho.js` 一致，并有两处**已知的缺口**记在
`etl/tests/test_ortho.py` 里（如 `Verhältnüß` 归不到 `Verhältnis`，
GW12 全卷 2 处）。

## 加卷

```bash
cd etl && ./.venv/bin/python -m sshex build --work all --db ../data/corpus.db
```

`fetch.VOLUMES` 里列了全部十六卷（GW 1, 3–9, 11, 12, 15, 17–21）。
ETL 是逐卷独立的，加一卷只是多跑一遍。

下载是网络往返（每卷 0.3–1.6 MB），解析与入库却只要不到一秒 —— 所以
**下载并行、解析串行**，十六卷从二十分钟缩到三分钟（`--workers` 控制并发数）。
已经缓存过的卷不再走网络，全量重建十六卷只要 5 秒。

改完 ETL 的产出格式后，要把 `app/src-tauri/src/db.rs` 里的 `CORPUS_VERSION`
加一 —— 应用启动时发现版本对不上，就重新复制一份资源里的语料库。

## 界面

```
┌──────────────────────────────────────────────────────────┐
│              标题栏（居中）：卷 · 翻页 · 检索 · 版式       │
├────────┬───────────────────────────────┬────────────────┤
│ 目录   │                               │ 脚注/批注/词表 │
│（可拖宽）│           正文                │（可拖宽）      │
├────────┴───────────────────────────────┴────────────────┤
│ [目录] 黑格尔 GW 12 · 第 5 页 · 章节路径 │         [面板] │
└──────────────────────────────────────────────────────────┘
```

- **排版面板**：字号（80–150%）、版心宽度（26–56rem）、行距、衬线/无衬线、
  四套主题（纸色/纯白/米黄/夜间）。设置写进工作区库，下次打开还在
- **顶栏只有一行**：检索收成一个放大镜（点了才展开输入框）；翻页按钮浮在
  阅读区左右边缘，鼠标移入才浮现；窗口再窄时次要按钮自动折进「⋯」菜单
- **目录跟着当前页高亮**：翻页、点目录、从检索结果跳过去（跨卷也行），
  目录都会高亮到对应章节，并把那一项滚进可视区
- 阅读区滚动条宽度定死（10px）并始终预留位置，右边的悬浮翻页按钮据此让开
- 底栏的章节路径按**层级**截断：丢掉又长又没信息量的卷名，断口永远落在
  「›」上，最后一级（正在读的那一节）完整保留
- **两侧栏可拖宽、可收起**；两边都收起就是沉浸阅读（快捷键 `f`）
- 底栏是书目信息：作者、卷次、当前页与行、当前章节路径
- 快捷键：`/` 检索 · `p` 切换版式 · `←` `→` 翻页 · `f` 沉浸 · `Esc` 关检索
- 检索范围可切「全部卷 / 本卷」，结果按卷分组

## 界面样式：token

所有尺寸、颜色、圆角、字号都从 `app/src/styles.css` 顶部的 `:root` 取值，
规则里不另写死。想把正文字号调大一点，只动 `--fs-body` 一个值。

| 前缀 | 含义 | 例子 |
|---|---|---|
| `--c-*` | 颜色 | `--c-text` `--c-accent` `--c-border` |
| `--space-*` | 间距（2px 起的等差级数） | `--space-7` = 14px |
| `--fs-*` | 字号 | `--fs-2xl` = 1.06rem |
| `--lh-*` | 行高 | `--lh-relaxed` = 1.72 |
| `--ls-*` | 字距 | `--ls-wide` = 0.14em |
| `--r-*` | 圆角 | `--r-md` = 4px |
| `--w-*` / `--h-*` | 尺寸 | `--w-reading` = 34rem |
| `--bw-*` | 边框粗细 | `--bw-hair` = 1px |
| `--em-*` / `--vh-*` / `--vw-*` | 随字号或视口缩放的量 | `--em-para-gap` = 1.05em |

## 与原站的对照

ETL 的正确性用原站当尺子量过 —— 原站自己的检索索引里存着每个单元的
阅读层文字，逐字比对：

| 卷 | 站上的单元 | 文字相同 | 不同 |
|---|---|---|---|
| 黑格尔 GW 12 | 1169 | 1169 | 0 |
| 费希特 SW I | 2163 | 2163 | 0 |
| 谢林 SW I/1 | 2015 | 2013 | 2 |

脚注数也逐卷比对过：四十一卷全部与原站一致。

两处已知的差异：

1. **疏排标记** —— 站的检索索引用 `*…*` 标疏排，我们用 span 标。
2. **脚注锚点** —— 站把锚点整个丢掉（黑格尔的 `∗)` 丢了右括号），
   我们原样留着。谢林那 2 处不同是一个印刷留下的竖线（`|`），
   站只在自己的**检索索引**里去掉它，阅读页上照旧显示。

## 许可与出处

**代码**（本仓库）：[MIT](LICENSE)。

**语料**（另作授权）：

- 黑格尔（卒于 1831）、费希特（卒于 1814）、谢林（卒于 1854）的原文均属**公有领域**
- 三套数字版的数据与改编归 Giuliano Infantino 所有，以 **CC BY 4.0** 授权：
  - [Digital Hegel Edition](https://hegel.idealismedition.com)
  - [Digitale Fichte-Edition](https://fichte.idealismedition.com)
  - [Digitale Schelling-Edition](https://schelling.idealismedition.com)
- 本项目按 CC BY 4.0 的要求署名 —— 语料库每条卷记录里都有
  `license_attribution` 与 `license_url`

