/**
 * 数值 oracle：把 scribble 真正送进光栅器的最终点列与逐点笔宽吐出来。
 * 做法是把 canvas.polyline 换掉，捕获即可——不重写它的数学。
 */
import { readFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const ROOT = resolve(HERE, '..', '..')
const SCRIBBLE = resolve(ROOT, '..', 'draw-plan', 'dsh-scribble-review', 'lib')

const { Renderer } = await import(pathToFileURL(resolve(SCRIBBLE, 'render.js')).href)
const { resolveStyle } = await import(pathToFileURL(resolve(SCRIBBLE, 'style.js')).href)

const scenePath = process.argv[2] || resolve(HERE, 'm0_scene.json')
const scene = JSON.parse(readFileSync(scenePath, 'utf8'))

const style = resolveStyle('ink', null)
const [W, H] = scene.canvas
const r = new Renderer({ width: W, height: H, style, seed: scene.seed, paper: scene.paper, scale: 1 })

const captured = []
r.canvas.polyline = (pts, widths) => { captured.push({ pts, widths }) }
r.svg.path = () => {}

for (const s of scene.strokes) {
  r.stroke(s.points, {
    color: s.color, width: s.width, alpha: s.alpha ?? 1,
    jitter: s.jitter, roughness: s.roughness, taper: s.taper,
    overshoot: s.overshoot === null ? undefined : s.overshoot,
    closed: Boolean(s.closed),
  })
}

process.stdout.write(JSON.stringify(captured))
