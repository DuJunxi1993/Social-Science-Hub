//! 语料库与用户库的打开方式。
//!
//! 两个库，职责分明：
//!
//! * **语料库**（`corpus.db`）—— 只读，打包在应用资源里。它是全卷黑格尔
//!   文本，第一次启动时复制到应用数据目录，之后永远只读打开。
//! * **用户库**（`workspace.db`）—— 可写，放在应用数据目录。批注、书签、
//   个人词库、阅读进度都在这里。语料升级不影响它。

use std::fs;
use std::path::PathBuf;

use rusqlite::Connection;
use tauri::{AppHandle, Manager};

/// 语料库的版本号。改了 ETL 的产出格式就 +1，应用启动时发现版本对不上
/// 就重新复制一份资源里的语料库。
const CORPUS_VERSION: i64 = 7;

pub struct Corpus {
    conn: Connection,
}

impl Corpus {
    pub fn conn(&self) -> &Connection {
        &self.conn
    }
}

/// 把打包的语料库复制到应用数据目录（只在该做的时候做一次）。
fn ensure_corpus(app: &AppHandle) -> Result<PathBuf, String> {
    let data_dir = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("找不到应用数据目录：{e}"))?;
    fs::create_dir_all(&data_dir).map_err(|e| format!("建不了应用数据目录：{e}"))?;

    let target = data_dir.join("corpus.db");
    let stamp = data_dir.join("corpus.version");

    let current_version: i64 = fs::read_to_string(&stamp)
        .ok()
        .and_then(|s| s.trim().parse().ok())
        .unwrap_or(0);

    if current_version == CORPUS_VERSION && target.exists() {
        return Ok(target);
    }

    // 资源里的语料库：Tauri 把 `bundle.resources` 放在 resource_dir 下。
    let resource = app
        .path()
        .resource_dir()
        .map_err(|e| format!("找不到资源目录：{e}"))?;
    let source = resource.join("corpus.db");
    if !source.exists() {
        return Err(format!(
            "应用里没有语料库（{}）。请先运行 `python -m sshex build --work gw-12` 生成 data/corpus.db。",
            source.display()
        ));
    }

    // 先写临时文件再改名 —— 中途崩溃不会留下半份语料库。
    let temp = data_dir.join("corpus.db.tmp");
    fs::copy(&source, &temp).map_err(|e| format!("复制语料库失败：{e}"))?;
    fs::rename(&temp, &target).map_err(|e| format!("替换语料库失败：{e}"))?;
    fs::write(&stamp, CORPUS_VERSION.to_string())
        .map_err(|e| format!("写版本标记失败：{e}"))?;

    Ok(target)
}

/// 用户库：批注、书签、词库、阅读进度。
pub fn open_workspace(app: &AppHandle) -> Result<Connection, String> {
    let data_dir = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("找不到应用数据目录：{e}"))?;
    fs::create_dir_all(&data_dir).map_err(|e| format!("建不了应用数据目录：{e}"))?;

    let path = data_dir.join("workspace.db");
    let conn = Connection::open(&path).map_err(|e| format!("打开用户库失败：{e}"))?;
    migrate(&conn)?;
    Ok(conn)
}

/// 用户库结构的版本。
///
/// 版本变了就得重建表 —— 页码从整数变成了字符串（卷首的页是罗马数字），
/// 列的存储类型跟着变，旧数据得搬过去。
const WORKSPACE_VERSION: i64 = 2;

