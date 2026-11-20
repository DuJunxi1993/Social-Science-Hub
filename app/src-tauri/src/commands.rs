//! 前端能调的命令。
//!
//! 语料相关的命令只读语料库；用户数据相关的命令读写用户库。
//! 两边不混 —— 语料是别人的成果（CC BY 4.0），用户的东西是自己的。

use std::sync::Mutex;

use rusqlite::Connection;
use serde::Serialize;
use tauri::State;

use crate::db::{open_corpus, open_workspace, Corpus};
use crate::search::{self, Hit};

pub struct AppState {
    pub corpus: Mutex<Option<Corpus>>,
    pub workspace: Mutex<Connection>,
}

impl AppState {
    pub fn new(workspace: Connection) -> Self {
        Self {
            corpus: Mutex::new(None),
            workspace: Mutex::new(workspace),
        }
    }
}

fn with_corpus<T>(
    state: &State<'_, AppState>,
    f: impl FnOnce(&Connection) -> Result<T, String>,
) -> Result<T, String> {
    let guard = state.corpus.lock().map_err(|_| "语料库锁坏了".to_string())?;
    let corpus = guard.as_ref().ok_or("语料库还没准备好".to_string())?;
    f(corpus.conn())
}

// ── 语料 ────────────────────────────────────────────────────────────────

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Work {
    pub id: String,
    /// 版本：hegel / fichte / schelling
    pub edition: String,
    /// 作者（德文姓名）
    pub author: Option<String>,
    pub siglum: String,
    pub title: String,
    pub short_title: Option<String>,
    pub source_title: Option<String>,
    pub series: Option<String>,
    pub volume_number: Option<String>,
    pub license_attribution: Option<String>,
    pub license_database: Option<String>,
    pub license_url: Option<String>,
    pub source_url: Option<String>,
}

