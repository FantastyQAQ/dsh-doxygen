#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_doxygen.py —— Doxygen 注释的模板填充 / 插入 / 补全 / 指纹。

与 parse_function.py 的分工：
  parse_function.py  只「读」：定位函数、解析签名（无副作用）
  gen_doxygen.py     只「写」：渲染模板、决定插入或补全、输出 diff / 落盘

命令行契约见本技能 SKILL.md 的「脚本调用契约」一节。
默认只输出 diff（JSON 的 "diff" 字段），加 --write 才落盘；--diff 打印纯 diff 文本。

退出码：0 成功 / 1 未找到目标 / 2 参数或文件错误 / 3 缺少 tree-sitter 依赖。
"""

from __future__ import annotations

import argparse
import datetime
import difflib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.dont_write_bytecode = True          # 不往 skill 目录里丢 __pycache__

from parse_function import find_function, list_functions  # noqa: E402

# ---- 常量 --------------------------------------------------------------------

TAG_WIDTH = 13                     # 标签列宽（@brief 之后补到第 13 列），与既有注释风格一致
FP_TAG = "doxygen_sig_fp"          # 签名指纹标签
# 作者 / 版权没有通用默认值：未显式指定时写成尖括号占位符，由使用者替换。
# 可用环境变量预设一次：DOXYGEN_AUTHOR / DOXYGEN_COPYRIGHT（后者可含 {year}）。
AUTHOR_DEFAULT = os.environ.get("DOXYGEN_AUTHOR", "").strip() or "<author>"
COPYRIGHT_DEFAULT = (
    os.environ.get("DOXYGEN_COPYRIGHT", "").strip()
    or "Copyright (c) {year} by <copyright holder>, All Rights Reserved."
)
VERSION_DEFAULT = "1.0"

KINDS = ("fun", "nom", "source", "module", "module-end", "rear")

SOURCE_EXTS = (".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".inl")
SKIP_DIRS = {
    ".git", ".svn", ".hg", ".claude", ".codebuddy", ".trae", ".dsh", ".vscode", ".idea",
    "build", "release", "debug", "release_dist", "libs", "node_modules",
}

_TAG_RE = re.compile(r"@(\w+)")
_PARAM_RE = re.compile(r"@param(?:\[\s*[^\]]*\s*\])?\s+(?:\{([^}]*)\}|([*&\w:~<>]+))")
_FP_RE = re.compile(r"@" + FP_TAG + r"\s+([0-9a-fA-F]+)")


# ---- 文件读写（保持换行风格与编码） ------------------------------------------

def load_source(path):
    """返回 (行列表, 换行符, 编码, 原始字节)。行不含换行符，写回时可原样拼回。"""
    with open(path, "rb") as fp:
        raw = fp.read()
    encoding = "utf-8"
    if raw.startswith(b"\xef\xbb\xbf"):
        encoding = "utf-8-sig"
    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError:
        encoding = "gbk"
        text = raw.decode("gbk", "replace")
    newline = "\r\n" if "\r\n" in text else "\n"
    return text.split(newline), newline, encoding, raw


def save_lines(path, lines, newline, encoding):
    with open(path, "wb") as fp:
        fp.write(newline.join(lines).encode(encoding, "replace"))


def unified_diff(path, old_lines, new_lines):
    rel = os.path.basename(path)
    diff = difflib.unified_diff(
        old_lines, new_lines,
        fromfile="a/" + rel, tofile="b/" + rel,
        lineterm="", n=3,
    )
    return "\n".join(diff)


# ---- 渲染：各模板 ------------------------------------------------------------

def _tag(tag, text, indent=""):
    """` * @brief       text` 形式的一行（标签补到第 TAG_WIDTH 列）。"""
    pad = max(1, TAG_WIDTH - len(tag))
    return "{} * {}{}{}".format(indent, tag, " " * pad, text)


def _log_row(date, version, author_short, desc):
    return " * <tr><td>{:<8}    <td>{:<8}  <td>{:<8}  <td>{}".format(
        date, version, author_short, desc)


def resolve_param_docs(info, doc):
    """把 LLM 给的参数描述对到签名参数上。

    返回 ([(param, direction, desc)], [未匹配上的说明名])。
    按参数名匹配；没有名字的说明项才退化到按位置匹配，避免名字写错时描述串位。
    direction 优先取 LLM 给的，否则用 parse_function 按「参数方向判断规则」算出的结果。
    """
    provided = doc.get("params") or []
    by_name = {p["name"]: p for p in provided if p.get("name")}
    unnamed = [p for p in provided if not p.get("name")]
    resolved = []
    for index, param in enumerate(info.get("params", [])):
        item = by_name.get(param.get("name")) if param.get("name") else None
        if item is None and unnamed:
            item = unnamed.pop(0)
        item = item or {}
        resolved.append((param, item.get("direction") or param.get("direction") or "in",
                         item.get("desc", "")))
    used = {p.get("name") for p in provided if p.get("name")}
    known = {p.get("name") for p in info.get("params", [])}
    unmatched = sorted(n for n in used if n and n not in known)
    return resolved, unmatched


def _param_body(param, desc):
    """模板里的 `{<param_name>} <类型> <说明>` 段。"""
    if param.get("variadic"):
        return "{{...}} {}".format(desc).rstrip()
    name = param.get("name") or "_"          # 形参未命名时用 _ 占位
    if param.get("type"):
        return "{{{}}} {} {}".format(name, param["type"], desc).rstrip()
    return "{{{}}} {}".format(name, desc).rstrip()


def render_function_block(info, doc, indent=""):
    """模板 2：函数注释（含签名指纹）。"""
    lines = [indent + "/**", _tag("@brief", doc.get("brief") or "<待补充>", indent), indent + " *"]
    param_docs, _ = resolve_param_docs(info, doc)
    for param, direction, desc in param_docs:
        lines.append(_tag("@param[{}]".format(direction), _param_body(param, desc), indent))
    if info.get("is_constructor"):
        lines.append(_tag("@return", "none（构造/析构函数，无返回值）", indent))
    elif not info.get("return_type") or info["return_type"] == "void":
        lines.append(_tag("@return", "none", indent))
    else:
        lines.append(_tag("@return", doc.get("return_desc") or "none", indent))
    for detail in doc.get("return_details") or []:
        lines.append("{} *        -     {}".format(indent, detail))
    for tag, text in (("@retval", doc.get("retval")), ("@todo", doc.get("todo")),
                      ("@details", doc.get("details"))):
        if text:
            lines.append(_tag(tag, text, indent))
    lines.append(_tag("@" + FP_TAG, info["fingerprint"], indent))
    lines.append(indent + " */")
    return lines


def render_nom_block(brief, indent=""):
    """模板 6：仅 @brief 的简短注释。"""
    return [indent + "/**", _tag("@brief", brief or "<待补充>", indent), indent + " *", indent + " */"]


def render_rear_line(text):
    """模板 5：分号后的行内注释。"""
    return "/**< {} */".format(text or "<说明>")


def render_source_block(opts, filename, indent=""):
    """模板 1：文件头注释。"""
    author = opts["author"]
    author_short = author.split("(")[0].strip().split(" ")[0] or author
    lines = [
        indent + "/**",
        _tag("@file", filename, indent),
        _tag("@brief", opts["brief"] or "<简要说明>", indent),
        _tag("@author", author, indent),
        _tag("@version", opts["version"], indent),
        _tag("@date", opts["date"], indent),
    ]
    for warn in opts["warnings"]:
        lines.append(_tag("@warning", warn, indent))
    for note in opts["notes"]:
        lines.append(_tag("@note", note, indent))
    lines.append(indent + " *")
    lines.append(_tag("@copyright", opts["copyright"], indent))
    lines.append(indent + " *")
    lines.append(_tag("@par", "修改日志:", indent))
    lines.append(indent + " * <table>")
    lines.append(indent + " * <tr><th>Date        <th>Version   <th>Author    <th>Description")
    lines.append(indent + " * " + _log_row(opts["date"], opts["version"], author_short,
                                           opts["log_desc"] or opts["brief"] or "<描述>")[3:])
    lines.append(indent + " * </table>")
    lines.append(indent + " */")
    return lines


def render_module_block(group, title, brief, desc, indent=""):
    """模板 3：模块注释开头。"""
    lines = [indent + "/**", _tag("@defgroup", "{} {}".format(group, title).strip(), indent),
             indent + " *"]
    if brief:
        lines.append(indent + " * " + brief)
    for row in desc or []:
        lines.append(indent + " * " + row)
    lines.append(indent + " * @{")
    lines.append(indent + " */")
    return lines


def render_module_end_block(indent=""):
    """模板 4：模块注释结尾。"""
    return [indent + "/**", indent + " * @}", indent + " *", indent + " */"]


# ---- 既有注释块的识别 / 补全 --------------------------------------------------

def find_doc_block(lines, start_line):
    """向上找紧邻目标的 `/** ... */` 块，返回 [start, end) 的 0 基行区间。"""
    index = start_line - 2
    blanks = 0
    while index >= 0 and not lines[index].strip():
        blanks += 1
        if blanks > 2:
            return None
        index -= 1
    if index < 0 or not lines[index].rstrip().endswith("*/"):
        return None
    end = index
    while index >= 0 and end - index < 200:
        stripped = lines[index].strip()
        if stripped.startswith("/**") and not stripped.startswith("/***"):
            return (index, end + 1)
        if stripped.startswith("/*") and index != end:
            return None
        index -= 1
    return None


def analyze_block(block_lines):
    """解析既有块：返回 (标签集合, 已文档化的参数名集合, 是否有 ... 变参说明)。"""
    tags = set()
    params = set()
    variadic = False
    for line in block_lines:
        found = _TAG_RE.search(line)
        if not found:
            continue
        tags.add(found.group(1).lower())
        for hit in _PARAM_RE.finditer(line):
            name = (hit.group(1) or hit.group(2) or "").strip()
            if name == "...":
                variadic = True
            elif name:
                params.add(name)
    return tags, params, variadic


def existing_fingerprint(block_lines):
    for line in block_lines:
        hit = _FP_RE.search(line)
        if hit:
            return hit.group(1)
    return None


def fill_block(lines, block, info, doc):
    """只补缺失字段 + 刷新指纹，不改写已有描述文字。返回 (新行列表, 说明列表)。"""
    start, end = block
    block_lines = list(lines[start:end])
    indent = re.match(r"[ \t]*", block_lines[0]).group(0)
    tags, params, has_variadic = analyze_block(block_lines)
    notes = []
    after_open = []
    before_close = []

    if "brief" not in tags:
        after_open.append(_tag("@brief", doc.get("brief") or "<待补充>", indent))
        notes.append("补 @brief")

    param_docs, _ = resolve_param_docs(info, doc)
    for param, direction, desc in param_docs:
        if param.get("variadic"):
            if has_variadic:
                continue
            body = _param_body(param, desc)
        else:
            name = param.get("name")
            if not name or name in params:
                continue
            body = _param_body(param, desc)
        before_close.append(_tag("@param[{}]".format(direction), body, indent))
        notes.append("补 @param {}".format(param.get("name") or "..."))

    if info.get("return_type") and "return" not in tags:
        before_close.append(_tag("@return", doc.get("return_desc") or "none", indent))
        notes.append("补 @return")
    for tag, key in (("@retval", "retval"), ("@todo", "todo"), ("@details", "details")):
        if doc.get(key) and tag.lstrip("@").lower() not in tags:
            before_close.append(_tag(tag, doc[key], indent))
            notes.append("补 " + tag)

    if after_open:
        block_lines[1:1] = after_open

    fingerprint = info["fingerprint"]
    stale = False
    current = existing_fingerprint(block_lines)
    if current is None:
        before_close.append(_tag("@" + FP_TAG, fingerprint, indent))
        notes.append("写入签名指纹")
    elif current != fingerprint:
        block_lines = [re.sub(r"(@" + FP_TAG + r"\s+)[0-9a-fA-F]+", r"\g<1>" + fingerprint, line)
                       for line in block_lines]
        stale = True
        notes.append("刷新签名指纹（签名已变化）")

    if before_close:
        block_lines[len(block_lines) - 1:len(block_lines) - 1] = before_close

    new_lines = lines[:start] + block_lines + lines[end:]
    return new_lines, notes, stale


# ---- 各 kind 的处理 ----------------------------------------------------------

def handle_function(path, lines, args, doc, raw):
    info = find_function(raw, line=args.line, name=args.name, body_lines=0)
    if info is None:
        return None, {"status": "error", "reason": "未找到函数（{}）".format(
            "--name {}".format(args.name) if args.name else "--line {}".format(args.line))}
    block = find_doc_block(lines, info["start_line"])
    result = {
        "function": info["name"],
        "line": info["start_line"],
        "fingerprint": info["fingerprint"],
        "signature": info["signature"],
    }
    if block is None:
        indent = re.match(r"[ \t]*", lines[info["start_line"] - 1]).group(0)
        block_lines = render_function_block(info, doc, indent)
        result["status"] = "inserted"
        result["notes"] = ["在函数上方插入完整 Doxygen 块"]
        new_lines = lines[:info["start_line"] - 1] + block_lines + lines[info["start_line"] - 1:]
    else:
        new_lines, notes, stale = fill_block(lines, block, info, doc)
        result["stale_fingerprint"] = stale
        result["notes"] = notes
        result["status"] = "updated" if notes else "ok"
    _, unmatched = resolve_param_docs(info, doc)
    if unmatched:
        result.setdefault("notes", []).append("参数说明未匹配到形参：{}".format("、".join(unmatched)))
    return new_lines, result


def handle_nom(path, lines, args, doc, raw=None):
    target = args.line
    if target is None:
        return None, {"status": "error", "reason": "kind=nom 需要 --line"}
    if not 1 <= target <= len(lines):
        return None, {"status": "error",
                      "reason": "行号越界：{}（文件共 {} 行）".format(target, len(lines))}
    indent = re.match(r"[ \t]*", lines[target - 1]).group(0)
    block_lines = render_nom_block(doc.get("brief"), indent)
    result = {"line": target, "status": "inserted", "notes": ["插入 @brief 简短注释"]}
    return lines[:target - 1] + block_lines + lines[target - 1:], result


def handle_rear(path, lines, args, doc, raw=None):
    target = args.line
    if target is None:
        return None, {"status": "error", "reason": "kind=rear 需要 --line"}
    if not 1 <= target <= len(lines):
        return None, {"status": "error",
                      "reason": "行号越界：{}（文件共 {} 行）".format(target, len(lines))}
    text = args.text or doc.get("brief") or ""
    new_lines = list(lines)
    new_lines[target - 1] = new_lines[target - 1].rstrip() + " " + render_rear_line(text)
    result = {"line": target, "status": "inserted", "notes": ["追加行尾注释"]}
    return new_lines, result


def handle_source(path, lines, args, doc, raw=None):
    opts = {
        "brief": args.brief or doc.get("brief") or "",
        "author": args.author or AUTHOR_DEFAULT,
        "version": args.version or VERSION_DEFAULT,
        "date": args.date or datetime.date.today().strftime("%Y%m%d"),
        "copyright": args.copyright or COPYRIGHT_DEFAULT.replace(
            "{year}", str(datetime.date.today().year)),
        "log_desc": args.log_desc or "",
        "notes": args.note or [],
        "warnings": args.warning or [],
    }
    # 文件头若已存在含 @file 的 Doxygen 块，按「不重写」原则跳过
    index = 0
    while index < min(len(lines), 10) and not lines[index].strip():
        index += 1
    if index < len(lines) and lines[index].lstrip().startswith("/**"):
        for end in range(index, min(len(lines), index + 120)):
            if lines[end].rstrip().endswith("*/"):
                if any("@file" in row for row in lines[index:end + 1]):
                    return None, {"status": "skipped",
                                  "reason": "文件头已有 Doxygen 注释（第 {} 行），不重写".format(index + 1)}
                break
    block_lines = render_source_block(opts, os.path.basename(path))
    result = {"line": 1, "status": "inserted", "notes": ["在文件首行插入文件头注释"]}
    return block_lines + lines, result


def handle_module(path, lines, args, doc, raw=None):
    target = args.line or 1
    if not 1 <= target <= len(lines) + 1:
        return None, {"status": "error",
                      "reason": "行号越界：{}（文件共 {} 行）".format(target, len(lines))}
    if args.kind != "module-end" and not args.group:
        return None, {"status": "error", "reason": "kind=module 需要 --group"}
    indent = re.match(r"[ \t]*", lines[target - 1]).group(0) if lines else ""
    if args.kind == "module-end":
        block_lines = render_module_end_block(indent)
        result = {"line": target, "status": "inserted", "notes": ["插入 @} 模块结尾"]}
    else:
        block_lines = render_module_block(args.group, args.title or args.group,
                                         args.brief or doc.get("brief") or "",
                                         args.desc or [], indent)
        result = {"line": target, "status": "inserted", "notes": ["插入 @defgroup 模块开头"]}
    return lines[:target - 1] + block_lines + lines[target - 1:], result


# ---- 批量扫描 ----------------------------------------------------------------

def scan_tree(root, exts=SOURCE_EXTS):
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith("moc_")]
        for name in sorted(files):
            if name.lower().endswith(exts):
                yield os.path.join(base, name)


def scan_file(path):
    lines, _, _, raw = load_source(path)
    report = []
    for info in list_functions(raw):
        block = find_doc_block(lines, info["start_line"])
        item = {
            "file": path,
            "name": info["name"],
            "start_line": info["start_line"],
            "fingerprint": info["fingerprint"],
        }
        if block is None:
            item["status"] = "missing"
            item["missing_fields"] = ["<整个注释块>"]
        else:
            body = lines[block[0]:block[1]]
            tags, params, has_variadic = analyze_block(body)
            missing = []
            if "brief" not in tags:
                missing.append("@brief")
            for param in info["params"]:
                if param.get("name") and param["name"] not in params:
                    missing.append("@param " + param["name"])
                if param.get("variadic") and not has_variadic:
                    missing.append("@param ...")
            if info["return_type"] and "return" not in tags:
                missing.append("@return")
            current = existing_fingerprint(body)
            stale = current is None or current != info["fingerprint"]
            if stale:
                item["status"] = "stale"
                item["stale_fingerprint"] = True
            elif missing:
                item["status"] = "partial"
            else:
                item["status"] = "ok"
            item["missing_fields"] = missing
        report.append(item)
    return report


# ---- 命令行 ------------------------------------------------------------------

def build_doc(args):
    doc = {"brief": args.brief or "", "params": [],
           "return_desc": getattr(args, "return_text", None) or "",
           "return_details": args.return_detail or [], "retval": args.retval or "",
           "todo": args.todo or "", "details": args.details or ""}
    if args.doc:
        if args.doc == "-":
            # 直接读字节再按 UTF-8 解码，避免 Windows 控制台编码把中文搞坏
            chunk = sys.stdin.buffer.read()
            try:
                text = chunk.decode("utf-8")
            except UnicodeDecodeError:
                text = chunk.decode("gbk", "replace")
        else:
            with open(args.doc, "rb") as fp:
                text = fp.read().decode("utf-8-sig")
        text = text.lstrip("\ufeff")
        try:
            data = json.loads(text)
        except ValueError as exc:
            sys.stderr.write("--doc 不是合法 JSON：{}\n".format(exc))
            sys.exit(2)
        for key, value in data.items():
            if value not in (None, "", [], {}):
                doc[key] = value
    if args.param:
        params = list(doc.get("params") or [])
        for item in args.param:
            if "=" not in item:
                sys.stderr.write("--param 格式应为 NAME=说明：{}\n".format(item))
                sys.exit(2)
            name, _, desc = item.partition("=")
            params.append({"name": name.strip(), "desc": desc.strip()})
        doc["params"] = params
    return doc


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):     # Windows 控制台默认 GBK，中文会乱码
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):    # pragma: no cover
            pass
    ap = argparse.ArgumentParser(description="Doxygen 注释渲染 / 插入 / 补全 / 指纹")
    ap.add_argument("--file", help="目标源文件")
    ap.add_argument("--line", type=int, help="目标行号（1 基）")
    ap.add_argument("--name", help="按函数名定位（配合 kind=fun）")
    ap.add_argument("--kind", choices=KINDS, default="fun", help="注释类型，默认 fun")
    ap.add_argument("--doc", help="LLM 输出的 JSON（brief/params/return_desc/retval/details）；- 表示读 stdin")
    ap.add_argument("--brief", help="@brief 内容")
    ap.add_argument("--param", action="append", help="参数说明 NAME=说明，可重复")
    ap.add_argument("--return", dest="return_text", help="@return 说明")
    ap.add_argument("--return-detail", action="append", help="@return 下的补充说明行，可重复")
    ap.add_argument("--retval", help="@retval 内容")
    ap.add_argument("--todo", help="@todo 内容")
    ap.add_argument("--details", help="@details 补充说明")
    ap.add_argument("--text", help="kind=rear 的行尾注释文本")
    ap.add_argument("--author", help="kind=source 的作者，默认 " + AUTHOR_DEFAULT
                                     + "；也可用环境变量 DOXYGEN_AUTHOR 预设")
    ap.add_argument("--version", help="kind=source 的版本号，默认 " + VERSION_DEFAULT)
    ap.add_argument("--date", help="kind=source 的日期 YYYYMMDD，默认今天")
    ap.add_argument("--copyright", help="kind=source 的版权行，默认缺省占位符写法；"
                                        "也可用环境变量 DOXYGEN_COPYRIGHT（其中 {year} 会替换成当年）")
    ap.add_argument("--note", action="append", help="kind=source 的 @note，可重复")
    ap.add_argument("--warning", action="append", help="kind=source 的 @warning，可重复")
    ap.add_argument("--log-desc", help="kind=source 修改日志的描述")
    ap.add_argument("--group", help="kind=module 的 @defgroup 组名")
    ap.add_argument("--title", help="kind=module 的组标题")
    ap.add_argument("--desc", action="append", help="kind=module 的详细说明行，可重复")
    ap.add_argument("--write", action="store_true", help="落盘（默认只输出 diff）")
    ap.add_argument("--diff", action="store_true", help="直接打印纯 diff 文本（人读用）")
    ap.add_argument("--scan", help="批量扫描目录，输出各函数注释状态 JSON")
    args = ap.parse_args(argv)

    if args.scan:
        if not os.path.isdir(args.scan):
            sys.stderr.write("目录不存在：{}\n".format(args.scan))
            return 2
        report = []
        for path in scan_tree(os.path.abspath(args.scan)):
            try:
                report.extend(scan_file(path))
            except Exception as exc:            # 单个文件坏了不影响整批
                report.append({"file": path, "status": "error", "error": str(exc)})
        summary = {}
        for item in report:
            summary[item["status"]] = summary.get(item["status"], 0) + 1
        json.dump({"summary": summary, "items": report}, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0

    if not args.file:
        sys.stderr.write("缺少 --file\n")
        return 2
    path = os.path.abspath(args.file)
    if not os.path.isfile(path):
        sys.stderr.write("文件不存在：{}\n".format(path))
        return 2

    lines, newline, encoding, raw = load_source(path)
    doc = build_doc(args)

    handlers = {"fun": handle_function, "nom": handle_nom, "rear": handle_rear,
                "source": handle_source, "module": handle_module,
                "module-end": handle_module}
    new_lines, result = handlers[args.kind](path, lines, args, doc, raw)
    if new_lines is None:
        payload = {"file": path, "kind": args.kind, "changed": False, "wrote": False, "diff": ""}
        payload.update(result)
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0 if payload.get("status") == "skipped" else 1

    changed = new_lines != lines
    diff = unified_diff(path, lines, new_lines) if changed else ""
    if changed and args.write:
        save_lines(path, new_lines, newline, encoding)

    payload = {"file": path, "kind": args.kind, "wrote": bool(changed and args.write),
               "changed": changed, "diff": diff}
    payload.update(result)
    if args.diff:
        sys.stdout.write(diff + ("\n" if diff else ""))
        if not diff:
            sys.stdout.write("（无改动，注释已是最新：{}）\n".format(payload.get("status")))
        return 0
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
