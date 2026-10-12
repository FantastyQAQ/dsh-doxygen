#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""parse_function.py —— 解析 C/C++ 函数签名（Doxygen 注释生成的第一步）。

给「文件 + 行号」（或函数名），返回函数签名 JSON，供上层组装 Doxygen 注释。

命令行契约见本技能 SKILL.md 的「脚本调用契约」一节：
    python parse_function.py --file <path> --line <int> [--body-lines 30]
    python parse_function.py --file <path> --name <函数名>
    python parse_function.py --file <path> --list

退出码：0 成功 / 1 未找到函数 / 2 参数或文件错误 / 3 缺少 tree-sitter 依赖。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from typing import List, Optional, Tuple

__all__ = [
    "extract_function",
    "list_functions",
    "find_function",
    "signature_fingerprint",
    "param_direction",
]

# ---- 依赖初始化（tree-sitter 0.22 前后 API 有差异，这里做兼容） ----------------

_MISSING_DEP_HINT = (
    "缺少依赖 tree-sitter / tree-sitter-cpp。\n"
    "安装：pip install tree-sitter tree-sitter-cpp"
)

try:
    import tree_sitter_cpp
    from tree_sitter import Language, Parser
except ImportError:  # pragma: no cover - 环境问题
    sys.stderr.write(_MISSING_DEP_HINT + "\n")
    sys.exit(3)


def _build_language():
    """兼容 0.22 前后两种 Language 构造方式。"""
    raw = tree_sitter_cpp.language()
    try:
        return Language(raw)             # >= 0.22：直接传语言对象
    except TypeError:                    # pragma: no cover - 老版本
        return Language(raw, "cpp")


def _build_parser(language):
    try:
        return Parser(language)          # >= 0.22：构造时指定语言
    except TypeError:                    # pragma: no cover - 老版本
        parser = Parser()
        parser.set_language(language)
        return parser


CPP_LANGUAGE = _build_language()
PARSER = _build_parser(CPP_LANGUAGE)


# ---- 语法树的小工具 ----------------------------------------------------------

# 可能承载「函数声明」的节点：定义本体、普通声明、类成员声明
_FUNC_HOST_TYPES = ("function_definition", "declaration", "field_declaration")

# 需要把起始行一并计入的外层包装（模板、extern "C"）
_WRAPPER_TYPES = ("template_declaration", "linkage_specification")

# 可直接当作「名字」的叶子节点
_NAME_LEAF_TYPES = ("identifier", "field_identifier", "destructor_name", "operator_name")

# 参数列表里需要跳过 / 特殊对待的节点
_VARIADIC_TYPES = ("variadic_declarator", "...")
_PARAM_TYPES = ("parameter_declaration", "optional_parameter_declaration")


def _text(src: bytes, node) -> str:
    """按字节区间取原文。"""
    return src[node.start_byte:node.end_byte].decode("utf-8", "replace")


def _tidy(text: str) -> str:
    """压掉换行与多余空白，便于单行渲染。"""
    return re.sub(r"\s+", " ", text).strip()


def _tidy_type(text: str) -> str:
    """规范化类型文本：压空白、去掉 `*`/`&` 两侧空格（`char *argv[]` → `char*[]`）。"""
    out = _tidy(text)
    out = re.sub(r"\s*([*&])", r"\1", out)
    out = re.sub(r"([*&])\s+", r"\1", out)
    out = re.sub(r"\s+([\[\],\)])", r"\1", out)
    out = re.sub(r"([\(\[])\s+", r"\1", out)
    return out.strip()


def _find_function_declarator(decl):
    """沿 declarator 链向下找 function_declarator（剥掉指针 / 引用 / 括号包装）。

    `int *foo()` 的 declarator 是 pointer_declarator→function_declarator，
    `void (*cb)(int)` 的 declarator 直接就可能是 function_declarator。
    """
    seen = set()
    cur = decl
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if cur.type == "function_declarator":
            return cur
        nxt = cur.child_by_field_name("declarator")
        if nxt is None:
            nxt = next((c for c in cur.children if c.is_named), None)
        cur = nxt
    return None


def _innermost_name_node(decl):
    """取 declarator 里最内层的名字节点（函数名或参数名）。"""
    seen = set()
    cur = decl
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if cur.type in _NAME_LEAF_TYPES:
            return cur
        nxt = cur.child_by_field_name("declarator")
        if nxt is None:
            named = [c for c in cur.children if c.is_named]
            if not named:
                return cur
            # qualified_identifier / destructor_name 的名字在最后一个子节点
            nxt = named[-1] if cur.type == "qualified_identifier" else named[0]
        cur = nxt
    return None


