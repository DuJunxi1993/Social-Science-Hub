//! 社科研读 · 离线本地应用
//!
//! 底本是 *Digital Hegel Edition* 的黑格尔《Gesammelte Werke》
//! （Giuliano Infantino 编纂，CC BY 4.0；黑格尔原文属公有领域）。
//!
//! 应用完全离线：语料库打包在资源里，启动时复制到应用数据目录；
//! 用户自己的批注、书签、术语表存在旁边的另一个库里。

pub mod commands;
pub mod db;
pub mod ortho;
pub mod search;

use tauri::Manager;

/// 启动应用。
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            let handle = app.handle().clone();
            let state = commands::init(&handle)?;
            app.manage(state);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::list_works,
            commands::get_sections,
            commands::list_pages,
            commands::get_page_units,
            commands::get_units,
            commands::get_unit,
            commands::find_by_book_page,
            commands::get_footnotes,
            commands::search_corpus,
            commands::citation,
            commands::list_annotations,
            commands::save_annotation,
            commands::delete_annotation,
            commands::list_bookmarks,
            commands::add_bookmark,
            commands::remove_bookmark,
            commands::list_glossary,
            commands::save_glossary,
            commands::delete_glossary,
            commands::get_progress,
            commands::set_progress,
            commands::get_settings,
            commands::set_setting,
            commands::corpus_location,
        ])
        .run(tauri::generate_context!())
        .expect("应用启动失败");
}
