//! 端到端测试：拿真正建出来的语料库跑一遍检索。
//!
//! 单元测试验的是函数；这里验的是**整条链路** —— ETL 产出的库能不能被
//! Rust 侧的查询解析、正字法归一、FTS5 检索、行号反查完整走通。
//!
//! 语料库不在仓库里（11 MB，且可以随时重新生成），所以找不到就跳过。

use rusqlite::Connection;
use sshub_lib::search;
use std::path::PathBuf;

fn corpus_path() -> Option<PathBuf> {
    // CARGO_MANIFEST_DIR = app/src-tauri
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../data/corpus.db")
        .canonicalize()
        .ok()?;
    if path.exists() {
        Some(path)
    } else {
        None
    }
}

fn open() -> Option<Connection> {
    let path = corpus_path()?;
    let conn = Connection::open(path).ok()?;
    // 只读打开
    conn.execute_batch("PRAGMA query_only = ON;").ok()?;
    Some(conn)
}

#[test]
fn 语料库_结构完整() {
    let Some(conn) = open() else {
        eprintln!("跳过：没有 data/corpus.db，先跑 `python -m sshex build --work gw-12`");
        return;
    };

    // 每一卷都要自洽：页、单元、章节、词表齐全，且没有落单的单元。
    let volumes: Vec<String> = conn
        .prepare("SELECT id FROM work ORDER BY id")
        .unwrap()
        .query_map([], |r| r.get(0))
        .unwrap()
        .flatten()
        .collect();

    assert!(!volumes.is_empty(), "库里一卷都没有");

    for volume in &volumes {
        let pages: i64 = conn
            .query_row("SELECT COUNT(*) FROM page WHERE work_id = ?1", [volume], |r| r.get(0))
            .unwrap();
        let units: i64 = conn
            .query_row("SELECT COUNT(*) FROM unit WHERE work_id = ?1", [volume], |r| r.get(0))
            .unwrap();
        let sections: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM section WHERE work_id = ?1",
                [volume],
                |r| r.get(0),
            )
            .unwrap();
        let tokens: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM unit_fts WHERE rowid IN
                    (SELECT id FROM unit WHERE work_id = ?1)",
                [volume],
                |r| r.get(0),
            )
            .unwrap();
        let orphan: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM unit WHERE work_id = ?1 AND section_id IS NULL",
                [volume],
                |r| r.get(0),
            )
            .unwrap();

        // 没有章节的单元只能是「前言」：书名页、目录页、题词 —— 都在第一个
        // 章节落点之前。正文里的单元必须都有归属。
        let stray: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM unit u
                 WHERE u.work_id = ?1 AND u.section_id IS NULL
                   AND u.id > COALESCE(
                       (SELECT MIN(s.unit_id) FROM section s
                        WHERE s.work_id = ?1 AND s.unit_id IS NOT NULL), 0)",
                [volume],
                |r| r.get(0),
            )
            .unwrap();

        assert!(pages > 100, "{volume} 的页数太少：{pages}");
        assert!(units > 500, "{volume} 的单元数太少：{units}");
        assert!(sections >= 10, "{volume} 的章节数太少：{sections}");
        // 章节密度：书自己的目录稀疏是常事（GW 15 是草稿集，只有 10 个分部，
        // 339 页 —— 那是这本书本来的结构），但再稀疏也不该到四十页没有落点。
        assert!(
            (pages as f64) / (sections as f64) < 40.0,
            "{volume} 的章节太稀：{pages} 页只有 {sections} 个章节"
        );
        assert!(tokens > 500, "{volume} 进索引的单元太少：{tokens}");
        // 前言（书名页、目录、编者序）不算章节，但也不能太多。
        // 阈值按比例算 —— 谢林各卷的「编者序」长得离谱
        // （SW I/5 有 46 个前言单元，因为编者序本身就有好几页）。
        let orphan_limit = (units / 10).max(50);
        assert!(
            orphan <= orphan_limit,
            "{volume} 的前言单元太多了：{orphan}（上限 {orphan_limit}）"
        );
        assert_eq!(stray, 0, "{volume} 有正文单元没归到章节");
    }

    // GW 12 的已知基线（用来发现语料悄悄变了）
    let units: i64 = conn
        .query_row("SELECT COUNT(*) FROM unit WHERE work_id = 'gw-12'", [], |r| r.get(0))
        .unwrap();
    let pages: i64 = conn
        .query_row("SELECT COUNT(*) FROM page WHERE work_id = 'gw-12'", [], |r| r.get(0))
        .unwrap();
    assert_eq!(units, 1259, "GW 12 的内容单元数变了");
    assert_eq!(pages, 310, "GW 12 的印刷页数变了");
}

