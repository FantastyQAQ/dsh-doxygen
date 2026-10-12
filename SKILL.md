---
name: doxygen-comment
description: 为 C/C++（含 Qt）源码生成与维护 Doxygen 注释（文件头/函数/模块/行尾/简短注释）。当用户请求「给函数加注释」「生成文件头注释」「补全 @brief/@param/@return」「批量给源码补 Doxygen 注释」「检查注释是否过期」，或提到片段前缀 doxygen_source / doxygen_fun / doxygen_module_head / doxygen_module_end / doxygen_rear / doxygen_nom 时使用。内置解析脚本可按行号或函数名定位函数、自动取签名并判定参数方向，生成后靠签名指纹支持「代码改了、注释自动标记过期」的维护流程。不要用于普通业务注释或非 Doxygen 风格的注释。
allowed-tools: Read, Write, Edit, Bash, Grep, Glob
---

# Doxygen Comment

为 C/C++（含 Qt）源码生成与维护 Doxygen 注释的技能包。它**不是代码片段库**，而是一套**注释生产工作流**：

- `scripts/parse_function.py` —— 读：按行号/函数名定位函数，解析签名（无副作用）
- `scripts/gen_doxygen.py` —— 写：模板填充、插入或补全已有注释、写入签名指纹、输出 diff

