// Windows 下不要弹控制台窗口。
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    sshub_lib::run()
}