#[tauri::command]
pub fn list_works(state: State<'_, AppState>) -> Result<Vec<Work>, String> {
    with_corpus(&state, |conn| {
        // 按**卷号数字**排，不是按字符串 —— 否则 gw-11 会排在 gw-3 前面。
        // 这一版里 GW 2、10、13、14、16 并不存在（编者版未出或未备），
        // 所以卷号本来就不连续。
        let mut stmt = conn
            .prepare(
                // 先按版本排（黑格尔 → 费希特 → 谢林），版本内按卷次排。
                //
                // 黑格尔这一版的卷号是 „GW 12“ 这种，剥掉前缀转数字就能排；
                // 费希特是 „SW I“、„NW III“，谢林是 „SW I/1“、„SW II/4“ ——
                // 得按版本分别排。
                "SELECT id, edition, author, siglum, title, short_title, source_title,
                        series, volume_number, license_attribution, license_database,
                        license_url, source_url
                 FROM work
                 ORDER BY edition_order, sort_order",
            )
            .map_err(|e| e.to_string())?;
        let rows = stmt
            .query_map([], |row| {
                Ok(Work {
                    id: row.get(0)?,
                    edition: row.get(1)?,
                    author: row.get(2)?,
                    siglum: row.get(3)?,
                    title: row.get(4)?,
                    short_title: row.get(5)?,
                    source_title: row.get(6)?,
                    series: row.get(7)?,
                    volume_number: row.get(8)?,
                    license_attribution: row.get(9)?,
                    license_database: row.get(10)?,
                    license_url: row.get(11)?,
                    source_url: row.get(12)?,
                })
            })
            .map_err(|e| e.to_string())?;
        rows.collect::<Result<Vec<_>, _>>().map_err(|e| e.to_string())
    })
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Section {
    pub id: i64,
    pub ord: i64,
    pub level: i64,
    pub title: String,
    pub path: String,
    pub book_page: Option<String>,
    pub pdf_page: Option<i64>,
    pub unit_id: Option<i64>,
}

#[tauri::command]
pub fn get_sections(
    work_id: String,
    state: State<'_, AppState>,
) -> Result<Vec<Section>, String> {
    with_corpus(&state, |conn| {
        let mut stmt = conn
            .prepare(
                "SELECT id, ord, level, title, path, book_page, pdf_page, unit_id
                 FROM section WHERE work_id = ?1 ORDER BY ord",
            )
            .map_err(|e| e.to_string())?;
        let rows = stmt
            .query_map([&work_id], |row| {
                Ok(Section {
                    id: row.get(0)?,
                    ord: row.get(1)?,
                    level: row.get(2)?,
                    title: row.get(3)?,
                    path: row.get(4)?,
                    book_page: row.get(5)?,
                    pdf_page: row.get(6)?,
                    unit_id: row.get(7)?,
                })
            })
            .map_err(|e| e.to_string())?;
        rows.collect::<Result<Vec<_>, _>>().map_err(|e| e.to_string())
    })
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Unit {
    pub id: i64,
    pub ord: i64,
    pub pdf_page: i64,
    pub book_page: Option<String>,
    pub section_id: Option<i64>,
    pub kind: String,
    pub text: String,
    pub spans: serde_json::Value,
    pub refs: serde_json::Value,
    pub lines: serde_json::Value,
    pub line_map: serde_json::Value,
    pub meta: serde_json::Value,
}

fn row_to_unit(row: &rusqlite::Row<'_>) -> rusqlite::Result<Unit> {
    Ok(Unit {
        id: row.get("id")?,
        ord: row.get("ord")?,
        pdf_page: row.get("pdf_page")?,
        book_page: row.get("book_page")?,
        section_id: row.get("section_id")?,
        kind: row.get("kind")?,
        text: row.get("text")?,
        spans: serde_json::from_str(&row.get::<_, String>("spans")?).unwrap_or_default(),
        refs: serde_json::from_str(&row.get::<_, String>("refs")?).unwrap_or_default(),
        lines: serde_json::from_str(&row.get::<_, String>("lines")?).unwrap_or_default(),
        line_map: serde_json::from_str(&row.get::<_, String>("line_map")?).unwrap_or_default(),
        meta: serde_json::from_str(&row.get::<_, String>("meta")?).unwrap_or_default(),
    })
}

/// 取一整个印刷页上的单元。
#[tauri::command]
pub fn get_page_units(
    work_id: String,
    pdf_page: i64,
    state: State<'_, AppState>,
) -> Result<Vec<Unit>, String> {
    with_corpus(&state, |conn| {
        let mut stmt = conn
            .prepare(
                "SELECT * FROM unit
                 WHERE work_id = ?1 AND pdf_page = ?2
                 ORDER BY ord",
            )
            .map_err(|e| e.to_string())?;
        let rows = stmt
            .query_map(rusqlite::params![&work_id, pdf_page], row_to_unit)
            .map_err(|e| e.to_string())?;
        rows.collect::<Result<Vec<_>, _>>().map_err(|e| e.to_string())
    })
}

/// 取一段连续的单元（按 ord 顺序），用于前后翻页。
#[tauri::command]
pub fn get_units(
    work_id: String,
    from_ord: i64,
    count: i64,
    state: State<'_, AppState>,
) -> Result<Vec<Unit>, String> {
    with_corpus(&state, |conn| {
        let mut stmt = conn
            .prepare(
                "SELECT * FROM unit
                 WHERE work_id = ?1 AND ord >= ?2
                 ORDER BY ord LIMIT ?3",
            )
            .map_err(|e| e.to_string())?;
        let rows = stmt
            .query_map(rusqlite::params![&work_id, from_ord, count], row_to_unit)
            .map_err(|e| e.to_string())?;
        rows.collect::<Result<Vec<_>, _>>().map_err(|e| e.to_string())
    })
}

#[tauri::command]
pub fn get_unit(unit_id: i64, state: State<'_, AppState>) -> Result<Unit, String> {
    with_corpus(&state, |conn| {
        let mut stmt = conn
            .prepare("SELECT * FROM unit WHERE id = ?1")
            .map_err(|e| e.to_string())?;
        let mut rows = stmt
            .query_map([unit_id], row_to_unit)
            .map_err(|e| e.to_string())?;
        rows.next()
            .transpose()
            .map_err(|e| e.to_string())?
            .ok_or_else(|| format!("没有这个单元：{unit_id}"))
    })
}

/// 按 GW 页码找单元 —— 工具条上的「跳到 GW 第几页」用。
#[tauri::command]
pub fn find_by_book_page(
    work_id: String,
    book_page: String,
    state: State<'_, AppState>,
) -> Result<Option<Unit>, String> {
    with_corpus(&state, |conn| {
        let mut stmt = conn
            .prepare(
                "SELECT * FROM unit
                 WHERE work_id = ?1 AND book_page = ?2
                 ORDER BY ord LIMIT 1",
            )
            .map_err(|e| e.to_string())?;
        let mut rows = stmt
            .query_map(rusqlite::params![&work_id, book_page], row_to_unit)
            .map_err(|e| e.to_string())?;
        Ok(rows.next().transpose().map_err(|e| e.to_string())?)
    })
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PageInfo {
    pub pdf_page: i64,
    pub book_page: Option<String>,
    pub page_kind: String,
    pub has_apparatus: bool,
    pub running_header: String,
    pub signature: String,
}

/// 一卷的全部页（含书名页、目录页）。翻页与页眉都靠它。
#[tauri::command]
pub fn list_pages(work_id: String, state: State<'_, AppState>) -> Result<Vec<PageInfo>, String> {
    with_corpus(&state, |conn| {
        let mut stmt = conn
            .prepare(
                "SELECT pdf_page, book_page, page_kind, has_apparatus, running_header, signature
                 FROM page WHERE work_id = ?1 ORDER BY pdf_page",
            )
            .map_err(|e| e.to_string())?;
        let rows = stmt
            .query_map([&work_id], |row| {
                Ok(PageInfo {
                    pdf_page: row.get(0)?,
                    book_page: row.get(1)?,
                    page_kind: row.get(2)?,
                    has_apparatus: row.get(3)?,
                    running_header: row.get(4)?,
                    signature: row.get(5)?,
                })
            })
            .map_err(|e| e.to_string())?;
        rows.collect::<Result<Vec<_>, _>>().map_err(|e| e.to_string())
    })
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Footnote {
    pub id: String,
    pub unit_id: Option<i64>,
    pub part: Option<i64>,
    pub marker: Option<String>,
    pub anchor_gw_line: Option<i64>,
    pub book_page: Option<String>,
    pub gw_line: Option<i64>,
    pub text: String,
    pub spans: serde_json::Value,
}

#[tauri::command]
pub fn get_footnotes(
    work_id: String,
    state: State<'_, AppState>,
) -> Result<Vec<Footnote>, String> {
    with_corpus(&state, |conn| {
        let mut stmt = conn
            .prepare(
                "SELECT id, unit_id, part, marker, anchor_gw_line, book_page, gw_line,
                        text, spans
                 FROM footnote WHERE work_id = ?1 ORDER BY book_page, gw_line",
            )
            .map_err(|e| e.to_string())?;
        let rows = stmt
            .query_map([&work_id], |row| {
                Ok(Footnote {
                    id: row.get(0)?,
                    unit_id: row.get(1)?,
                    part: row.get(2)?,
                    marker: row.get(3)?,
                    anchor_gw_line: row.get(4)?,
                    book_page: row.get(5)?,
                    gw_line: row.get(6)?,
                    text: row.get(7)?,
                    spans: serde_json::from_str(&row.get::<_, String>("spans")?).unwrap_or_default(),
                })
            })
            .map_err(|e| e.to_string())?;
        rows.collect::<Result<Vec<_>, _>>().map_err(|e| e.to_string())
    })
}

#[tauri::command]
pub fn search_corpus(
    query: String,
    work_id: Option<String>,
    limit: Option<i64>,
    state: State<'_, AppState>,
) -> Result<Vec<Hit>, String> {
    with_corpus(&state, |conn| {
        Ok(search::search(
            conn,
            &query,
            work_id.as_deref(),
            limit.unwrap_or(50).max(1) as usize,
        ))
    })
}

/// 规范的引用串：``GW 12, 241.36``、``SW I, 29.12``。
#[tauri::command]
pub fn citation(unit_id: i64, state: State<'_, AppState>) -> Result<String, String> {
    with_corpus(&state, |conn| citation_of(conn, unit_id))
}

/// 引用串的核心逻辑（抽出来好测试）。
pub fn citation_of(conn: &rusqlite::Connection, unit_id: i64) -> Result<String, String> {
    {
        let mut stmt = conn
            .prepare(
                "SELECT w.siglum, u.book_page, u.lines
                 FROM unit u JOIN work w ON w.id = u.work_id
                 WHERE u.id = ?1",
            )
            .map_err(|e| e.to_string())?;
        let mut rows = stmt.query_map([unit_id], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, Option<String>>(1)?,
                row.get::<_, String>(2)?,
            ))
        })
        .map_err(|e| e.to_string())?;
        let (siglum, book_page, lines) = rows
            .next()
            .transpose()
            .map_err(|e| e.to_string())?
            .ok_or_else(|| "没有这个单元".to_string())?;
        let first_line: Option<i64> = serde_json::from_str::<serde_json::Value>(&lines)
            .ok()
            .and_then(|v| v.get(0)?.get("n")?.as_i64());
        match (book_page, first_line) {
            (Some(page), Some(line)) => Ok(format!("{siglum}, {page}.{line}")),
            (Some(page), None) => Ok(format!("{siglum}, {page}")),
            _ => Ok(siglum),
        }
    }
}

// ── 用户数据 ────────────────────────────────────────────────────────────

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Annotation {
    pub id: i64,
    pub work_id: String,
    pub unit_id: i64,
    pub book_page: Option<String>,
    pub gw_line: Option<i64>,
    pub quote: String,
    pub note: String,
    pub tags: serde_json::Value,
    pub created_at: String,
    pub updated_at: String,
}

#[tauri::command]
pub fn list_annotations(
    work_id: Option<String>,
    state: State<'_, AppState>,
) -> Result<Vec<Annotation>, String> {
    let conn = state.workspace.lock().map_err(|_| "用户库锁坏了".to_string())?;
    let (sql, params): (&str, Vec<Box<dyn rusqlite::ToSql>>) = match &work_id {
        Some(_) => (
            "SELECT id, work_id, unit_id, book_page, gw_line, quote, note, tags,
                    created_at, updated_at
             FROM annotation WHERE work_id = ?1 ORDER BY book_page, gw_line",
            vec![Box::new(work_id.clone().unwrap())],
        ),
        None => (
            "SELECT id, work_id, unit_id, book_page, gw_line, quote, note, tags,
                    created_at, updated_at
             FROM annotation ORDER BY updated_at DESC",
            vec![],
        ),
    };
    let mut stmt = conn.prepare(sql).map_err(|e| e.to_string())?;
    let refs: Vec<&dyn rusqlite::ToSql> = params.iter().map(|b| b.as_ref()).collect();
    let rows = stmt
        .query_map(refs.as_slice(), |row| {
            Ok(Annotation {
                id: row.get(0)?,
                work_id: row.get(1)?,
                unit_id: row.get(2)?,
                book_page: row.get(3)?,
                gw_line: row.get(4)?,
                quote: row.get(5)?,
                note: row.get(6)?,
                tags: serde_json::from_str(&row.get::<_, String>(7)?).unwrap_or_default(),
                created_at: row.get(8)?,
                updated_at: row.get(9)?,
            })
        })
        .map_err(|e| e.to_string())?;
    rows.collect::<Result<Vec<_>, _>>().map_err(|e| e.to_string())
}

#[derive(serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AnnotationInput {
    pub work_id: String,
    pub unit_id: i64,
    pub book_page: Option<String>,
    pub gw_line: Option<i64>,
    #[serde(default)]
    pub quote: String,
    #[serde(default)]
    pub note: String,
    #[serde(default)]
    pub tags: Vec<String>,
    /// 有 id 就是改，没有就是新建
    #[serde(default)]
    pub id: Option<i64>,
}

