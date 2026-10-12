// DSH plugin entry: registers the bundled doxygen-comment skill.
//
// The skill itself is the repository root (SKILL.md plus scripts/, assets/ and
// references/), so installing this bundle needs no file movement: the plugin
// registers the same directory that manual installations copy into a host's
// skills folder.
import { existsSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const name = 'doxygen-comment'
const inject = ['skills']

const FALLBACK_DESCRIPTION =
  '为 C/C++（含 Qt）源码生成与维护 Doxygen 注释（文件头/函数/模块/行尾/简短注释）。'

const here = dirname(fileURLToPath(import.meta.url))
const skillFile = join(here, 'SKILL.md')

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
    ctx.logger?.warn?.(`[${name}] SKILL.md not found at ${skillFile}`)
    return
  }

  const { meta, body } = parseFrontmatter(readFileSync(skillFile, 'utf8'))
  const content = body.trimStart()
  if (!content) {
    ctx.logger?.warn?.(`[${name}] SKILL.md has no body`)
    return
  }

  // The skill body refers to ${SKILL_DIR}; a plugin install lives under the
  // profile's node_modules, so resolve it here instead of guessing a host
  // variable name.
  const resolved = `> 运行时路径：本技能由 DSH 插件 \`dsh-doxygen\` 安装，\`\${SKILL_DIR}\` = \`${here}\`。\n\n`

  ctx.skills.register({
    name: meta.name || name,
    description: meta.description || FALLBACK_DESCRIPTION,
    ...(meta.whenToUse ? { whenToUse: meta.whenToUse } : {}),
    content: resolved + content,
    source: 'runtime',
    resourceBase: { kind: 'directory', path: here },
    metadata: {
      package: 'dsh-doxygen',
      bundled: ['SKILL.md', 'scripts', 'assets', 'references'],
    },
  })
}

export { apply, inject, name }
export default { name, inject, apply }