#[test]
fn 旧拼写能查到() {
    let Some(conn) = open() else { return };

    // 这些词在 GW 12 里都有旧拼写，现代拼写也应当能查到它们。
    for query in ["Verhältniß", "Sein", "Proceß", "nemlich", "Substanz"] {
        let hits = search::search(&conn, query, Some("gw-12"), 5);
        assert!(!hits.is_empty(), "「{query}」应当有命中");
    }
}

#[test]
fn 卷里没有的词查不到() {
    let Some(conn) = open() else { return };

    // GW 12 是《逻辑学》，通篇没有 „Cultur“ 这个词 —— 归一规则是对的，
    // 但这卷里确实没有它。检索不该凭空造出命中。
    let hits = search::search(&conn, "Cultur", Some("gw-12"), 5);
    assert!(hits.is_empty(), "GW 12 里不该有 „Cultur“");
}

#[test]
fn 命中带得上_gw_行号() {
    let Some(conn) = open() else { return };

    let hits = search::search(&conn, "Verhältniß", Some("gw-12"), 10);
    assert!(!hits.is_empty());

    for hit in &hits {
        assert!(hit.book_page.is_some(), "命中没有 GW 页码");
        assert!(hit.gw_line.is_some(), "命中没有 GW 行号");
        // 片段里的高亮区间必须落在片段长度之内
        for (start, end) in &hit.matches {
            assert!(*start < *end);
            assert!(*end <= hit.snippet.chars().count());
        }
    }
}

#[test]
fn 短语与布尔() {
    let Some(conn) = open() else { return };

    // 注意：GW 12 里没有 „genauer Begriff“ 这个短语（genauer 后面从不
    // 紧跟 begriff），所以这里用确实存在的短语。
    let phrase = search::search(&conn, "\"der Begriff\"", Some("gw-12"), 5);
    assert!(!phrase.is_empty(), "短语应当有命中");

    let absent = search::search(&conn, "\"genauer Begriff\"", Some("gw-12"), 5);
    assert!(absent.is_empty(), "不存在的短语不该有命中");

    let both = search::search(&conn, "Begriff AND Sein", Some("gw-12"), 5);
    assert!(!both.is_empty());

    let prefix = search::search(&conn, "Subject*", Some("gw-12"), 5);
    assert!(!prefix.is_empty(), "前缀应当有命中");
}

#[test]
fn 章节路径带层级() {
    let Some(conn) = open() else { return };

    let path: String = conn
        .query_row(
            "SELECT path FROM section WHERE title LIKE '%Erstes Kapitel. Der Begriff%' LIMIT 1",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert!(
        path.contains("›"),
        "章节路径应当体现层级：{path}"
    );
    assert!(
        path.contains("ERSTER ABSCHNITT"),
        "章节路径应当从所属的 Abschnitt 起头：{path}"
    );
}

#[test]
fn 跨卷检索() {
    let Some(conn) = open() else { return };

    // 不限卷 —— 十六卷一起搜。
    let hits = search::search(&conn, "Aufhebung", None, 50);
    assert!(hits.len() > 5, "跨卷检索命中太少：{}", hits.len());

    // 命中应当落在不止一卷上。
    let mut volumes: Vec<String> = Vec::new();
    for hit in &hits {
        let volume: String = conn
            .query_row("SELECT work_id FROM unit WHERE id = ?1", [hit.unit_id], |r| r.get(0))
            .unwrap();
        if !volumes.contains(&volume) {
            volumes.push(volume);
        }
    }
    assert!(volumes.len() > 1, "命中全落在一卷里：{volumes:?}");
}

#[test]
fn 限定卷检索() {
    let Some(conn) = open() else { return };

    let hits = search::search(&conn, "Begriff", Some("gw-9"), 20);
    assert!(!hits.is_empty());
    for hit in &hits {
        let volume: String = conn
            .query_row("SELECT work_id FROM unit WHERE id = ?1", [hit.unit_id], |r| r.get(0))
            .unwrap();
        assert_eq!(volume, "gw-9", "限定了卷，结果却来自 {volume}");
    }
}

#[test]
fn 引用串格式() {
    let Some(conn) = open() else { return };

    let siglum: String = conn
        .query_row("SELECT siglum FROM work WHERE id = 'gw-12'", [], |r| r.get(0))
        .unwrap();
    assert_eq!(siglum, "GW 12");
}

#[test]
fn 三家版本都在库里() {
    let Some(conn) = open() else { return };

    let editions: Vec<String> = conn
        .prepare("SELECT DISTINCT edition FROM work ORDER BY edition_order")
        .unwrap()
        .query_map([], |r| r.get(0))
        .unwrap()
        .flatten()
        .collect();

    assert_eq!(editions, vec!["hegel", "fichte", "schelling"]);
}

#[test]
fn 卷目按版本和卷次排好() {
    let Some(conn) = open() else { return };

    let rows: Vec<(String, i64, i64)> = conn
        .prepare("SELECT siglum, edition_order, sort_order FROM work ORDER BY edition_order, sort_order")
        .unwrap()
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))
        .unwrap()
        .flatten()
        .collect();

    // 黑格尔在前，费希特其次，谢林最后
    assert_eq!(rows[0].0, "GW 1");
    assert_eq!(rows[rows.len() - 1].0, "SW II/4");

    // 排序键在每个版本内单调递增
    let mut last = (i64::MIN, i64::MIN);
    for (siglum, edition_order, sort_order) in &rows {
        assert!(*edition_order >= last.0, "{siglum} 的版本序回退了");
        if *edition_order == last.0 {
            assert!(*sort_order > last.1, "{siglum} 的卷序回退了");
        }
        last = (*edition_order, *sort_order);
    }
}

