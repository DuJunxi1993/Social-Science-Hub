//! 德语旧正字法归一 —— 与 Python 端 `sshex.ortho` 和数字版原站
//! `assets/en/ortho.js` 同一套规则。
//!
//! 检索时只有**查询**要归一；语料那边在 ETL 阶段就归一好了，存在
//! `token` 表里。所以这里的实现只需要正确，不必快。
//!
//! 用了 `fancy-regex` 而不是 `regex`：规则表里有负向断言
//! （``(?<![sc])c(?=[aou])``），标准 `regex` 不支持回头看。
//!
//! 顺序有意义：``ni(ß|ss)→nis`` 必须排在 ``ß→ss`` 前面，否则
//! ``Verhältniß`` 变成 ``verhältniss``、``Verhältnis`` 变成 ``verhältnis``，
//! 两者再也合不到一起。

use fancy_regex::Regex;
use std::sync::OnceLock;

struct Rule {
    regex: Regex,
    replacement: &'static str,
}

fn rules() -> &'static Vec<Rule> {
    static RULES: OnceLock<Vec<Rule>> = OnceLock::new();
    RULES.get_or_init(|| {
        let specs: &[(&str, &str)] = &[
            (r"ni(?:ß|ss)(?![a-zäöü])", "nis"),
            (r"(?<![sc])c(?=[aou])", "k"),
            (r"(?<![sc])c(?=[ei])", "z"),
            (r"ey", "ei"),
            (r"ay", "ai"),
            (r"ß", "ss"),
            (r"th(?=[aeiouäöü])", "t"),
            (r"ct", "kt"),
            (r"ph", "f"),
            (r"iren\b", "ieren"),
        ];
        specs
            .iter()
            .map(|(pattern, replacement)| Rule {
                regex: Regex::new(pattern).expect("正字法规则应当能编译"),
                replacement,
            })
            .collect()
    })
}

/// 把一个词变成**检索键**：先转小写，再套用全部规则。
pub fn normalize_token(word: &str) -> String {
    let mut result = word.to_lowercase();
    for rule in rules() {
        result = rule
            .regex
            .replace_all(&result, rule.replacement)
            .into_owned();
    }
    result
}

/// 把一段文本切成词（字母或数字的极大连续段），与 FTS5 的 `unicode61` 一致。
pub fn tokenize(text: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut current = String::new();
    for ch in text.chars() {
        if ch.is_alphanumeric() {
            current.push(ch);
        } else if !current.is_empty() {
            out.push(std::mem::take(&mut current));
        }
    }
    if !current.is_empty() {
        out.push(current);
    }
    out
}

/// 同 :func:`tokenize`，但带上每个词在原文中的**字符**起止位置。
///
/// 字符（不是字节）—— ETL 那边记的偏移也是字符，两边要对得上。
pub fn tokenize_with_offsets(text: &str) -> Vec<(String, usize, usize)> {
    let mut out = Vec::new();
    let mut current = String::new();
    let mut start = 0usize;
    let mut index = 0usize;

    for ch in text.chars() {
        if ch.is_alphanumeric() {
            if current.is_empty() {
                start = index;
            }
            current.push(ch);
        } else if !current.is_empty() {
            out.push((std::mem::take(&mut current), start, index));
        }
        index += 1;
    }
    if !current.is_empty() {
        out.push((current, start, index));
    }
    out
}

/// 无规律的异体：现代写法 → 历史写法。
///
/// 第一项是现代形，其余是黑格尔时代的写法。键是**归一后**的小写形式，
/// 所以 ``Nemlich``、``nemlich``、``nämlich`` 命中同一组。
const VARIANT_GROUPS: &[&[&str]] = &[
    &["jetzt", "itzt", "izt", "jezt"],
    &["nämlich", "nemlich", "nehmlich"],
    &["gibt", "giebt"],
    &["andere", "andre"],
    &["unsere", "unsre"],
    &["ungeachtet", "ohngeachtet"],
    &["sowohl", "sowol"],
];

/// 与 ``word`` 同组的其它写法（不含 ``word`` 本身）。
pub fn variants(word: &str) -> Vec<String> {
    let key = normalize_token(word);
    for group in VARIANT_GROUPS {
        if group.iter().any(|v| normalize_token(v) == key) {
            return group
                .iter()
                .filter(|v| normalize_token(v) != key)
                .map(|v| v.to_lowercase())
                .collect();
        }
    }
    Vec::new()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn regeln() {
        assert_eq!(normalize_token("Seyn"), "sein");
        assert_eq!(normalize_token("daß"), "dass");
        assert_eq!(normalize_token("Proceß"), "prozess");
        assert_eq!(normalize_token("Verhältniß"), "verhältnis");
        assert_eq!(normalize_token("Cultur"), "kultur");
    }

    #[test]
    fn gross_und_klein() {
        assert_eq!(normalize_token("Cultur"), normalize_token("Kultur"));
        assert_eq!(normalize_token("Seyn"), normalize_token("sein"));
    }

    #[test]
    fn varianten() {
        assert!(variants("jetzt").contains(&"itzt".to_string()));
        assert!(variants("nämlich").contains(&"nemlich".to_string()));
        assert!(variants("unbekannt").is_empty());
    }

    #[test]
    fn tokenizer() {
        assert_eq!(tokenize("Der Begriff."), vec!["Der", "Begriff"]);
    }
}
