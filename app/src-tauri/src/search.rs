//! 查询解析与检索。
//!
//! 查询先解析成 **FTS5 表达式**与**高亮词表**两样东西：
//!
//! * FTS5 表达式负责「哪些单元命中」—— 快，用的是归一后的词表。
//! * 高亮词表负责「命中词的原文位置」—— 慢一点，但拿的是**原文**，
//!   所以屏幕上显示的仍然是黑格尔 1816 年的拼写。
//!
//! 支持：``a b``（隐含 AND）、``AND`` / ``OR`` / ``NOT``、``"短语"``、
//! ``词*``（前缀）、``NEAR``（邻近）、``=词``（精确，不展开异体）。

use crate::ortho::{normalize_token, variants};
use rusqlite::Connection;
use serde::Serialize;

#[derive(Debug, Clone)]
pub struct Query {
    /// 交给 FTS5 的表达式
    pub fts: String,
    /// 参与高亮的归一词（精确匹配）
    pub terms: Vec<String>,
    /// 参与高亮的前缀词（``词*``）
    pub prefix_terms: Vec<String>,
}

/// 把用户输入拆成记号：引号里的短语算一个，括号独立，其余按空白切。
fn split_tokens(query: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut current = String::new();
    let mut in_quote = false;

    for ch in query.chars() {
        match ch {
            '"' => {
                if in_quote {
                    out.push(format!("\"{current}\""));
                    current.clear();
                } else {
                    if !current.is_empty() {
                        out.push(std::mem::take(&mut current));
                    }
                    in_quote = true;
                }
                current.push('"');
            }
            '(' | ')' if !in_quote => {
                if !current.is_empty() {
                    out.push(std::mem::take(&mut current));
                }
                out.push(ch.to_string());
            }
            c if c.is_whitespace() && !in_quote => {
                if !current.is_empty() {
                    out.push(std::mem::take(&mut current));
                }
            }
            _ => current.push(ch),
        }
    }
    if !current.is_empty() {
        out.push(current);
    }
    out
}

fn quote_literal(term: &str) -> String {
    format!("\"{}\"", term.replace('"', "\"\""))
}

/// 解析查询。
pub fn parse(query: &str) -> Query {
    let mut parser = Parser {
        tokens: split_tokens(query),
        pos: 0,
        terms: Vec::new(),
        prefix_terms: Vec::new(),
    };
    let fts = parser.parse_or();
    Query {
        fts,
        terms: parser.terms,
        prefix_terms: parser.prefix_terms,
    }
}

/// 递归下降的查询解析器。
///
/// FTS5 的 ``NOT`` 是**二元**运算符（``A NOT B``），所以它跟 ``AND`` 一样
/// 在同一层处理，不能当成前缀。
struct Parser {
    tokens: Vec<String>,
    pos: usize,
    terms: Vec<String>,
    prefix_terms: Vec<String>,
}

impl Parser {
    fn peek(&self) -> Option<&str> {
        self.tokens.get(self.pos).map(|s| s.as_str())
    }

    fn push_term(&mut self, word: &str) {
        if !word.is_empty() && !self.terms.iter().any(|t| t == word) {
            self.terms.push(word.to_string());
        }
    }

    fn push_prefix_term(&mut self, word: &str) {
        if !word.is_empty() && !self.prefix_terms.iter().any(|t| t == word) {
            self.prefix_terms.push(word.to_string());
        }
    }

    /// or_expr := and_expr (OR and_expr)*
    fn parse_or(&mut self) -> String {
        let mut left = self.parse_and();
        if left.is_empty() {
            return String::new();
        }
        while self.peek().map(|t| t.eq_ignore_ascii_case("OR")).unwrap_or(false) {
            self.pos += 1;
            let right = self.parse_and();
            if right.is_empty() {
                break;
            }
            left = format!("({left} OR {right})");
        }
        left
    }

    /// and_expr := atom ((AND | NOT)? atom)*
    fn parse_and(&mut self) -> String {
        let mut left = self.parse_atom();
        if left.is_empty() {
            return String::new();
        }
        loop {
            let Some(token) = self.peek() else { break };
            if token == ")" {
                break;
            }
            if token.eq_ignore_ascii_case("OR") {
                break;
            }
            let operator = if token.eq_ignore_ascii_case("AND") {
                self.pos += 1;
                "AND"
            } else if token.eq_ignore_ascii_case("NOT") {
                self.pos += 1;
                "NOT"
            } else {
                "AND"
            };
            let right = self.parse_atom();
            if right.is_empty() {
                break;
            }
            left = format!("({left} {operator} {right})");
        }
        left
    }

