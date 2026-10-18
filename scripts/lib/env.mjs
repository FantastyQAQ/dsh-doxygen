// Python runtime probe for the doxygen-comment skill.
//
// Every script in this skill is a Python script, so a machine without a Python
// interpreter fails deep inside the agent's shell with an OS-specific message
// ("'python' is not recognized as an internal or external command", "python3:
// command not found"). The DSH plugin runs this probe once at registration,
// injects the verdict at the top of the skill body, and the same probe backs
// `scripts/check_env.mjs` for manual installs and for re-checking after the
// user installs Python.
//
// The probe itself is plain Node (no dependencies) because it has to work on
// exactly the machines where Python is missing.

import { spawnSync } from 'node:child_process'

export const MIN_PYTHON = [3, 10]
export const MODULES = ['tree_sitter', 'tree_sitter_cpp']

// Printed as JSON by the probed interpreter: version, executable path and the
// import status of both parser modules (a real import, so a broken compiled
// extension is reported instead of a false success).
const PROBE_SOURCE = [
  'import json, sys',
  'report = {"version": "%d.%d.%d" % sys.version_info[:3],',
  '          "exe": sys.executable, "missing": [], "errors": {}}',
  'for mod in ("tree_sitter", "tree_sitter_cpp"):',
  '    try:',
  '        __import__(mod)',
  '    except Exception as exc:',
  '        report["missing"].append(mod)',
  '        report["errors"][mod] = "%s: %s" % (type(exc).__name__, exc)',
  'report["version_ok"] = sys.version_info >= (3, 10)',
  'print(json.dumps(report))',
].join('\n')

const INSTALL_HINT = [
  '- 安装 Python 3.10+：https://www.python.org/downloads/',
  '  Windows 安装时勾选 “Add python.exe to PATH”；macOS 可 `brew install python`；',
  '  Ubuntu/Debian 用 `sudo apt install python3 python3-pip`。',
  '- 再安装解析依赖：`python -m pip install tree-sitter tree-sitter-cpp`',
].join('\n')

/**
 * Interpreter candidates in probing order. `DOXYGEN_PYTHON` (an absolute path or
 * any command name) overrides detection, which is how venv / conda / portable
 * installs whose interpreter is not on PATH are supported.
 */
export function pythonCandidates() {
  const forced = process.env.DOXYGEN_PYTHON?.trim()
  if (forced) return [{ command: forced, args: [] }]
  return process.platform === 'win32'
    ? [
        { command: 'python', args: [] },
        { command: 'py', args: ['-3'] },
        { command: 'python3', args: [] },
      ]
    : [
        { command: 'python3', args: [] },
        { command: 'python', args: [] },
      ]
}

/** Decode a child-process buffer: the probe prints UTF-8, but a stray Windows
 * tool (a Store stub, a broken shim) may answer in the ANSI code page (GBK on
 * Chinese systems). Replacement characters are the tell. */
function decode(buffer) {
  if (!buffer || buffer.length === 0) return ''
  const utf8 = buffer.toString('utf8')
  if (!utf8.includes('\uFFFD')) return utf8
  try {
    return new TextDecoder('gbk').decode(buffer)
  } catch {
    return utf8
  }
}

/** Run one candidate: `-c PROBE_SOURCE`, parse the JSON line it prints. */
function runCandidate({ command, args }) {
  const display = [command, ...args].join(' ')
  const result = spawnSync(command, [...args, '-c', PROBE_SOURCE], {
    timeout: 8000,
    windowsHide: true,
    env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' },
  })

  if (result.error) {
    // ENOENT: the command does not exist at all — the expected "no Python" case.
    return { kind: 'not-found', command: display, detail: result.error.code || result.error.message }
  }

  const stdout = decode(result.stdout).trim()
  const stderr = decode(result.stderr).trim()
  const jsonLine = stdout
    .split(/\r?\n/)
    .reverse()
    .find((line) => line.startsWith('{'))

  if (result.status === 0 && jsonLine) {
    let parsed
    try {
      parsed = JSON.parse(jsonLine)
    } catch {
      return { kind: 'broken', command: display, detail: 'unparsable probe output' }
    }
    const version = String(parsed.version || '')
    const missing = Array.isArray(parsed.missing) ? parsed.missing : []
    return {
      kind: 'found',
      command: display,
      version,
      exe: parsed.exe || '',
      missing,
      errors: parsed.errors || {},
      versionOk: parsed.version_ok !== false,
      detail: missing.length ? `缺少模块 ${missing.join(', ')}` : 'ok',
    }
  }

  // The Microsoft Store alias stub exits non-zero with a "not found, install
  // from the Store" message; report that as "no interpreter", not as broken.
  // `py -3` answers "Requested Python version (3) not installed" on the same
  // machines. A corrupt install ("无法找到入口" / missing DLL) stays broken so
  // the agent forwards the real error instead of asking to install Python again.
  const blob = `${stdout}\n${stderr}`
  if (
    /Microsoft Store|Windows Store|Microsoft 商店/i.test(blob) ||
    /Requested Python version \(3\) not installed|No suitable Python runtime/i.test(blob) ||
    result.status === 9009
  ) {
    return { kind: 'stub', command: display, detail: 'Microsoft Store 别名占位符 / 未安装 Python 3' }
  }

  return {
    kind: 'broken',
    command: display,
    detail:
      result.status === 0
        ? '没有返回探针结果（该命令不是 Python 解释器）'
        : stderr.split(/\r?\n/).find(Boolean) || `exit ${result.status}`,
  }
}