#[test]
fn 罗马数字的页码留住了() {
    let Some(conn) = open() else { return };

    // 费希特 SW I 的卷首页是罗马数字
    let roman: i64 = conn
        .query_row(
            "SELECT COUNT(*) FROM page WHERE work_id = 'fsw-1' AND book_page GLOB '*[IVXLC]*'",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert!(roman > 0, "费希特 SW I 里没有罗马数字页码");

    // 而且这些页确实能查出来
    let page: String = conn
        .query_row(
            "SELECT book_page FROM page WHERE work_id = 'fsw-1' AND book_page = 'V'",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(page, "V");
}

#[test]
fn 引用串用各版本自己的卷标() {
    let Some(conn) = open() else { return };

    for (work, expected) in [("gw-12", "GW 12"), ("fsw-1", "SW I"), ("sw-I-01", "SW I/1")] {
        let unit_id: i64 = conn
            .query_row(
                "SELECT id FROM unit WHERE work_id = ?1 AND kind = 'paragraph' LIMIT 1",
                [work],
                |r| r.get(0),
            )
            .unwrap();
        let citation = sshub_lib::commands::citation_of(&conn, unit_id).unwrap();
        assert!(
            citation.starts_with(expected),
            "{work} 的引用串应以 {expected} 开头，实际是 {citation}"
        );
    }
}

#[test]
fn 脚注不会互相顶掉() {
    let Some(conn) = open() else { return };

    // 脚注的 id 里带着页码（fn-135-1），只在**一卷之内**唯一。
    // 主键必须是 (work_id, id) —— 否则后建的卷会把先建的卷的脚注顶掉。
    //
    // 这个坑很隐蔽：四十一卷建下来，脚注数会少一半，而每一卷单独看
    // 都是对的。所以这里按卷核对总数。
    let totals: Vec<(String, i64)> = conn
        .prepare(
            "SELECT w.edition, COUNT(*) FROM footnote f JOIN work w ON w.id = f.work_id
             GROUP BY w.edition ORDER BY w.edition",
        )
        .unwrap()
        .query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, i64>(1)?)))
        .unwrap()
        .flatten()
        .collect();

    // 与原站各版的统计一致（见 README「与原站的对照」）
    assert_eq!(
        totals,
        vec![
            ("fichte".to_string(), 582),
            ("hegel".to_string(), 1614),
            ("schelling".to_string(), 3421),
        ]
    );
}

#[test]
fn 边注也算脚注() {
    let Some(conn) = open() else { return };

    // 边注（type="rand"）、行下注、行上注都是书里的内容，也该能查到。
    let kinds: Vec<(String, i64)> = conn
        .prepare(
            "SELECT COALESCE(place_kind, '页脚'), COUNT(*) FROM footnote
             GROUP BY place_kind ORDER BY 1",
        )
        .unwrap()
        .query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, i64>(1)?)))
        .unwrap()
        .flatten()
        .collect();

    let total: i64 = kinds.iter().map(|(_, n)| n).sum();
    assert_eq!(total, 5617, "全部脚注（含边注）");
    assert!(kinds.len() >= 3, "页脚、边注、行下注、行上注都该在：{kinds:?}");
}
