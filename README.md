# doxygen-comment

**English** | [中文说明](#中文说明)

An agent skill for generating and maintaining [Doxygen](https://www.doxygen.nl/) comments in C/C++
(including Qt) sources. It is not a snippet collection but a pipeline an AI coding assistant can drive
end to end: **read the function signature → generate or complete the comment → mark the comment stale
when the code changes**.

## Features

- **Locate a function by line number or by name.** `parse_function.py` parses C/C++ signatures with
  tree-sitter and prints JSON (function name, return type, parameters and their direction, start line,
  signature fingerprint, optional body snippet). Read-only, no side effects.
- **Six templates.** File header / function / module head / module tail / trailing `/**< */` / short
  `@brief`, matching the editor snippet prefixes `doxygen_source`, `doxygen_fun`,
  `doxygen_module_head`, `doxygen_module_end`, `doxygen_rear`, `doxygen_nom`.
- **Fill in, never rewrite.** When a Doxygen block already exists above a function, only the missing
  fields are added and the fingerprint is refreshed; existing wording and line order are kept. A file
  that already carries an `@file` block is skipped.
- **Signature fingerprint.** Every function block ends with `@doxygen_sig_fp <16 hex digits>`; `--scan`
  compares the current signature against it and marks "signature changed, comment outdated" functions
  as `stale`, which is what makes repository-wide upkeep possible. Pure formatting changes (whitespace,
  `*`/`&` placement) do not change the fingerprint.
- **Nothing is written by default.** A diff is printed first; `--write` applies it while preserving the
  target file's CRLF/LF style and its UTF-8 / UTF-8-BOM / GBK encoding.
- **CJK-text friendly.** The scripts force UTF-8 output, avoiding the mojibake a GBK Windows console
  would otherwise cause.

## Repository layout

```
doxygen-comment/
├── SKILL.md                  # skill body: workflow, script contract, template list
├── README.md                 # this file
├── LICENSE                   # MIT
├── requirements.txt          # Python dependencies
├── assets/
│   └── cpp.json              # the six templates as editor snippets (optional)
├── references/
│   └── examples.md           # before/after examples, Qt cases, common mistakes
└── scripts/
    ├── parse_function.py     # read: locate a function + parse its signature (no side effects)
    ├── gen_doxygen.py        # write: render / insert / complete / fingerprint / diff / scan
    └── install_snippets.py   # optional: merge the snippets into a VS Code style IDE
```

## Installation

### 1. Get the source

```bash
git clone https://github.com/FantastyQAQ/dsh-doxygen.git
```

The repository is named `dsh-doxygen` while the skill is named `doxygen-comment`: when you drop it into
a skills directory, **name the directory `doxygen-comment`**.

### 2. Dependencies

Python 3.10+ is required:

```bash
pip install -r requirements.txt
# equivalent: pip install "tree-sitter>=0.22" "tree-sitter-cpp>=0.21"
```

Tested with `tree-sitter 0.26.0` + `tree-sitter-cpp 0.23.4`; the scripts support the `Language`/`Parser`
construction API both before and after 0.22. On Windows, always type `python` (`python3` is an alias
trap in some environments).

### 3. Drop it into a skills directory

The folder is self-contained — copy the whole directory and it works; the scripts contain no
project-specific paths:

| Host | Skills directory |
|---|---|
| DeepSeek Harness | `~/.dsh/skills/doxygen-comment/` |
| Claude Code | `~/.claude/skills/doxygen-comment/`, or a project's `.claude/skills/` |
| CodeBuddy CN / WorkBuddy | `~/.codebuddy/skills/doxygen-comment/`, `~/.workbuddy/skills/doxygen-comment/` |

```powershell
# e.g. install for Claude Code at user level
git clone https://github.com/FantastyQAQ/dsh-doxygen.git "$env:USERPROFILE\.claude\skills\doxygen-comment"
```

### 4. Verify

```bash
python scripts/parse_function.py --file demo.cpp --list
```

If it prints an array of functions, the installation works.

## Quick start

The commands below are run from the skill root; replace `: <path>` with your source path.

### 1) Locate a function and parse its signature

```bash
python scripts/parse_function.py --file src/rtc.cpp --line 42 --body-lines 30
python scripts/parse_function.py --file src/rtc.cpp --name RTC_Init
python scripts/parse_function.py --file src/rtc.cpp --list      # list all (no body_snippet)
```

The output is UTF-8 JSON:

```json
{
  "name": "RTC_Init",
  "return_type": "int32_t",
  "params": [
    {"type": "const RTC_Config_t*", "name": "config", "direction": "in"},
    {"type": "uint32_t*", "name": "status", "direction": "out"}
  ],
  "start_line": 42,
  "end_line": 68,
  "is_definition": true,
  "signature": "int32_t RTC_Init(const RTC_Config_t* config, uint32_t* status)",
  "fingerprint": "ac50cb812857de87",
  "file": "…/rtc.cpp"
}
```

`direction` is decided by the script using the parameter-direction rules (the "参数方向判断规则"
section of `SKILL.md`); take it as given.

### 2) Generate a function comment

Hand the signature plus the body snippet from the previous step to the model and let it produce the
description JSON:

```json
{
  "brief": "初始化 RTC 外设",
  "params": [
    {"name": "config", "desc": "RTC 配置参数"},
    {"name": "status", "desc": "初始化状态码，非 0 表示失败"}
  ],
  "return_desc": "0 成功，非 0 为错误码",
  "retval": "none",
  "details": "调用前需保证 32.768kHz 晶振已起振。"
}
```

Then render, preview and apply:

```bash
python scripts/gen_doxygen.py --file src/rtc.cpp --line 42 --kind fun --doc doc.json --diff
python scripts/gen_doxygen.py --file src/rtc.cpp --line 42 --kind fun --doc doc.json --write
```

Without `--diff`/`--write` it prints JSON (with `status`, `notes`, `changed`, `diff` fields).

### 3) Other template kinds

```bash
# file header (inserted at the first line of the file)
python scripts/gen_doxygen.py --file src/rtc.cpp --kind source \
  --brief "RTC 驱动" --note "依赖 32.768kHz 晶振" --log-desc "创建" --diff

# module group head / tail (used as a pair)
python scripts/gen_doxygen.py --file src/rtc.cpp --kind module --line 30 \
  --group rtc_api --title "RTC API" --brief "RTC 对外接口" --desc "全部函数可重入" --diff
python scripts/gen_doxygen.py --file src/rtc.cpp --kind module-end --line 120 --diff

# trailing comment / short comment (no signature parsing needed)
python scripts/gen_doxygen.py --file src/rtc.h --kind rear --line 18 --text "已发送帧数" --diff
python scripts/gen_doxygen.py --file src/rtc.h --kind nom  --line 25 --brief "RTC 状态枚举" --diff
```

### 4) Repository-wide scan (read-only)

```bash
python scripts/gen_doxygen.py --scan src
```

It returns `{"summary": {...}, "items": [...]}` where every function carries a `status`:

| scan status | meaning | what to do |
|---|---|---|
| `missing` | no Doxygen block above it | add one with the function-comment flow |
| `stale` | block exists but the fingerprint no longer matches (the code changed) | review the description, then refresh |
| `partial` | block exists but fields are missing (e.g. no `@param`) | fill in only what is missing |
| `ok` | complete and fingerprint matches | leave it alone |

The scan skips `.git`, `build`, `libs`, `node_modules` and similar directories. Do **not** rewrite
hundreds of files in one go: group by status and let the user pick the scope first.

## Commands and exit codes

| Script | Purpose |
|---|---|
| `parse_function.py --file --line/--name/--list [--body-lines N]` | parse a signature |
| `gen_doxygen.py --file … --kind <fun\|nom\|source\|module\|module-end\|rear>` | generate one comment |
| `gen_doxygen.py --scan <dir>` | scan comment status across a tree |

Both scripts share the same exit codes:

| Code | Meaning |
|---|---|
| 0 | Success (including `status=ok/skipped`, i.e. "nothing to change") |
| 1 | Target function not found / not enough arguments |
| 2 | Argument or file error (missing path, invalid JSON) |
| 3 | The `tree-sitter` dependency is missing |

On failure the reason is written to stderr, and stdout never carries a half-written JSON document.

## Authors and copyright

The author and copyright in file headers have **no universal default**: when nothing is specified the
script writes the placeholders `<author>` and
`Copyright (c) <current year> by <copyright holder>, All Rights Reserved.` for the user to replace.
There are two ways to specify them:

```bash
python scripts/gen_doxygen.py --file a.cpp --kind source --brief "…" \
  --author "Your Name (you@example.com)" --copyright "Copyright (c) 2026 by Your Company, All Rights Reserved."
```

```bash
# set once, then every later command reuses it
export DOXYGEN_AUTHOR="Your Name (you@example.com)"
export DOXYGEN_COPYRIGHT="Copyright (c) {year} by Your Company, All Rights Reserved."   # {year} becomes the current year
```

## Optional: install the templates into your IDE

`assets/cpp.json` is exactly the six templates as editor snippets. Type `doxygen_fun` and press Tab to
expand it:

```bash
python scripts/install_snippets.py                       # dry run: detect IDEs, show what would be merged (writes nothing)
python scripts/install_snippets.py --apply --create       # actually write
python scripts/install_snippets.py --uninstall --apply    # remove the snippets this skill installed
```

- The target file is `<IDE user dir>\snippets\cpp.json`; it is **merged**, never overwritten, and the
  previous file is backed up as `cpp.json.bak-<timestamp>`.
- Snippets are scoped per language: `cpp.json` only applies to `.cpp/.cc/.cxx`; to use them in `.c/.h`
  you must merge them into `c.json` in the same directory.
- Only that one snippet file is touched; `settings.json` is left alone.
- CodeBuddy CN, VS Code, CodeBuddy, Cursor and Windsurf can be detected automatically; `--target <file>`
  picks a path explicitly.

## Usage notes

- Existing comment blocks are always **filled in, never rewritten**; a `//` note above a function is
  preserved and the Doxygen block is inserted directly above the function.
- The fingerprint line is written and refreshed only by the script — do not hand-write it, and do not
  put it after `*/`.
- Comments are always UTF-8; avoid non-ASCII glyphs such as `?` or `→` inside comments so that a source
  encoding conversion cannot silently drop characters.
- Indentation follows the target line: comments for class members and for Qt `signals:`/`slots:`
  entries are aligned automatically.
- Look at the diff before writing; run `--scan` before a bulk change.

## Compatibility

- Python 3.10+, on Windows / Linux / macOS (the scripts handle Windows console encoding).
- C/C++ sources; Qt projects work as-is (`signals:`/`slots:` regions are covered).
- Host-agnostic: any agent with Bash plus file read/write tools can drive it — no specific IDE or
  plugin required.

## License

[MIT](LICENSE).

Repository: <https://github.com/FantastyQAQ/dsh-doxygen>

---

## 中文说明

给 C/C++（含 Qt）源码生成与维护 [Doxygen](https://www.doxygen.nl/) 注释的 Agent Skill（技能包）。
它不是片段收藏夹，而是一条可被 AI 编程助手直接调用的流水线：
**读函数签名 → 生成/补全注释 → 代码改了自动标记注释过期**。

### 特性

- **按行号或函数名定位函数**：`parse_function.py` 用 tree-sitter 解析 C/C++ 签名，输出 JSON
  （函数名、返回类型、参数及方向、起始行、签名指纹、可选函数体片段），只读、无副作用。
- **六套模板**：文件头 / 函数 / 模块头 / 模块尾 / 行尾 `/**< */` / 简短 `@brief`，
  与编辑器片段前缀 `doxygen_source`、`doxygen_fun`、`doxygen_module_head`、`doxygen_module_end`、
  `doxygen_rear`、`doxygen_nom` 一一对应。
- **只补不重写**：函数上方已有 Doxygen 块时，只补齐缺失字段并刷新指纹，不改已有措辞与行序；
  文件头已有 `@file` 块则直接跳过。
- **签名指纹**：函数注释块末尾写入 `@doxygen_sig_fp <16 位十六进制>`；`--scan` 对比当前签名与指纹，
  把「签名变了、注释过期」的函数标成 `stale`，从而支持仓库级自动维护。
  纯格式化（空格、`*`/`&` 位置）改动不会导致指纹变化。
- **默认不落盘**：先输出 diff，`--write` 才写回；写回时保持目标文件原有的 CRLF/LF 与
  UTF-8 / UTF-8-BOM / GBK 编码。
- **中文友好**：脚本强制 UTF-8 输出，规避 Windows 控制台 GBK 造成的中文乱码。

### 目录结构

```
doxygen-comment/
├── SKILL.md                  # 技能正文：工作流、脚本契约、模板列表
├── README.md                 # 本文件
├── LICENSE                   # MIT
├── requirements.txt          # Python 依赖
├── assets/
│   └── cpp.json              # 六套模板的编辑器片段（可选安装）
├── references/
│   └── examples.md           # 前后对照示例、Qt 场景、常见错误
└── scripts/
    ├── parse_function.py     # 读：定位函数 + 解析签名（无副作用）
    ├── gen_doxygen.py        # 写：渲染 / 插入 / 补全 / 指纹 / diff / 扫描
    └── install_snippets.py   # 可选：把片段合并进 VS Code 系 IDE
```

### 安装

#### 1. 获取源码

```bash
git clone https://github.com/FantastyQAQ/dsh-doxygen.git
```

仓库名是 `dsh-doxygen`，技能名仍是 `doxygen-comment`：放进宿主技能目录时**目录名请用 `doxygen-comment`**。

#### 2. 依赖

需要 Python 3.10+：

```bash
pip install -r requirements.txt
# 等价写法：pip install "tree-sitter>=0.22" "tree-sitter-cpp>=0.21"
```

实测组合 `tree-sitter 0.26.0` + `tree-sitter-cpp 0.23.4`；脚本对 0.22 前后的 `Language`/`Parser`
构造 API 都做了兼容。Windows 下统一写 `python`（`python3` 在部分环境是别名陷阱）。

#### 3. 放进宿主的技能目录

整目录复制即可，脚本不含任何工程硬编码：

| 宿主 | 技能目录 |
|---|---|
| DeepSeek Harness | `~/.dsh/skills/doxygen-comment/` |
| Claude Code | `~/.claude/skills/doxygen-comment/`，或工程的 `.claude/skills/` |
| CodeBuddy CN / WorkBuddy | `~/.codebuddy/skills/doxygen-comment/`、`~/.workbuddy/skills/doxygen-comment/` |

```powershell
# 例：装到 Claude Code 用户级技能目录
git clone https://github.com/FantastyQAQ/dsh-doxygen.git "$env:USERPROFILE\.claude\skills\doxygen-comment"
```

#### 4. 验证

```bash
python scripts/parse_function.py --file demo.cpp --list
```

能打印出函数数组即安装成功。

### 快速开始

以下命令都在技能根目录下执行；`: <path>` 换成你的源码路径。

#### 1) 定位函数并解析签名

```bash
python scripts/parse_function.py --file src/rtc.cpp --line 42 --body-lines 30
python scripts/parse_function.py --file src/rtc.cpp --name RTC_Init
python scripts/parse_function.py --file src/rtc.cpp --list      # 批量列出（无 body_snippet）
```

输出为 UTF-8 JSON：

```json
{
  "name": "RTC_Init",
  "return_type": "int32_t",
  "params": [
    {"type": "const RTC_Config_t*", "name": "config", "direction": "in"},
    {"type": "uint32_t*", "name": "status", "direction": "out"}
  ],
  "start_line": 42,
  "end_line": 68,
  "is_definition": true,
  "signature": "int32_t RTC_Init(const RTC_Config_t* config, uint32_t* status)",
  "fingerprint": "ac50cb812857de87",
  "file": "…/rtc.cpp"
}
```

`direction` 由脚本按[参数方向规则]（`SKILL.md` 的「参数方向判断规则」一节）判定，可直接沿用。

#### 2) 生成函数注释

把上一步的签名 + 函数体片段交给模型，产出描述 JSON：

```json
{
  "brief": "初始化 RTC 外设",
  "params": [
    {"name": "config", "desc": "RTC 配置参数"},
    {"name": "status", "desc": "初始化状态码，非 0 表示失败"}
  ],
  "return_desc": "0 成功，非 0 为错误码",
  "retval": "none",
  "details": "调用前需保证 32.768kHz 晶振已起振。"
}
```

再渲染、预演、落盘：

```bash
python scripts/gen_doxygen.py --file src/rtc.cpp --line 42 --kind fun --doc doc.json --diff
python scripts/gen_doxygen.py --file src/rtc.cpp --line 42 --kind fun --doc doc.json --write
```

不带 `--diff`/`--write` 时输出 JSON（含 `status`、`notes`、`changed`、`diff` 字段）。

#### 3) 其他类型

```bash
# 文件头（插到文件第一行）
python scripts/gen_doxygen.py --file src/rtc.cpp --kind source \
  --brief "RTC 驱动" --note "依赖 32.768kHz 晶振" --log-desc "创建" --diff

# 模块分组头 / 尾（成对使用）
python scripts/gen_doxygen.py --file src/rtc.cpp --kind module --line 30 \
  --group rtc_api --title "RTC API" --brief "RTC 对外接口" --desc "全部函数可重入" --diff
python scripts/gen_doxygen.py --file src/rtc.cpp --kind module-end --line 120 --diff

# 行尾注释 / 简短注释（不需要解析签名）
python scripts/gen_doxygen.py --file src/rtc.h --kind rear --line 18 --text "已发送帧数" --diff
python scripts/gen_doxygen.py --file src/rtc.h --kind nom  --line 25 --brief "RTC 状态枚举" --diff
```

#### 4) 仓库级扫描（只读）

```bash
python scripts/gen_doxygen.py --scan src
```

返回 `{"summary": {...}, "items": [...]}`，每个函数带 `status`：

| scan status | 含义 | 处理方式 |
|---|---|---|
| `missing` | 上方没有 Doxygen 块 | 按函数注释流程补 |
| `stale` | 有块但签名指纹对不上（代码改过） | 复核描述后刷新 |
| `partial` | 有块但缺字段（如缺 `@param`） | 只补缺失字段 |
| `ok` | 完整且指纹一致 | 不动 |

扫描会自动跳过 `.git`、`build`、`libs`、`node_modules` 等目录。**不要**一次性改上百个文件：
先按状态分组汇报，让用户挑范围。

### 命令与退出码

| 脚本 | 用途 |
|---|---|
| `parse_function.py --file --line/--name/--list [--body-lines N]` | 解析签名 |
| `gen_doxygen.py --file … --kind <fun\|nom\|source\|module\|module-end\|rear>` | 生成单处注释 |
| `gen_doxygen.py --scan <目录>` | 批量扫描注释状态 |

退出码两个脚本一致：

| 码 | 含义 |
|---|---|
| 0 | 成功（含 `status=ok/skipped` 的「无需改动」） |
| 1 | 未找到目标函数 / 参数不足 |
| 2 | 参数或文件错误（路径不存在、JSON 非法） |
| 3 | 缺少 tree-sitter 依赖 |

失败时原因写入 stderr，stdout 不会输出半截 JSON。

### 作者与版权

文件头注释里的作者、版权**没有通用默认值**：不指定时脚本写出 `<author>`、
`Copyright (c) <当年> by <copyright holder>, All Rights Reserved.` 这样的占位符，
由使用者替换。指定方式两种：

```bash
python scripts/gen_doxygen.py --file a.cpp --kind source --brief "…" \
  --author "Your Name (you@example.com)" --copyright "Copyright (c) 2026 by Your Company, All Rights Reserved."
```

```bash
# 一次性预设，之后所有命令沿用
export DOXYGEN_AUTHOR="Your Name (you@example.com)"
export DOXYGEN_COPYRIGHT="Copyright (c) {year} by Your Company, All Rights Reserved."   # {year} 会替换成当年
```

### 可选：把模板装进 IDE

`assets/cpp.json` 就是六套模板的编辑器片段。手敲 `doxygen_fun` + Tab 即可展开：

```bash
python scripts/install_snippets.py                      # 预演：探测 IDE、显示将合并的内容（不写盘）
python scripts/install_snippets.py --apply --create      # 实际写入
python scripts/install_snippets.py --uninstall --apply   # 撤销
```

- 目标文件是 `<IDE 用户目录>\snippets\cpp.json`，**合并**而非覆盖，写入前自动备份 `cpp.json.bak-<时间戳>`。
- 片段按语言作用域生效：`cpp.json` 只对 `.cpp/.cc/.cxx` 生效，要给 `.c/.h` 用需另行并入同目录的 `c.json`。
- 只改这一个片段文件，不动 `settings.json`。
- 支持探测 CodeBuddy CN、VS Code、CodeBuddy、Cursor、Windsurf；也可用 `--target <file>` 指定路径。

### 使用注意

- 已有注释块一律**只补不重写**；函数上方原有的 `//` 说明保留，Doxygen 块插在函数正上方。
- 指纹行只由脚本写入/刷新，不要手写，也不要放到 `*/` 之后。
- 注释统一 UTF-8；不要写 `?`、`→` 之类的非 ASCII 特殊字形，避免源码转换时丢字。
- 缩进跟随目标行：类内成员、Qt `signals:`/`slots:` 下的注释会自动对齐。
- 落盘前先看 diff；批量改动前先 `--scan`。

### 兼容性

- Python 3.10+，Windows / Linux / macOS 均可（脚本对 Windows 控制台编码做了处理）。
- C/C++ 源码；Qt 工程可直接用（`signals:`/`slots:` 区域已覆盖）。
- 宿主无关：只要有 Bash + 文件读写工具即可驱动，不依赖特定 IDE 或插件。

### 许可

[MIT](LICENSE)。