// Preference among interpreters that were found but are not directly usable:
// 2 = the interpreter runs and only the parser modules are missing (fixable
// with one pip command), 1 = the interpreter is too old (needs an upgrade).
// Trying every candidate matters on Windows, where `python` is often an old
// install while `py -3` is the current one; stopping at the first "found"
// candidate would report "too old" on a machine that already has a working
// interpreter further down the list.
function usableRank(attempt) {
  if (attempt.versionOk && attempt.missing.length === 0) return 3
  return attempt.versionOk ? 2 : 1
}

/**
 * Probe the machine. Returns
 * `{ ok, status, command, version, exe, missing, errors, attempts }` where status
 * is one of `ok | no-python | too-old | missing-modules | broken-python`.
 *
 * Every candidate is tried: a usable interpreter anywhere wins outright;
 * otherwise the most usable candidate found is reported. A candidate that
 * exists but cannot run `-c` does not stop the scan either — an old broken
 * install can sit on PATH ahead of a working interpreter.
 */
export function probePython() {
  const attempts = []
  const found = []
  let broken
  for (const candidate of pythonCandidates()) {
    const attempt = runCandidate(candidate)
    attempts.push(attempt)
    if (attempt.kind === 'found') {
      const { kind: _kind, ...facts } = attempt
      const base = { ...facts, attempts, ok: false }
      if (usableRank(attempt) === 3) return { ...base, ok: true, status: 'ok' }
      found.push({ attempt, base })
      continue
    }
    if (attempt.kind === 'broken' && !broken) broken = attempt
  }
  if (found.length) {
    const best = found.reduce((a, b) => (usableRank(b.attempt) > usableRank(a.attempt) ? b : a))
    return {
      ...best.base,
      attempts,
      status: best.attempt.versionOk ? 'missing-modules' : 'too-old',
    }
  }
  if (broken) return { ...broken, attempts, ok: false, status: 'broken-python' }
  return {
    ok: false,
    status: 'no-python',
    attempts,
    missing: [],
    errors: {},
    version: '',
    exe: '',
    detail: '',
    command: pythonCandidates()
      .map((c) => [c.command, ...c.args].join(' '))
      .join(' / '),
  }
}

/** One-line verdict, suitable for logs and for the skill bulletin. */
export function summaryLine(report) {
  switch (report.status) {
    case 'ok':
      return `Python ${report.version}（${report.command}，${report.exe}），tree_sitter / tree_sitter_cpp 可用`
    case 'no-python':
      return `未找到可用的 Python 解释器（已尝试 ${report.command}）`
    case 'too-old':
      return `Python ${report.version} 版本过低（需要 ${MIN_PYTHON.join('.')}+）`
    case 'missing-modules':
      return `Python ${report.version} 可用，但缺少模块 ${report.missing.join(', ')}`
    case 'broken-python':
      return `Python 解释器存在（${report.command}）但无法运行：${report.detail}`
    default:
      return 'Python 探测失败'
  }
}

/**
 * Markdown block prepended to the skill body by index.js. It must be readable
 * by the agent as a hard gate: when the verdict is not OK the agent has to stop
 * instead of calling the scripts.
 */
export function buildSkillNote(report, skillDir = '${SKILL_DIR}') {
  const check = `node "${skillDir}/scripts/check_env.mjs"`
  if (report.ok) {
    return `> 环境自检（插件注册时执行）：✅ ${summaryLine(report)}。\n\n`
  }

  const lines = [`> 环境自检（插件注册时执行）：❌ ${summaryLine(report)}。`]
  switch (report.status) {
    case 'no-python':
      lines.push(
        '> 本技能的全部脚本都是 Python 脚本，没有解释器时**任何注释命令都无法执行**。',
        '> 现在请**立即停止**：不要调用 `scripts/parse_function.py` / `scripts/gen_doxygen.py`，',
        '> 也不要用「没找到函数」之类的说法继续，直接把下面的安装步骤转告用户，等装好后再继续。',
        '>',
        `> ${INSTALL_HINT.split('\n').join('\n> ')}`,
        `> - 验证：\`${check}\`，输出 ✅ 即可使用（重启会话让插件重新探测）。`,
      )
      break
    case 'too-old':
      lines.push(
        `> 已找到 ${report.command}（Python ${report.version}，${report.exe}），但本技能要求 ${MIN_PYTHON.join('.')}+。`,
        '> 请**立即停止**调用脚本，让用户升级 Python 后再继续：',
        `> - 升级到 Python 3.10+：https://www.python.org/downloads/`,
        '> - 升级后重装依赖：`python -m pip install tree-sitter tree-sitter-cpp`',
        `> - 验证：\`${check}\``,
      )
      break
    case 'missing-modules': {
      const detail = report.missing
        .map((mod) => `\`${mod}\`（${report.errors?.[mod] || 'import failed'}）`)
        .join('、')
      lines.push(
        `> 解释器：${report.command} → ${report.exe || '(路径未知)'}；版本 ${report.version}。`,
        `> 失败原因：${detail}`,
        '> 请**立即停止**调用脚本，让用户执行：',
        `> - \`${report.command} -m pip install tree-sitter tree-sitter-cpp\``,
        '> - 若 pip 报 `externally-managed-environment`（PEP 668），改用虚拟环境，',
        '>   或在确认无冲突时加 `--break-system-packages`',
        `> - 验证：\`${check}\``,
      )
      break
    }
    default:
      lines.push(
        `> 解释器 ${report.command} 存在，但执行失败：${report.detail}。`,
        '> 请**立即停止**调用脚本，把该错误转告用户；常见原因是 Store 占位符、',
        '> 权限不足或解释器安装损坏，重装 Python 3.10+ 后重试。',
        `> - 验证：\`${check}\``,
      )
  }
  lines.push('> 若 Python 不在 PATH 上（venv / conda / 绿色版），设置 `DOXYGEN_PYTHON=<解释器绝对路径>` 后重启会话。')
  return `${lines.join('\n')}\n\n`
}