# ---- 参数方向判断（与 SKILL.md「参数方向判断规则」保持一致） ------------------

_DIRECTION_RULES = (
    (re.compile(r"^(get|find|read|query)", re.IGNORECASE), "in,out"),
    (re.compile(r"^(init|create|open|alloc)", re.IGNORECASE), "out"),
)


def param_direction(func_name: str, type_text: str) -> str:
    """按确定性规则判断参数方向，返回 `in` / `out` / `in,out`。

    const T* / const T& / 传值 / 函数指针 → in；
    非 const 的指针与引用按函数名前缀决定，兜底 out。
    """
    out = type_text.strip()
    if not (out.endswith("*") or out.endswith("&")):
        return "in"                       # 传值（基本类型/结构体）、函数指针、数组
    if re.search(r"\bconst\b", out):
        return "in"                       # const T* / const T&
    for pattern, direction in _DIRECTION_RULES:
        if pattern.match(func_name):
            return direction
    return "out"


def _parse_parameter(node, src: bytes, func_name: str) -> Optional[dict]:
    """把 parameter_declaration / variadic_declarator 转成 {type, name, direction}。"""
    if node.type in _VARIADIC_TYPES:
        return {"type": "...", "name": "", "direction": "in", "variadic": True}
    if node.type not in _PARAM_TYPES:
        return None

    decl = node.child_by_field_name("declarator")
    default = node.child_by_field_name("default_value")
    limit = default.start_byte if default is not None else node.end_byte
    name_node = _innermost_name_node(decl) if decl is not None else None

    if name_node is not None:
        name = _text(src, name_node)
        # 抠掉名字本身，剩下的就是类型（含 `*` `&` `[]` 等修饰）
        type_text = _tidy_type(
            src[node.start_byte:name_node.start_byte].decode("utf-8", "replace")
            + src[name_node.end_byte:limit].decode("utf-8", "replace")
        )
    else:
        name = ""
        type_text = _tidy_type(src[node.start_byte:limit].decode("utf-8", "replace"))

    item = {
        "type": type_text,
        "name": name,
        "direction": param_direction(func_name, type_text),
    }
    if default is not None:
        item["default"] = _text(src, default)
    return item


def signature_fingerprint(info: dict) -> str:
    """签名指纹：sha256("名字|返回类型|类型 名字|...")[:16]。

    用于判断「函数签名变了、注释过期了」——见 SKILL.md「签名指纹」。
    """
    basis = "{}|{}|".format(info.get("name", ""), info.get("return_type", ""))
    basis += "|".join("{} {}".format(p.get("type", ""), p.get("name", ""))
                      for p in info.get("params", []))
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


# ---- 节点 → 签名信息 --------------------------------------------------------

def _describe(src: bytes, node, wrap, body_lines: int = 0) -> dict:
    """把 function_definition / 函数声明节点整理成 JSON 可序列化的签名信息。"""
    decl = node.child_by_field_name("declarator")
    fdecl = _find_function_declarator(decl)
    name_node = fdecl.child_by_field_name("declarator")
    params_node = fdecl.child_by_field_name("parameters")

    return_type = ""
    if decl is not None and decl.start_byte > node.start_byte:
        # 从声明起始到 declarator 起始之间的部分就是返回类型（含 const/static/*）
        return_type = _tidy_type(src[node.start_byte:decl.start_byte].decode("utf-8", "replace"))

    params: List[dict] = []
    if params_node is not None:
        name = _text(src, name_node) if name_node is not None else ""
        for child in params_node.children:
            item = _parse_parameter(child, src, name)
            if item is not None:
                params.append(item)

    info = {
        "name": _text(src, name_node) if name_node is not None else "",
        "return_type": return_type,
        "params": params,
        "start_line": (wrap.start_point[0] if wrap is not None else node.start_point[0]) + 1,
        "end_line": node.end_point[0] + 1,
        "is_definition": node.type == "function_definition",
        "signature": _tidy(src[node.start_byte:fdecl.end_byte].decode("utf-8", "replace")),
    }
    if not return_type:
        info["is_constructor"] = True      # 构造函数 / 析构函数，无返回类型
    info["fingerprint"] = signature_fingerprint(info)

    if body_lines > 0 and node.type == "function_definition":
        lines = src[node.start_byte:node.end_byte].decode("utf-8", "replace").split("\n")
        info["body_snippet"] = "\n".join(lines[:body_lines])
    return info


