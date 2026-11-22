/**
 * JS oracle：用 dsh-scribble 的 Renderer 画同一份场景。
 * 只用于对照，不进产品。
 */
import { readFileSync, writeFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const ROOT = resolve(HERE, '..', '..')
const SCRIBBLE = resolve(ROOT, '..', 'draw-plan', 'dsh-scribble-review', 'lib')

const { Renderer } = await import(pathToFileURL(resolve(SCRIBBLE, 'render.js')).href)
const { resolveStyle } = await import(pathToFileURL(resolve(SCRIBBLE, 'style.js')).href)

const scenePath = process.argv[2] || resolve(HERE, 'm0_scene.json')
const outPath = process.argv[3] || resolve(ROOT, 'renders', 'm0-js.png')
const scene = JSON.parse(readFileSync(scenePath, 'utf8'))

const style = resolveStyle('ink', null)
const [W, H] = scene.canvas
const r = new Renderer({ width: W, height: H, style, seed: scene.seed, paper: scene.paper, scale: 2 })

for (const s of scene.strokes) {
  r.stroke(s.points, {
    color: s.color,
    width: s.width,
    alpha: s.alpha ?? 1,
    jitter: s.jitter,
    roughness: s.roughness,
    taper: s.taper,
    overshoot: s.overshoot === null ? undefined : s.overshoot,
    closed: Boolean(s.closed),
  })
}

writeFileSync(outPath, r.canvas.toPng())
console.log(`js  ops=${r.opCount}  -> ${outPath}`)