    /// atom := '(' or_expr ')' | "短语" | 词
    fn parse_atom(&mut self) -> String {
        let Some(token) = self.tokens.get(self.pos).cloned() else {
            return String::new();
        };

        if token == "(" {
            self.pos += 1;
            let inner = self.parse_or();
            if self.peek() == Some(")") {
                self.pos += 1;
            }
            return if inner.is_empty() {
                String::new()
            } else {
                format!("({inner})")
            };
        }

        if token.starts_with('"') {
            let phrase = token.trim_matches('"');
            let words: Vec<String> = phrase
                .split(|c: char| !c.is_alphanumeric())
                .filter(|s| !s.is_empty())
                .map(normalize_token)
                .collect();
            self.pos += 1;
            if words.is_empty() {
                return String::new();
            }
            for word in &words {
                self.push_term(word);
            }
            return quote_literal(&words.join(" "));
        }

        // 普通词
        self.pos += 1;
        let exact = token.starts_with('=');
        let raw = token.trim_start_matches('=');
        // `*` 与 `?` 都按前缀处理：FTS5 不支持单字符通配，但
        // `Begrif?` 想找的是 „Begriff“ 这类词 —— 拿问号之前的部分
        // 当前缀，恰好覆盖得到。
        let prefix = raw.ends_with('*') || raw.contains('?');
        let stem = raw.trim_end_matches('*');
        let stem = stem.split('?').next().unwrap_or(stem);

        let word = normalize_token(stem);
        if word.is_empty() {
            return String::new();
        }

        let mut forms = vec![word.clone()];
        if !exact {
            for variant in variants(&word) {
                let normalized = normalize_token(&variant);
                if !forms.contains(&normalized) {
                    forms.push(normalized);
                }
            }
        }

        if prefix {
            for form in &forms {
                self.push_prefix_term(form);
            }
        } else {
            for form in &forms {
                self.push_term(form);
            }
        }

        if prefix {
            format!(
                "({})",
                forms
                    .iter()
                    .map(|f| format!("{}*", quote_literal(f)))
                    .collect::<Vec<_>>()
                    .join(" OR ")
            )
        } else {
            format!(
                "({})",
                forms
                    .iter()
                    .map(|f| quote_literal(f))
                    .collect::<Vec<_>>()
                    .join(" OR ")
            )
        }
    }
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Hit {
    pub unit_id: i64,
    /// 命中所在的卷（跨卷检索时必须告诉用户是哪一卷）
    pub work_id: String,
    pub siglum: String,
    pub book_page: Option<String>,
    pub gw_line: Option<i64>,
    pub pdf_page: i64,
    pub section: String,
    pub snippet: String,
    /// 命中词在 ``snippet`` 中的区间，供前端高亮
    pub matches: Vec<(usize, usize)>,
    pub score: f64,
    pub kind: String,
}

/// 在语料库里检索。
pub fn search(
    conn: &Connection,
    query: &str,
    work_id: Option<&str>,
    limit: usize,
) -> Vec<Hit> {
    let parsed = parse(query);
    if parsed.fts.is_empty() {
        return Vec::new();
    }

    // 两种 SQL 分开写：FTS5 的参数编号不能有空洞。
    let base = "SELECT f.rowid AS unit_id, bm25(unit_fts) AS score,
                       u.book_page, u.pdf_page, u.kind, u.text, u.line_map,
                       COALESCE(s.path, '') AS section
                FROM unit_fts f
                JOIN unit u ON u.id = f.rowid
                JOIN work w ON w.id = u.work_id
                LEFT JOIN section s ON s.id = u.section_id
                WHERE unit_fts MATCH ?1";
    let bound_limit = (limit * 3) as i64;

    let mut stmt = match work_id {
        Some(_work) => match conn.prepare(&format!(
            "{base} AND u.work_id = ?2 ORDER BY score LIMIT ?3"
        )) {
            Ok(s) => s,
            Err(_) => return Vec::new(),
        },
        None => match conn.prepare(&format!("{base} ORDER BY score LIMIT ?2")) {
            Ok(s) => s,
            Err(_) => return Vec::new(),
        },
    };

    let rows = match work_id {
        Some(work) => stmt.query(rusqlite::params![parsed.fts, work, bound_limit]),
        None => stmt.query(rusqlite::params![parsed.fts, bound_limit]),
    };
    let mut rows = match rows {
        Ok(r) => r,
        Err(_) => return Vec::new(),
    };

    let mut hits = Vec::new();
    while let Ok(Some(row)) = rows.next() {
        let unit_id: i64 = row.get("unit_id").unwrap_or(0);
        let text: String = row.get("text").unwrap_or_default();
        let line_map: String = row.get("line_map").unwrap_or_default();
        let score: f64 = row.get("score").unwrap_or(0.0);

        let positions = match_positions(&text, &parsed.terms, &parsed.prefix_terms);
        let kind: String = row.get("kind").unwrap_or_default();
        if positions.is_empty() && kind == "paragraph" {
            continue;
        }

        let (snippet, matches) = snippet(&text, &positions, 90);
        let gw_line = line_for_position(&line_map, positions.first().map(|p| p.0));

        hits.push(Hit {
            unit_id,
            work_id: row.get("work_id").unwrap_or_default(),
            siglum: row.get("siglum").unwrap_or_default(),
            book_page: row.get("book_page").ok(),
            gw_line,
            pdf_page: row.get("pdf_page").unwrap_or(0),
            section: row.get("section").unwrap_or_default(),
            snippet,
            matches,
            score: -score,
            kind,
        });
        if hits.len() >= limit {
            break;
        }
    }
    hits
}

/// 命中词在原文中的位置。
///
/// 词的位置**现算**：把单元的正文重新切词、逐词归一，再看哪些词命中了。
///
/// 为什么不另存一张「词 → 偏移」的表？存了要一百多兆（十六卷近两百万个词，
/// 加上两个索引共 101 MB，占整个库的 58%）—— 而 FTS5 已经告诉我们「这个单元
/// 命中了」，剩下的只是在这个单元的一千三百来个字里找那几个词。现算一次
/// 是微秒级的，比从磁盘读一百万行快得多。
fn match_positions(
    text: &str,
    terms: &[String],
    prefix_terms: &[String],
) -> Vec<(usize, usize)> {
    if terms.is_empty() && prefix_terms.is_empty() {
        return Vec::new();
    }
    let mut out = Vec::new();
    for (word, start, end) in crate::ortho::tokenize_with_offsets(text) {
        let normalized = normalize_token(&word);
        let exact_hit = terms.iter().any(|t| *t == normalized);
        let prefix_hit = prefix_terms.iter().any(|t| normalized.starts_with(t.as_str()));
        if exact_hit || prefix_hit {
            out.push((start, end));
        }
    }
    out
}

/// 截一段上下文，并给出命中词在片段中的区间。
///
/// **偏移的单位是「字符」，不是字节。** ETL 里 ``token.offset`` / ``length``
/// 是 Python 的字符下标；Rust 的 ``String`` 按 UTF-8 字节切片，切错了会
/// panic（「ß」正好在两个字节中间）。所以这里先拆成字符数组再切。
///
/// 返回的区间是相对**片段**的 **UTF-16 码元**下标 —— 前端是 JavaScript，
/// ``String.slice`` 按 UTF-16 计数。德语与希腊字母都在 BMP 里，两种计数
/// 一致，但写成 UTF-16 更保险。
fn snippet(text: &str, positions: &[(usize, usize)], context: usize) -> (String, Vec<(usize, usize)>) {
    let chars: Vec<char> = text.chars().collect();

    if positions.is_empty() {
        let end = (context * 2).min(chars.len());
        return (chars[..end].iter().collect::<String>().trim().to_string(), Vec::new());
    }

    // 合并相邻区间
    let mut merged: Vec<(usize, usize)> = Vec::new();
    for (start, end) in positions {
        let (start, end) = (*start, *end);
        match merged.last_mut() {
            Some(last) if start <= last.1 => last.1 = last.1.max(end),
            _ => merged.push((start, end)),
        }
    }

    let mut out = String::new();
    let mut matches = Vec::new();
    let mut cursor = 0usize;

    for (start, end) in merged {
        let (start, end) = (start.min(chars.len()), end.min(chars.len()));
        if start.saturating_sub(cursor) > context * 2 {
            // 离得远：只取命中前的一小段，中间用省略号跳过。
            out.push('…');
            out.push(' ');
            let window_start = snap_left(&chars, start.saturating_sub(context)).max(cursor);
            out.extend(&chars[cursor..window_start]);
        } else {
            // 离得近：两个命中之间的原文**整段留下**。
            //
            // （早先这里的窗口起点算错了：把「吸附到词边界」的结果又夹回
            //  上一个命中的末尾，于是中间那段从来没被加进片段 ——
            //  片段里会出现 „VerhältnißVerhältniß“ 这种两个词粘在一起的样子。）
            out.extend(&chars[cursor..start]);
        }
        let piece: String = chars[start..end].iter().collect();
        let piece_len = utf16_len(&piece);
        let length = utf16_len(&out);
        out.push_str(&piece);
        matches.push((length, length + piece_len));
        cursor = end;
    }
    if cursor < chars.len() {
        let tail_end = snap_right(&chars, (cursor + context).min(chars.len()));
        out.extend(&chars[cursor..tail_end]);
    }
    (out.trim().to_string(), matches)
}

/// 字符串的 UTF-16 码元长度（JavaScript 的 ``String.length``）。
fn utf16_len(s: &str) -> usize {
    s.chars().map(|c| c.len_utf16()).sum()
}

/// 起点往左挪到词边界，免得片段从半个词开始。
fn snap_left(chars: &[char], mut index: usize) -> usize {
    index = index.min(chars.len());
    while index > 0 && chars[index - 1].is_alphanumeric() {
        index -= 1;
    }
    index
}

/// 终点往右挪到词边界。
fn snap_right(chars: &[char], mut index: usize) -> usize {
    index = index.min(chars.len());
    while index < chars.len() && chars[index].is_alphanumeric() {
        index += 1;
    }
    index
}

/// 位置落在印刷层的哪一行。
fn line_for_position(line_map: &str, position: Option<usize>) -> Option<i64> {
    let position = position?;
    let parsed: serde_json::Value = serde_json::from_str(line_map).ok()?;
    for entry in parsed.as_array()? {
        let start = entry.get(0)?.as_u64()? as usize;
        let end = entry.get(1)?.as_u64()? as usize;
        let number = entry.get(2)?.as_i64()?;
        if start <= position && position < end {
            return Some(number);
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn einzelnes_wort() {
        let q = parse("Begriff");
        assert!(q.fts.contains("Begriff") || q.fts.contains("begriff"));
        assert_eq!(q.terms.len(), 1);
    }

    #[test]
    fn implizites_und() {
        let q = parse("genauer Begriff");
        assert!(q.fts.contains("AND"));
        assert_eq!(q.terms.len(), 2);
    }

    #[test]
    fn phrase() {
        let q = parse("\"genauer Begriff\"");
        assert!(q.fts.starts_with('"'));
        assert_eq!(q.terms.len(), 2);
    }

    #[test]
    fn praefix() {
        let q = parse("Subject*");
        assert!(q.fts.contains('*'));
    }

    #[test]
    fn orthographie() {
        let q = parse("Verhältniß");
        // 归一后应是 verhältnis，并且变体展开
        assert!(q.terms.iter().any(|t| t == "verhältnis"));
    }

    #[test]
    fn not_ist_binaer() {
        let q = parse("Begriff NOT Sein");
        assert!(q.fts.contains(" NOT "), "FTS5 的 NOT 必须是二元运算：{}", q.fts);
        assert!(!q.fts.contains("{neg}"));
    }

    #[test]
    fn klammern() {
        let q = parse("(a OR b) c");
        assert!(q.fts.contains("OR"));
        assert!(q.fts.contains("AND"));
    }

    #[test]
    fn fragezeichen_ist_praefix() {
        // FTS5 不支持单字符通配；问号之前的部分当前缀用。
        let q = parse("Begrif?");
        assert_eq!(q.fts, r#"("begrif"*)"#);
        assert_eq!(q.prefix_terms, vec!["begrif".to_string()]);
        assert!(q.terms.is_empty());
    }

    #[test]
    fn klammern_stehen_allein() {
        // 括号必须各自独立成词，不能粘在词上。
        let q = parse("(a OR b) c");
        assert_eq!(q.terms, vec!["a", "b", "c"]);
        assert!(!q.terms.iter().any(|t| t.contains(')')));
    }

    #[test]
    fn 片段保留两个命中之间的原文() {
        // 早先的窗口算法把「吸附到词边界」的结果又夹回了上一个命中的末尾，
        // 于是中间那段从来没进过片段 —— 片段里会看到 „VerhältnißVerhältniß“
        // 这种两个词粘在一起的样子。
        let text = "Verhältniß der Begriffe speculativ ganz eigenthümlich – \
                    anderes Verhältniß folgt unmittelbar.";
        let positions = match_positions(text, &["verhältnis".to_string()], &[]);
        assert_eq!(positions, vec![(0, 10), (64, 74)]);

        let (snippet, ranges) = snippet(text, &positions, 90);
        assert!(snippet.contains("der Begriffe speculativ"), "中间那段原文被吞了");
        assert_eq!(snippet.matches("Verhältniß").count(), 2);
        assert_eq!(ranges, vec![(0, 10), (64, 74)]);
    }

    #[test]
    fn leerer_query() {
        assert!(parse("").fts.is_empty());
        assert!(parse("   ").fts.is_empty());
    }
}