def _collect(node, wrap, out: List[Tuple[object, object]]) -> None:
    """递归收集函数节点；不进入函数体，避免把局部变量/对象误判成函数。"""
    for child in node.children:
        ctype = child.type
        if ctype == "function_definition":
            if _find_function_declarator(child.child_by_field_name("declarator")) is not None:
                out.append((child, wrap))
            continue
        if ctype in ("declaration", "field_declaration"):
            decl = child.child_by_field_name("declarator")
            if decl is not None and _find_function_declarator(decl) is not None:
                out.append((child, wrap))
                continue
        new_wrap = wrap
        if ctype == "template_declaration" and wrap is None:
            new_wrap = child
        _collect(child, new_wrap, out)


def list_functions(src: bytes, body_lines: int = 0) -> List[dict]:
    """列出源文件里所有函数（含头文件里的声明与类成员函数）。"""
    nodes: List[Tuple[object, object]] = []
    _collect(PARSER.parse(src).root_node, None, nodes)
    items = [_describe(src, node, wrap, body_lines) for node, wrap in nodes]
    items.sort(key=lambda it: it["start_line"])
    return items


def find_function(src: bytes, line: Optional[int] = None, name: Optional[str] = None,
                  body_lines: int = 0) -> Optional[dict]:
    """按行号或名字定位函数；行号落在函数体内也算命中。"""
    items = list_functions(src, body_lines)
    if name:
        for item in items:
            if item["name"] == name or item["name"].split("::")[-1] == name:
                return item
        return None
    if line is None:
        return None
    hit = None
    for item in items:                     # 取包含该行的最内层函数
        if item["start_line"] <= line <= item["end_line"]:
            if hit is None or item["end_line"] - item["start_line"] < hit["end_line"] - hit["start_line"]:
                hit = item
    if hit is not None:
        return hit
    for item in items:                     # 兜底：往后找最近的函数（光标停在注释上时用）
        if 0 < item["start_line"] - line <= 5:
            return item
    return None


def extract_function(source_code: bytes, cursor_byte: int) -> Optional[dict]:
    """兼容旧调用：按光标字节偏移定位函数。"""
    line = source_code[:cursor_byte].count(b"\n") + 1
    return find_function(source_code, line=line)


# ---- 命令行 ------------------------------------------------------------------

def _read_source(path: str) -> bytes:
    with open(path, "rb") as fp:
        return fp.read()


def _dump(obj) -> None:
    json.dump(obj, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def _force_utf8_stdout() -> None:
    """Windows 控制台默认 GBK，会把中文输出成乱码；统一按 UTF-8 输出。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):    # pragma: no cover
            pass


def main(argv: Optional[List[str]] = None) -> int:
    _force_utf8_stdout()
    ap = argparse.ArgumentParser(
        description="解析 C/C++ 函数签名，输出 JSON（供 Doxygen 注释生成使用）")
    ap.add_argument("--file", required=True, help="源文件路径")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--line", type=int, help="光标所在行号（1 基）")
    group.add_argument("--name", help="按函数名定位（支持 Class::func 或裸函数名）")
    group.add_argument("--list", action="store_true", help="列出文件内全部函数")
    ap.add_argument("--body-lines", type=int, default=0,
                    help="额外附带函数前 N 行源码（供 LLM 写 @brief，默认 0 不带）")
    args = ap.parse_args(argv)

    path = os.path.abspath(args.file)
    if not os.path.isfile(path):
        sys.stderr.write("文件不存在：{}\n".format(path))
        return 2
    if not args.list and args.line is None and args.name is None:
        sys.stderr.write("必须给出 --line / --name / --list 之一\n")
        return 2

    try:
        src = _read_source(path)
    except OSError as exc:
        sys.stderr.write("读取失败：{}\n".format(exc))
        return 2

    if args.list:
        items = list_functions(src, args.body_lines)
        for item in items:
            item["file"] = path
        _dump(items)
        return 0

    info = find_function(src, line=args.line, name=args.name, body_lines=args.body_lines)
    if info is None:
        target = "--name {}".format(args.name) if args.name else "--line {}".format(args.line)
        sys.stderr.write("未找到函数（{} {}）\n".format(path, target))
        return 1

    info["file"] = path
    if args.line is not None:
        info["query_line"] = args.line
    _dump(info)
    return 0


if __name__ == "__main__":
    sys.exit(main())