pub fn migrate(conn: &Connection) -> Result<(), String> {
    conn.execute_batch(
        r#"
        PRAGMA journal_mode = WAL;
        PRAGMA foreign_keys = ON;

        -- 阅读批注：挂在语料的一个单元上
        CREATE TABLE IF NOT EXISTS annotation (
            id          INTEGER PRIMARY KEY,
            work_id     TEXT NOT NULL,
            unit_id     INTEGER NOT NULL,
            book_page   TEXT,
            gw_line     INTEGER,
            quote       TEXT NOT NULL DEFAULT '',
            note        TEXT NOT NULL DEFAULT '',
            tags        TEXT NOT NULL DEFAULT '[]',
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS annotation_unit ON annotation (unit_id);

        -- 书签
        CREATE TABLE IF NOT EXISTS bookmark (
            id         INTEGER PRIMARY KEY,
            work_id    TEXT NOT NULL,
            unit_id    INTEGER NOT NULL,
            label      TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE UNIQUE INDEX IF NOT EXISTS bookmark_unit ON bookmark (unit_id);

        -- 个人术语表：德文 → 中文
        CREATE TABLE IF NOT EXISTS glossary (
            id         INTEGER PRIMARY KEY,
            term_de    TEXT NOT NULL,
            term_zh    TEXT NOT NULL DEFAULT '',
            note       TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE UNIQUE INDEX IF NOT EXISTS glossary_term ON glossary (term_de);

        -- 术语与语料位置的关联
        CREATE TABLE IF NOT EXISTS glossary_link (
            glossary_id INTEGER NOT NULL REFERENCES glossary(id) ON DELETE CASCADE,
            unit_id     INTEGER NOT NULL,
            PRIMARY KEY (glossary_id, unit_id)
        );

        -- 阅读进度
        CREATE TABLE IF NOT EXISTS progress (
            work_id     TEXT PRIMARY KEY,
            unit_id     INTEGER,
            book_page   TEXT,
            pdf_page    INTEGER,
            updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );

        -- 阅读偏好（字号、版心宽度、行距、字体、主题）
        CREATE TABLE IF NOT EXISTS setting (
            key        TEXT PRIMARY KEY,
            value      TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        "#,
    )
    .map_err(|e| format!("建用户库失败：{e}"))?;

    // 表建好了（新的或旧的都在），再按版本决定要不要重建。
    //
    // 顺序很重要：重建时要从旧表里 **SELECT** 出来搬到新表，所以旧表
    // 得先存在 —— 全新安装时上面那句 CREATE TABLE IF NOT EXISTS 已经建好了。
    let current: i64 = conn
        .query_row("PRAGMA user_version", [], |r| r.get(0))
        .map_err(|e| e.to_string())?;
    if current != WORKSPACE_VERSION {
        rebuild_workspace(conn)?;
    }
    Ok(())
}

pub fn open_corpus(app: &AppHandle) -> Result<Corpus, String> {
    let path = ensure_corpus(app)?;
    let conn = Connection::open_with_flags(
        &path,
        rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY | rusqlite::OpenFlags::SQLITE_OPEN_URI,
    )
    .map_err(|e| format!("打开语料库失败（{}）：{e}", path.display()))?;
    conn.execute_batch("PRAGMA query_only = ON;")
        .map_err(|e| format!("设置语料库只读失败：{e}"))?;
    Ok(Corpus { conn })
}

/// 语料库在磁盘上的位置 —— 供「在访达中显示」之类的功能用。
pub fn corpus_path(app: &AppHandle) -> Result<PathBuf, String> {
    ensure_corpus(app)
}

pub fn app_data_dir(app: &AppHandle) -> Result<PathBuf, String> {
    app.path()
        .app_data_dir()
        .map_err(|e| format!("找不到应用数据目录：{e}"))
}


/// 表里页码那一列叫啥。
///
/// 早先的库列名是 ``gw_page``，后来改成 ``book_page``（页码可能是罗马数字）。
/// 迁移时得看实际是哪一列。
fn page_column(conn: &Connection, table: &str) -> String {
    let sql = format!("PRAGMA table_info({table})");
    let mut stmt = match conn.prepare(&sql) {
        Ok(stmt) => stmt,
        Err(_) => return "gw_page".to_string(),
    };
    let names: Vec<String> = stmt
        .query_map([], |row| row.get::<_, String>(1))
        .map(|rows| rows.flatten().collect())
        .unwrap_or_default();
    if names.iter().any(|n| n == "book_page") {
        "book_page".to_string()
    } else {
        "gw_page".to_string()
    }
}

/// 重建用户库的用户表，把旧数据搬过去。
///
/// 只在结构版本变了的时候调用一次。批注、书签、词表、进度都留着 ——
/// 页码从整数变成字符串，用 ``CAST`` 转一下就行。
fn rebuild_workspace(conn: &Connection) -> Result<(), String> {
    let annotation_page = page_column(conn, "annotation");
    let progress_page = page_column(conn, "progress");

    let sql = r#"
        PRAGMA foreign_keys = OFF;

        -- 上一次迁移可能中途失败，留下半成品 —— 先清掉再来一遍
        DROP TABLE IF EXISTS annotation_new;
        DROP TABLE IF EXISTS bookmark_new;
        DROP TABLE IF EXISTS glossary_new;
        DROP TABLE IF EXISTS glossary_link_new;
        DROP TABLE IF EXISTS progress_new;

        -- 批注
        CREATE TABLE annotation_new (
            id          INTEGER PRIMARY KEY,
            work_id     TEXT NOT NULL,
            unit_id     INTEGER NOT NULL,
            book_page   TEXT,
            gw_line     INTEGER,
            quote       TEXT NOT NULL DEFAULT '',
            note        TEXT NOT NULL DEFAULT '',
            tags        TEXT NOT NULL DEFAULT '[]',
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );
        INSERT INTO annotation_new
            SELECT id, work_id, unit_id, CAST(ANNOTATION_PAGE AS TEXT), gw_line,
                   quote, note, tags, created_at, updated_at
            FROM annotation;
        DROP TABLE annotation;
        ALTER TABLE annotation_new RENAME TO annotation;

        -- 书签
        CREATE TABLE bookmark_new (
            id         INTEGER PRIMARY KEY,
            work_id    TEXT NOT NULL,
            unit_id    INTEGER NOT NULL,
            label      TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        INSERT INTO bookmark_new
            SELECT id, work_id, unit_id, label, created_at FROM bookmark;
        DROP TABLE bookmark;
        ALTER TABLE bookmark_new RENAME TO bookmark;

        -- 术语表
        CREATE TABLE glossary_new (
            id         INTEGER PRIMARY KEY,
            term_de    TEXT NOT NULL,
            term_zh    TEXT NOT NULL DEFAULT '',
            note       TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        INSERT INTO glossary_new
            SELECT id, term_de, term_zh, note, created_at, updated_at FROM glossary;
        DROP TABLE glossary;
        ALTER TABLE glossary_new RENAME TO glossary;

        -- 术语与语料位置的关联
        CREATE TABLE glossary_link_new (
            glossary_id INTEGER NOT NULL REFERENCES glossary(id) ON DELETE CASCADE,
            unit_id     INTEGER NOT NULL,
            PRIMARY KEY (glossary_id, unit_id)
        );
        INSERT INTO glossary_link_new SELECT glossary_id, unit_id FROM glossary_link;
        DROP TABLE glossary_link;
        ALTER TABLE glossary_link_new RENAME TO glossary_link;

        -- 阅读进度
        CREATE TABLE progress_new (
            work_id     TEXT PRIMARY KEY,
            unit_id     INTEGER,
            book_page   TEXT,
            pdf_page    INTEGER,
            updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );
        INSERT INTO progress_new
            SELECT work_id, unit_id, CAST(PROGRESS_PAGE AS TEXT), pdf_page, updated_at
            FROM progress;
        DROP TABLE progress;
        ALTER TABLE progress_new RENAME TO progress;

        -- 阅读偏好（键值表，结构没变，原样留着）
        CREATE TABLE IF NOT EXISTS setting (
            key        TEXT PRIMARY KEY,
            value      TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        PRAGMA foreign_keys = ON;
        "#;

    // 页码那一列的名字随库的版本而变，替换进去
    let sql = sql
        .replace("ANNOTATION_PAGE", &annotation_page)
        .replace("PROGRESS_PAGE", &progress_page);

    conn.execute_batch(&sql).map_err(|e| format!("重建用户库失败：{e}"))?;

    conn.execute_batch(&format!("PRAGMA user_version = {WORKSPACE_VERSION};"))
        .map_err(|e| format!("记用户库版本失败：{e}"))?;
    Ok(())
}
