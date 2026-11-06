// DSH plugin entry: registers the bundled doxygen-comment skill.
//
// The skill itself is the repository root (SKILL.md plus scripts/, assets/ and
// references/), so installing this bundle needs no file movement: the plugin
// registers the same directory that manual installations copy into a host's
// skills folder.
import { existsSync, readFileSync } from 'node:fs'
import { dirname, join, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

import { buildSkillNote, probePython } from './scripts/lib/env.mjs'

const name = 'doxygen-comment'
const inject = ['skills']

const FALLBACK_DESCRIPTION =
  '为 C/C++（含 Qt）源码生成与维护 Doxygen 注释（文件头/函数/模块/行尾/简短注释）。'

const here = dirname(fileURLToPath(import.meta.url))
const skillFile = join(here, 'SKILL.md')

// `here` is a native path; the host's skill contract addresses resources with
// POSIX separators (its own reference plugins normalize the same way), so
// publish the forward-slash spelling and keep `${SKILL_DIR}` readable in both.
const base = here.split(sep).join('/')

/** Minimal frontmatter reader: scalar keys only, which is all SKILL.md uses. */
function parseFrontmatter(text) {
  const match = /^---\r?\n([\s\S]*?)\r?\n---[ \t]*\r?\n?/.exec(text)
  if (!match) return { meta: {}, body: text }
  const meta = {}
  for (const line of match[1].split(/\r?\n/)) {
    const kv = /^([A-Za-z0-9_-]+):[ \t]*(.*)$/.exec(line)
    if (!kv) continue
    let value = kv[2].trim()
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1)
    }
    meta[kv[1]] = value
  }
  return { meta, body: text.slice(match[0].length) }
}

function apply(ctx) {
  if (!existsSync(skillFile)) {
    ctx.get('logger')?.warn?.(`[${name}] SKILL.md not found at ${skillFile}`)
    return
  }

  const { meta, body } = parseFrontmatter(readFileSync(skillFile, 'utf8'))
  const content = body.trimStart()
  if (!content) {
    ctx.get('logger')?.warn?.(`[${name}] SKILL.md has no body`)
    return
  }

  // The skill body refers to ${SKILL_DIR}; a plugin install lives under the
  // profile's node_modules, so resolve it here instead of guessing a host
  // variable name.
  const resolved = `> 运行时路径：本技能由 DSH 插件 \`dsh-doxygen\` 安装，\`\${SKILL_DIR}\` = \`${base}\`。\n\n`

  // Every script of the skill is Python. On a machine without a Python
  // interpreter the agent would otherwise hit an OS-specific shell error and
  // carry on as if the function was simply "not found". Probe once here and put
  // the verdict at the very top of the skill body, where it cannot be missed.
  let envNote = ''
  try {
    const report = probePython()
    envNote = buildSkillNote(report, base)
    if (!report.ok) {
      ctx.get('logger')?.warn?.(`[${name}] Python 环境自检未通过（${report.status}）：${report.command}`)
    }
  } catch (error) {
    // A probe failure must never take the plugin down: keep the skill usable and
    // let the agent run scripts/check_env.mjs itself.
    ctx.get('logger')?.warn?.(`[${name}] Python 探测失败：${error?.message || error}`)
  }

  // Registrations are effects: the registry keeps its layer entry on the
  // dsh-skill context, so a bare register() call would outlive this plugin
  // (HMR, disable/re-enable) and keep serving the old SKILL.md. Wrapping it in
  // ctx.effect() gives the plugin its own disposer, as the contract requires.
  return ctx.effect(() =>
    ctx.skills.register({
      name: meta.name || name,
      description: meta.description || FALLBACK_DESCRIPTION,
      ...(meta.whenToUse ? { whenToUse: meta.whenToUse } : {}),
      content: envNote + resolved + content,
      source: 'runtime',
      resourceBase: { kind: 'directory', path: base },
      metadata: {
        package: 'dsh-doxygen',
        bundled: ['SKILL.md', 'scripts', 'assets', 'references'],
      },
    }),
  )
}

export { apply, inject, name }
export default { name, inject, apply }
