// Writes each drawing in src/components/activityIcons.js to
// uba/icons/activity/<activity>.svg, so the Qt screens (Behaviour Results,
// the Wing step picker, Settings) show the same icons as the User Behavior
// window. Run after any change to activityIcons.js:
//
//   node scripts/export_activity_svgs.mjs        (from uba/react-uba)
import { mkdirSync, readdirSync, unlinkSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { ACTIVITY_ICONS } from '../src/components/activityIcons.js'

const here = dirname(fileURLToPath(import.meta.url))
const out = join(here, '..', '..', 'icons', 'activity')
mkdirSync(out, { recursive: true })

// A drawing removed from the source must not linger as a stale file.
for (const f of readdirSync(out)) {
  if (f.endsWith('.svg') && !(f.slice(0, -4) in ACTIVITY_ICONS)) unlinkSync(join(out, f))
}
for (const [name, markup] of Object.entries(ACTIVITY_ICONS)) {
  writeFileSync(join(out, `${name}.svg`),
    `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none">${markup}</svg>\n`)
}
console.log(`wrote ${Object.keys(ACTIVITY_ICONS).length} icons to ${out}`)