模板正文放在最后一节（[模板列表](#模板列表)），只在**没有脚本可比**的场景（手写、用户直接索要片段）下才手工展开。

## 路径约定

脚本相对本文件位于 `scripts/`。下文所有脚本路径都写成 `${SKILL_DIR}/scripts/...`，
其中 `${SKILL_DIR}` 是**本 SKILL.md 所在目录的绝对路径**，按顺序取值：

1. 宿主注入的技能目录变量 —— 如 CodeBuddy 的 `${CODEBUDDY_SKILL_DIR}`、Claude Code 的
   `${CLAUDE_SKILL_DIR}`，或宿主等价物；
2. 否则用本 SKILL.md 自身的绝对路径（技能被 `~/.dsh/skills/` 一类目录加载时，
   该路径即 `<技能根>/doxygen-comment`）。

拿到绝对路径后，命令不受工作目录、盘符、clone 位置影响：

```bash
PARSE="${SKILL_DIR}/scripts/parse_function.py"
GEN="${SKILL_DIR}/scripts/gen_doxygen.py"
```

若两者都拿不到（宿主只认相对路径），依次在下列目录下找
`doxygen-comment/scripts/parse_function.py`，用第一个存在的作为 `${SKILL_DIR}`：

1. `~/.dsh/skills`（DeepSeek Harness）
2. `~/.claude/skills`（Claude Code）
3. `~/.codebuddy/skills`、`~/.workbuddy/skills`（CodeBuddy 系）
4. 当前工程的 `.claude/skills`、`.codebuddy/skills`、`.trae/skills`

安装方法见 `README.md`；脚本不含任何工程硬编码，换工程后无需重装。

## 工作流

### 场景 A：用户光标位于函数上，请求生成函数注释（主场景）

1. 取到光标所在的**文件路径与行号**（由调用方传入，如 `$FILE`、`$LINE`；用户只给了文件名时应先用工具定位到具体函数行）。
2. 执行解析脚本：

   ```bash
   python "${SKILL_DIR}/scripts/parse_function.py" --file "$FILE" --line "$LINE" --body-lines 30
   ```

   PowerShell 下若管道/编码不稳，可先落临时文件再读；不要用 `python3`（Windows 上是别名陷阱，直接写 `python`）。
3. 读取返回的 JSON：`name`、`return_type`、`params[]`、`start_line`、`signature`、`fingerprint`，以及可选的 `body_snippet`（前 30 行源码）。
4. 参数方向：脚本已按[参数方向判断规则](#参数方向判断规则)给出每个参数的 `direction`，**直接沿用**；仅当规则明显不适用（如 `out` 缓冲区被规则判成 `in`）时由你覆盖。
5. 按[描述生成提示词](#描述生成提示词)基于签名 + `body_snippet` 写 `brief` / 各参数说明 / `return_desc`，产出一份 JSON。
6. 调生成脚本填充模板并预演（**默认只输出 diff，不落盘**）：

   ```bash
   python "${SKILL_DIR}/scripts/gen_doxygen.py" \
     --file "$FILE" --line "$LINE" --kind fun --doc /tmp/doc.json --diff
   ```

7. 脚本会自动判断函数上方是否已有 Doxygen 块，并给出 `status`：

   | status | 含义 | 脚本行为 |
   |---|---|---|
   | `inserted` | 上方无注释块 | 在函数正上方插入完整块，缩进对齐 |
   | `updated` | 有块但缺字段 / 指纹过期 | **只补缺失字段 + 刷新指纹，不重写已有内容** |
   | `ok` | 块完整且指纹一致 | 不改动 |
   | `skipped` | 文件头已有 Doxygen 注释 | 不改动 |

8. 把 diff 给用户看，确认后把 `--diff` 换成 `--write` 落盘。用户说「直接写」时可跳过确认，但仍应在回复里贴出改动摘要。

### 场景 B：用户请求添加文件头注释

1. 取文件名与当前日期（脚本自己取，无需你算）。
2. 用户没给 `@brief`/`@warning`/`@note` 内容时，先问一句；用户说「你看着写」就依据文件内容概括。
3. 作者 / 版权**没有通用默认值**：不指定时脚本写出 `<author>`、
   `Copyright (c) <当年> by <copyright holder>, All Rights Reserved.` 这样的占位符。
   用户没提供就保留占位符，或用 `--author "名字 (邮箱)"` / `--copyright "..."` 指定；
   想一次设好，可在环境里导出 `DOXYGEN_AUTHOR` / `DOXYGEN_COPYRIGHT`（后者可含 `{year}`）。
4. 执行：

   ```bash
   python "${SKILL_DIR}/scripts/gen_doxygen.py" --file "$FILE" --kind source \
     --brief "..." --note "..." --log-desc "创建" --diff
   ```

5. 脚本插到文件第一行（`#include` / `#pragma once` 之上）；已有 `@file` 块则返回 `skipped`，此时改用 `--kind fun` 等按需补函数注释，不要重写文件头。

### 场景 C：用户请求模块注释

按模板 3、4 配对插入，`@defgroup` 的组名需向用户确认：

```bash
python "${SKILL_DIR}/scripts/gen_doxygen.py" --file "$FILE" --kind module --line <模块首行> \
  --group <组名> --title <标题> --brief "..." --desc "..." --diff
python "${SKILL_DIR}/scripts/gen_doxygen.py" --file "$FILE" --kind module-end --line <模块末行+1> --diff
```

### 场景 D：用户请求行尾注释或简短注释

不需要解析函数签名：

```bash
python "${SKILL_DIR}/scripts/gen_doxygen.py" --file "$FILE" --kind nom  --line <行号> --brief "..." --diff
python "${SKILL_DIR}/scripts/gen_doxygen.py" --file "$FILE" --kind rear --line <行号> --text "..." --diff
```

### 场景 E：批量扫描 / 自动维护（仓库级）

批量补注释是 Agent 的编排工作，Skill 只提供「可被循环调用的接口」：

```bash
python "${SKILL_DIR}/scripts/gen_doxygen.py" --scan <源码目录>   # 只读，输出每个函数的 status
```

返回 `{"summary": {...}, "items": [...]}`，逐个处理 `missing` / `stale` / `partial` 的条目（`--scan` 会自动跳过 `build*`、`libs`、`.git` 等目录）。**不要**一次性改上百个文件：先按 status 分组汇报，让用户挑范围。

`stale` 即「函数签名变了、注释过期」——这是[签名指纹](#签名指纹)机制在起作用；处理方式同场景 A。

## 参数方向判断规则

脚本 `param_direction()` 已实现以下规则，输出 `in` / `out` / `in,out`；规则覆盖不到的再交给 LLM 推断：

- `const T*` / `const T&` → `in`
- `T*` / `T&`（非 const）：
  - 函数名以 `get`、`find`、`read`、`query` 开头 → `in,out`
  - 函数名以 `init`、`create`、`open`、`alloc` 开头 → `out`
  - 其他 → `out`
- 基本类型传值（`int`、`bool`、枚举等）→ `in`
- 结构体传值 → `in`
- 数组形参（`T a[]`、`T* argv[]` 等）→ `in`
- 函数指针形参（如 `void (*cb)(int)`）→ `in`
- 可变参数 `...` → `in`

生成脚本只在注释块**新建**时写入方向；补全已有块时保持原方向不动。

## 描述生成提示词

解析出函数签名后，按以下格式构造 Prompt（可用 `body_snippet`，即函数前 30 行源码）：

输入：

- 函数名：`{name}`
- 返回类型：`{return_type}`
- 参数列表：`{params_json}`（含脚本判定的 `direction`）
- 函数体前 30 行：`{body_snippet}`

要求：只输出 JSON，不要输出任何其他内容。

```json
{
  "brief": "一句话说明函数做什么（中文，不超过 30 字）",
  "params": [
    {"name": "参数名", "desc": "参数用途（中文，不超过 20 字）"}
  ],
  "return_desc": "返回值含义，void 则填 none",
  "retval": "返回值枚举说明，无则填 none",
  "details": "补充说明，无则填 none"
}
```

补充约定：

- `params[].name` **必须与签名里的形参名完全一致**；`name` 写空时才按位置匹配。对不上的名字不会串位，脚本会在 `notes` 里报「参数说明未匹配到形参」，此时请修正后重试。
- 如需覆盖方向，可在该项里加 `"direction": "in" | "out" | "in,out"`。
- 可选字段：`"return_details": ["@return 下的补充行"]`、`"todo"`。值为 `none` 的字段脚本会按模板原样写出。
- 描述要落到「业务语义」上（给谁用、边界条件、副作用），不要复述函数名。

## 签名指纹

每次生成**函数**注释时，在注释块末尾追加一行隐藏标记：

```doxygen
/**
 * ...
 * @doxygen_sig_fp 174c0e7e1c86bd8c
 */
```

指纹算法：

```text
sha256(f"{name}|{return_type}|" + "|".join(f"{p['type']} {p['name']}" for p in params))[:16]
```

- 类型文本做了规范化（压空白、`*`/`&` 贴住类型），所以**纯格式化改动不会导致指纹变化**；形参增删、类型或返回类型变化才会。
- 用途：`--scan` 时对比当前签名与指纹，把注释标记为 `stale`，从而支持「根据代码变化自动维护」。
- 指纹行**只由脚本写入/刷新**，不要手写，也不要放在 `*/` 之后。文件头/模块/行尾注释没有指纹（无签名可对比）。
- 例外：旧注释块没有指纹行时，脚本会补一行（`@brief`/`@param` 等已有内容原样保留）。

## 脚本调用契约

### parse_function.py（读）

```bash
python parse_function.py --file <path> --line <int> [--body-lines 30]
python parse_function.py --file <path> --name <函数名>
python parse_function.py --file <path> --list
```

输出（stdout，UTF-8 JSON）：

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
  "file": "E:\\...\\rtc.cpp",
  "body_snippet": "…（仅在传 --body-lines 时出现）"
}
```

- `start_line` 是**可插入注释的第一行**（含 `template<...>` 等包装）；`--line` 命中函数体内任意一行也算命中。
- 构造函数 / 析构函数 `return_type` 为空字符串，并带 `"is_constructor": true`。
- `--list` 输出数组，元素为上述对象（无 `body_snippet`），用于批量扫描。

### gen_doxygen.py（写）

```bash
python gen_doxygen.py --file <path> [--line <int> | --name <函数名>] \
  --kind <fun|nom|source|module|module-end|rear> \
  [--doc <json 文件|->] [--brief ...] [--param NAME=说明]... [--return ...] \
  [--return-detail ...] [--retval ...] [--todo ...] [--details ...] [--text ...] \
  [--author ...] [--version ...] [--date YYYYMMDD] [--copyright ...] \
  [--note ...]... [--warning ...]... [--log-desc ...] \
  [--group ...] [--title ...] [--desc ...]... \
  [--diff | --write]
python gen_doxygen.py --scan <目录>
```

- **默认不落盘**：输出 JSON（含 `status`、`notes`、`changed`、`diff` 字段）；`--diff` 改为只打印纯 diff 文本；`--write` 才写文件。
- 写回时保持原文件的换行风格（CRLF/LF）与编码（UTF-8 / UTF-8-BOM / GBK），是 UTF-8 工程的必要条件。
- `--kind nom` / `rear` 必须给 `--line`；`--kind source` 不需要行号；`--kind module` 必须给 `--group`。
- Windows PowerShell 下建议把提示词 JSON 存成文件用 `--doc path` 传入；`--doc -` 走管道时中文可能被控制台编码破坏。

### 退出码（两个脚本一致）

| 码 | 含义 |
|---|---|
| 0 | 成功（含 `status=ok/skipped` 的「无需改动」） |
| 1 | 未找到目标函数 / 参数不足 |
| 2 | 参数或文件错误（路径不存在、JSON 非法） |
| 3 | 缺少 tree-sitter 依赖 |

失败时 stderr 输出原因，stdout 不输出半截 JSON。

### 依赖

- Python 3.10+
- `tree-sitter`、`tree-sitter-cpp`：`pip install tree-sitter tree-sitter-cpp`
  （实测 0.26 / 0.23.4 可用；脚本对 0.22 前后的 API 均做了兼容）
- 两个脚本都把 stdout/stderr 强制成 UTF-8 输出，避免 Windows 控制台 GBK 造成中文乱码。

## 模板列表

脚本按下列模板渲染；只有手工写注释或用户直接索要片段时才自行展开。

### 1. doxygen格式源文件注释（prefix: doxygen_source / kind=source）

文件头部注释，用于 `.c/.cpp/.h` 文件顶端。

```doxygen
/**
 * @file        <文件名>
 * @brief       <简要说明>
 * @author      <author>
 * @version     1.0
 * @date        <YYYYMMDD>
 * @warning     <警告内容>
 * @note        <备注内容>
 *
 * @copyright   Copyright (c) <YYYY> by <copyright holder>, All Rights Reserved.
 *
 * @par         修改日志:
 * <table>
 * <tr><th>Date        <th>Version   <th>Author    <th>Description
 * <tr><td><YYYYMMDD>  <td>1.0       <td><author>  <td><描述>
 * </table>
 */
```

占位符替换：

- `<文件名>` → 当前文件名（`--file` 的 basename）
- `<简要说明>` → 用户输入或 `--brief`（`$0`）
- `<YYYYMMDD>` → 当前日期（`--date`，默认今天）
- `<author>` → `--author`，或环境变量 `DOXYGEN_AUTHOR`；都没有时**原样保留占位符**
- `<copyright holder>`、`<YYYY>` → `--copyright`，或环境变量 `DOXYGEN_COPYRIGHT`
  （未指定时写出 `Copyright (c) <当年> by <copyright holder>, All Rights Reserved.`）
- `<警告内容>` → `--warning`，无则删掉该行
- `<备注内容>` → `--note`（可重复，每个一行；行内换行用 `\n` 自行续行对齐）
- `<描述>` → `--log-desc`（默认沿用 `--brief`）

### 2. doxygen格式函数注释（prefix: doxygen_fun / kind=fun）

函数前注释，包含参数、返回值、retval 等。

```doxygen
/**
 * @brief       <简要说明>
 *
 * @param[in]   {<param_name>} <类型> <说明>
 * @param[out]  {<param_name>} <类型> <说明>
 * @return      none
 *        -     <返回值说明>
 * @retval      <返回值枚举说明>
 * @todo        none
 * @details     none
 * @doxygen_sig_fp <16位十六进制指纹>
 */
```

占位符替换：

- `<简要说明>` → 描述 JSON 的 `brief`
- `{<param_name>} <类型> <说明>` → 每个形参一行，方向取 `direction`；形参未命名时名字写 `_`，可变参数写 `{...}`
- `<返回值说明>` → `return_desc`；`void`/构造函数写 `none`
- `<返回值枚举说明>` → `retval`，`@return` 的补充行来自 `return_details`
- `@todo`/`@details` 未提供时写 `none`
- 指纹行由脚本按签名计算，永远放在**最后一行**、`*/` 之前

### 3. doxygen格式模块注释开头（prefix: doxygen_module_head / kind=module）

模块/分组起始注释。

```doxygen
/**
 * @defgroup    RTC_mouble RTC
 *
 * <简要说明>
 * <详细说明>
 * @{
 */
```

占位符替换：

- `<简要说明>` → `--brief`（`$0`）
- `<详细说明>` → `--desc`（可重复，每行一条）
- `RTC_mouble` 与 `RTC` → `--group` / `--title`

### 4. doxygen格式模块注释结尾（prefix: doxygen_module_end / kind=module-end）

模块/分组结束注释，与 `doxygen_module_head` 配对。

```doxygen
/**
 * @}
 *
 */
```

### 5. doxygen分号后面注释（prefix: doxygen_rear / kind=rear）

变量或成员声明后紧跟的行内注释。

```doxygen
/**< <说明> */
```

占位符替换：

- `<说明>` → `--text`

### 6. doxygen常用注释（prefix: doxygen_nom / kind=nom）

仅含 `@brief` 的简短注释，适用于简单函数或类型。

```doxygen
/**
 * @brief       <简要说明>
 *
 */
```

占位符替换：

- `<简要说明>` → `--brief`

## 使用规则

1. 用户给出 prefix（如 `doxygen_fun`）或描述用途（如「给函数加 Doxygen 注释」），匹配对应 `--kind`。
2. **优先走脚本**；只有用户明确要「一段模板文本」时才手写片段，此时未提供的值保留 `$0`、`$1` 占位符以便在 IDE 中跳转编辑。
3. 已有注释块一律**只补不重写**：缺 `@brief` 补 `@brief`，缺 `@param` 补 `@param`，不调整已有行顺序、不改已有措辞。函数上方原有的 `//` 说明注释保留，Doxygen 块插在函数正上方。
4. 模板里 `@warning`、`@note`、`@todo`、`@details`、`@retval` 等可选字段，未指定内容时可保留为 `none` 或省略该行。
5. 注释必须使用 UTF-8 编码；**不要在注释里直接敲 `?`、`→` 这类非 ASCII 字形以外的特殊符号**，避免源码编码转换时丢字（`?`）。
6. 生成的注释不破坏原有缩进：脚本取目标行/`/**` 行的前导空白做前缀，类内成员注释自动与成员对齐。
7. 改动落盘前先给 diff；一次批量改动前先 `--scan` 汇报范围，避免对全仓库无提示地大批量写入。

## 可选：把六套模板装进 IDE（编辑器片段）

本技能自带 `assets/cpp.json` —— 就是上文六套模板的编辑器代码片段，prefix 与模板一致。
若希望手敲 `doxygen_fun` + Tab 就能展开，可把它装进 IDE：

```powershell
# 1) 预演：探测本机 IDE，显示将要合并的内容（默认不写盘）
python "${SKILL_DIR}/scripts/install_snippets.py"

# 2) 实际写入；片段文件还不存在时加 --create
python "${SKILL_DIR}/scripts/install_snippets.py" --apply --create

# 3) 撤销本技能装进去的片段
python "${SKILL_DIR}/scripts/install_snippets.py" --uninstall --apply
```

要点：

- 目标文件是 `<IDE 用户目录>\snippets\cpp.json`，**合并**而非覆盖，写入前自动备份 `cpp.json.bak-<时间戳>`。
- 片段按语言作用域生效：`cpp.json` 只对 `.cpp` / `.cc` / `.cxx` 生效；要给 `.c` / `.h` 用需另行并入同目录的 `c.json`。
- 只改这一个片段文件，不动 `settings.json`。

`references/examples.md` 是完整的「前后对照」示例（文件头 / 函数 / in,out 参数 / 模块分组 / 尾随注释 / Qt 信号槽），拿不准排版时先看它。

## 安装与分发

本技能是一份自包含目录（`SKILL.md` + `scripts/` + `references/` + `assets/`），
整目录复制到宿主的技能目录即可用；两个 `.py` 里不含任何工程硬编码，换工程无需重装。

| 宿主 | 技能目录 |
|---|---|
| DeepSeek Harness | `~/.dsh/skills/doxygen-comment/` |
| Claude Code | `~/.claude/skills/doxygen-comment/`，或工程的 `.claude/skills/` |
| CodeBuddy CN / WorkBuddy | `~/.codebuddy/skills/doxygen-comment/`、`~/.workbuddy/skills/doxygen-comment/` |

**升级方式**：用新版本整目录覆盖旧目录，`SKILL.md` 与 `scripts/`、`assets/`、`references/`
要一起更新，避免模板和脚本版本对不上。

源码仓库：<https://github.com/FantastyQAQ/dsh-doxygen>（仓库名 `dsh-doxygen`，技能目录名仍用 `doxygen-comment`）。

若宿主支持子代理，可另注册一个 `doxygen-agent` 指向本技能；只有 SKILL.md 时功能同样完整。
依赖安装、验证方法和常见问题见 `README.md`。
