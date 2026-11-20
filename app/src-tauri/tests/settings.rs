//! 阅读偏好：存进去要能原样取回来。
//!
//! 这一层是「排版」面板的地基 —— 前端把字号、版心宽度这些写成键值对，
//! 下次启动再读回来。中间隔着一层 SQLite，所以得真的过一遍数据库。

use rusqlite::Connection;

fn workspace() -> Connection {
    let conn = Connection::open_in_memory().unwrap();
    sshub_lib::db::migrate(&conn).unwrap();
    conn
}

fn set(conn: &Connection, key: &str, value: &str) {
    conn.execute(
        "INSERT INTO setting (key, value, updated_at) VALUES (?1, ?2, datetime('now'))
         ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')",
        rusqlite::params![key, value],
    )
    .unwrap();
}

fn get(conn: &Connection, key: &str) -> Option<String> {
    conn.query_row("SELECT value FROM setting WHERE key = ?1", [key], |r| r.get(0))
        .ok()
}

#[test]
fn 偏好能存能取() {
    let conn = workspace();
    set(&conn, "theme", "night");
    set(&conn, "font", "sans");
    set(&conn, "scale", "1.25");
    set(&conn, "measure", "48");
    set(&conn, "leading", "1.9");

    assert_eq!(get(&conn, "theme").as_deref(), Some("night"));
    assert_eq!(get(&conn, "font").as_deref(), Some("sans"));
    assert_eq!(get(&conn, "scale").as_deref(), Some("1.25"));
    assert_eq!(get(&conn, "measure").as_deref(), Some("48"));
    assert_eq!(get(&conn, "leading").as_deref(), Some("1.9"));
}

#[test]
fn 同一项改了会覆盖() {
    let conn = workspace();
    set(&conn, "scale", "1.0");
    set(&conn, "scale", "1.5");
    assert_eq!(get(&conn, "scale").as_deref(), Some("1.5"));
    // 覆盖而不是新增 —— 键必须唯一
    let count: i64 = conn
        .query_row("SELECT COUNT(*) FROM setting WHERE key = 'scale'", [], |r| r.get(0))
        .unwrap();
    assert_eq!(count, 1);
}

#[test]
fn 空的偏好库读出来是空的() {
    let conn = workspace();
    assert_eq!(get(&conn, "theme"), None);
    let count: i64 = conn
        .query_row("SELECT COUNT(*) FROM setting", [], |r| r.get(0))
        .unwrap();
    assert_eq!(count, 0);
}