#[tauri::command]
pub fn save_annotation(
    input: AnnotationInput,
    state: State<'_, AppState>,
) -> Result<i64, String> {
    let conn = state.workspace.lock().map_err(|_| "用户库锁坏了".to_string())?;
    let tags = serde_json::to_string(&input.tags).unwrap_or_else(|_| "[]".into());
    match input.id {
        Some(id) => {
            conn.execute(
                "UPDATE annotation
                 SET quote = ?2, note = ?3, tags = ?4, book_page = ?5, gw_line = ?6,
                     updated_at = datetime('now')
                 WHERE id = ?1",
                rusqlite::params![
                    id,
                    input.quote,
                    input.note,
                    tags,
                    input.book_page,
                    input.gw_line
                ],
            )
            .map_err(|e| e.to_string())?;
            Ok(id)
        }
        None => {
            conn.execute(
                "INSERT INTO annotation (work_id, unit_id, book_page, gw_line, quote, note, tags)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
                rusqlite::params![
                    input.work_id,
                    input.unit_id,
                    input.book_page,
                    input.gw_line,
                    input.quote,
                    input.note,
                    tags
                ],
            )
            .map_err(|e| e.to_string())?;
            Ok(conn.last_insert_rowid())
        }
    }
}

#[tauri::command]
pub fn delete_annotation(id: i64, state: State<'_, AppState>) -> Result<(), String> {
    let conn = state.workspace.lock().map_err(|_| "用户库锁坏了".to_string())?;
    conn.execute("DELETE FROM annotation WHERE id = ?1", [id])
        .map_err(|e| e.to_string())?;
    Ok(())
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Bookmark {
    pub id: i64,
    pub work_id: String,
    pub unit_id: i64,
    pub label: String,
    pub created_at: String,
}

#[tauri::command]
pub fn list_bookmarks(state: State<'_, AppState>) -> Result<Vec<Bookmark>, String> {
    let conn = state.workspace.lock().map_err(|_| "用户库锁坏了".to_string())?;
    let mut stmt = conn
        .prepare("SELECT id, work_id, unit_id, label, created_at FROM bookmark ORDER BY created_at")
        .map_err(|e| e.to_string())?;
    let rows = stmt
        .query_map([], |row| {
            Ok(Bookmark {
                id: row.get(0)?,
                work_id: row.get(1)?,
                unit_id: row.get(2)?,
                label: row.get(3)?,
                created_at: row.get(4)?,
            })
        })
        .map_err(|e| e.to_string())?;
    rows.collect::<Result<Vec<_>, _>>().map_err(|e| e.to_string())
}

#[tauri::command]
pub fn add_bookmark(
    work_id: String,
    unit_id: i64,
    label: String,
    state: State<'_, AppState>,
) -> Result<(), String> {
    let conn = state.workspace.lock().map_err(|_| "用户库锁坏了".to_string())?;
    conn.execute(
        "INSERT OR REPLACE INTO bookmark (work_id, unit_id, label, created_at)
         VALUES (?1, ?2, ?3, datetime('now'))",
        rusqlite::params![work_id, unit_id, label],
    )
    .map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
pub fn remove_bookmark(unit_id: i64, state: State<'_, AppState>) -> Result<(), String> {
    let conn = state.workspace.lock().map_err(|_| "用户库锁坏了".to_string())?;
    conn.execute("DELETE FROM bookmark WHERE unit_id = ?1", [unit_id])
        .map_err(|e| e.to_string())?;
    Ok(())
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct GlossaryEntry {
    pub id: i64,
    pub term_de: String,
    pub term_zh: String,
    pub note: String,
    pub created_at: String,
    pub updated_at: String,
}

#[tauri::command]
pub fn list_glossary(state: State<'_, AppState>) -> Result<Vec<GlossaryEntry>, String> {
    let conn = state.workspace.lock().map_err(|_| "用户库锁坏了".to_string())?;
    let mut stmt = conn
        .prepare(
            "SELECT id, term_de, term_zh, note, created_at, updated_at
             FROM glossary ORDER BY term_de",
        )
        .map_err(|e| e.to_string())?;
    let rows = stmt
        .query_map([], |row| {
            Ok(GlossaryEntry {
                id: row.get(0)?,
                term_de: row.get(1)?,
                term_zh: row.get(2)?,
                note: row.get(3)?,
                created_at: row.get(4)?,
                updated_at: row.get(5)?,
            })
        })
        .map_err(|e| e.to_string())?;
    rows.collect::<Result<Vec<_>, _>>().map_err(|e| e.to_string())
}

#[derive(serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GlossaryInput {
    pub term_de: String,
    #[serde(default)]
    pub term_zh: String,
    #[serde(default)]
    pub note: String,
    #[serde(default)]
    pub id: Option<i64>,
}

#[tauri::command]
pub fn save_glossary(
    input: GlossaryInput,
    state: State<'_, AppState>,
) -> Result<i64, String> {
    let conn = state.workspace.lock().map_err(|_| "用户库锁坏了".to_string())?;
    match input.id {
        Some(id) => {
            conn.execute(
                "UPDATE glossary SET term_de = ?2, term_zh = ?3, note = ?4,
                        updated_at = datetime('now')
                 WHERE id = ?1",
                rusqlite::params![id, input.term_de, input.term_zh, input.note],
            )
            .map_err(|e| e.to_string())?;
            Ok(id)
        }
        None => {
            conn.execute(
                "INSERT INTO glossary (term_de, term_zh, note)
                 VALUES (?1, ?2, ?3)
                 ON CONFLICT(term_de) DO UPDATE SET
                     term_zh = excluded.term_zh, note = excluded.note,
                     updated_at = datetime('now')",
                rusqlite::params![input.term_de, input.term_zh, input.note],
            )
            .map_err(|e| e.to_string())?;
            Ok(conn.last_insert_rowid())
        }
    }
}

#[tauri::command]
pub fn delete_glossary(id: i64, state: State<'_, AppState>) -> Result<(), String> {
    let conn = state.workspace.lock().map_err(|_| "用户库锁坏了".to_string())?;
    conn.execute("DELETE FROM glossary WHERE id = ?1", [id])
        .map_err(|e| e.to_string())?;
    Ok(())
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Progress {
    pub work_id: String,
    pub unit_id: Option<i64>,
    pub book_page: Option<String>,
    pub pdf_page: Option<i64>,
}

#[tauri::command]
pub fn get_progress(work_id: String, state: State<'_, AppState>) -> Result<Option<Progress>, String> {
    let conn = state.workspace.lock().map_err(|_| "用户库锁坏了".to_string())?;
    let mut stmt = conn
        .prepare("SELECT work_id, unit_id, book_page, pdf_page FROM progress WHERE work_id = ?1")
        .map_err(|e| e.to_string())?;
    let mut rows = stmt.query_map([&work_id], |row| {
        Ok(Progress {
            work_id: row.get(0)?,
            unit_id: row.get(1)?,
            book_page: row.get(2)?,
            pdf_page: row.get(3)?,
        })
    })
    .map_err(|e| e.to_string())?;
    Ok(rows.next().transpose().map_err(|e| e.to_string())?)
}

#[tauri::command]
pub fn set_progress(
    work_id: String,
    unit_id: Option<i64>,
    book_page: Option<String>,
    pdf_page: Option<i64>,
    state: State<'_, AppState>,
) -> Result<(), String> {
    let conn = state.workspace.lock().map_err(|_| "用户库锁坏了".to_string())?;
    conn.execute(
        "INSERT INTO progress (work_id, unit_id, book_page, pdf_page, updated_at)
         VALUES (?1, ?2, ?3, ?4, datetime('now'))
         ON CONFLICT(work_id) DO UPDATE SET
             unit_id = excluded.unit_id, book_page = excluded.book_page,
             pdf_page = excluded.pdf_page, updated_at = datetime('now')",
        rusqlite::params![work_id, unit_id, book_page, pdf_page],
    )
    .map_err(|e| e.to_string())?;
    Ok(())
}

/// 语料库在磁盘上的位置。
#[tauri::command]
pub fn corpus_location(app: tauri::AppHandle) -> Result<String, String> {
    crate::db::corpus_path(&app).map(|p| p.display().to_string())
}

/// 全部阅读偏好。
///
/// 存成一张键值表（而不是几列），前端加一项偏好时后端不用改表结构。
#[derive(Debug, Default, Clone, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Settings {
    pub theme: Option<String>,
    pub font: Option<String>,
    pub scale: Option<f64>,
    pub measure: Option<f64>,
    pub leading: Option<f64>,
}

#[tauri::command]
pub fn get_settings(state: State<'_, AppState>) -> Result<Settings, String> {
    let conn = state.workspace.lock().map_err(|_| "用户库锁坏了".to_string())?;
    let mut stmt = conn
        .prepare("SELECT key, value FROM setting")
        .map_err(|e| e.to_string())?;
    let mut rows = stmt
        .query_map([], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
        })
        .map_err(|e| e.to_string())?;

    let mut out = Settings::default();
    while let Some(row) = rows.next() {
        let (key, value) = row.map_err(|e| e.to_string())?;
        let number = || value.parse::<f64>().ok();
        match key.as_str() {
            "theme" => out.theme = Some(value),
            "font" => out.font = Some(value),
            "scale" => out.scale = number(),
            "measure" => out.measure = number(),
            "leading" => out.leading = number(),
            _ => {}
        }
    }
    Ok(out)
}

#[tauri::command]
pub fn set_setting(
    key: String,
    value: String,
    state: State<'_, AppState>,
) -> Result<(), String> {
    let conn = state.workspace.lock().map_err(|_| "用户库锁坏了".to_string())?;
    conn.execute(
        "INSERT INTO setting (key, value, updated_at) VALUES (?1, ?2, datetime('now'))
         ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')",
        rusqlite::params![key, value],
    )
    .map_err(|e| e.to_string())?;
    Ok(())
}

pub fn init(app: &tauri::AppHandle) -> Result<AppState, String> {
    let workspace = open_workspace(app)?;
    let corpus = open_corpus(app)?;
    Ok(AppState {
        corpus: Mutex::new(Some(corpus)),
        workspace: Mutex::new(workspace),
    })
}
