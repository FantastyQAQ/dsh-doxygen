#!/usr/bin/env node
// Manual / diagnostic entry point for the environment probe.
//
// The DSH plugin runs the same probe at registration and writes the verdict to
// the top of SKILL.md, so this script exists for two cases:
//   1. manual installations (skill copied into a host's skills folder, no
//      index.js to inject the bulletin), and
//   2. re-checking after the user installed Python or the parser modules.
//
// Exit codes: 0 = usable, 2 = no Python at all, 3 = Python found but unusable
// (too old, modules missing, interpreter broken).

import { probePython, summaryLine, pythonCandidates, MIN_PYTHON } from './lib/env.mjs'

const argv = process.argv.slice(2)
const asJson = argv.includes('--json')
const forced = argv.find((arg) => arg === '--command') ? argv[argv.indexOf('--command') + 1] : null

if (argv.includes('-h') || argv.includes('--help')) {
  console.log('用法: node check_env.mjs [--json] [--command <python 命令或绝对路径>]')
  console.log('  退出码 0=可用 2=未安装 Python 3=已安装但不可用（版本过低/缺模块/解释器损坏）')
  process.exit(0)
}

if (forced) process.env.DOXYGEN_PYTHON = forced

const report = probePython()
const exitCode = report.ok ? 0 : report.status === 'no-python' ? 2 : 3

if (asJson) {
  console.log(JSON.stringify({ ...report, exitCode }, null, 2))
  process.exit(exitCode)
}

const icon = report.ok ? '✅' : '❌'
console.log('doxygen-comment 环境自检')
console.log(`  结论     : ${icon} ${summaryLine(report)}`)
console.log(`  需要     : Python ${MIN_PYTHON.join('.')}+ 且已安装 ${'tree_sitter, tree_sitter_cpp'}`)
if (report.version) console.log(`  解释器   : ${report.command} → ${report.exe || '(unknown)'}`)
if (report.version) console.log(`  版本     : ${report.version}`)
if (report.missing?.length) console.log(`  缺失模块 : ${report.missing.join(', ')}`)
if (report.attempts?.length && !report.ok) {
  for (const attempt of report.attempts) {
    console.log(`  已尝试   : ${attempt.command} → ${attempt.kind}${attempt.detail ? ` (${attempt.detail})` : ''}`)
  }
} else if (!report.ok && !report.attempts?.length) {
  console.log(`  已尝试   : ${pythonCandidates().map((c) => [c.command, ...c.args].join(' ')).join(' / ')}`)
}

if (!report.ok) {
  console.log('')
  if (report.status === 'no-python') {
    console.log('安装步骤：')
    console.log('  1. 安装 Python 3.10+：https://www.python.org/downloads/')
    console.log('     Windows 安装时勾选 “Add python.exe to PATH”；macOS: brew install python；')
    console.log('     Ubuntu/Debian: sudo apt install python3 python3-pip')
    console.log('  2. 安装解析依赖：python -m pip install tree-sitter tree-sitter-cpp')
    console.log('  3. 重新验证：node check_env.mjs')
  } else if (report.status === 'too-old') {
    console.log('请升级到 Python 3.10+：https://www.python.org/downloads/')
  } else if (report.status === 'missing-modules') {
    console.log('请安装/修复解析依赖：')
    console.log(`  ${report.command} -m pip install tree-sitter tree-sitter-cpp`)
    for (const [mod, error] of Object.entries(report.errors || {})) {
      console.log(`     ${mod}: ${error}`)
    }
  } else {
    console.log('解释器存在但执行失败，请重装 Python 3.10+ 后重试。')
  }
  console.log('')
  console.log('Python 不在 PATH 上时，可设置 DOXYGEN_PYTHON=<解释器绝对路径> 后再运行。')
}

process.exit(exitCode)
