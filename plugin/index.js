/**
 * 小飞鱼画板 · Host
 *
 * 干三件事：
 *  1. 给 Agent 一个工具 fyb_draw（渲染/生成逐笔动画），并把进度写到 .state/progress.json
 *  2. 给网页三条只读路由：gallery / image / state
 *  3. 不碰任何宿主状态，出问题只影响这个插件的面板
 */
import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import { createReadStream } from 'node:fs'
import { basename, dirname, extname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const PROJECT = resolve(HERE, '..')            // dsh-feiyu-board/
const SCENES = join(PROJECT, 'scenes')
const RENDERS = join(PROJECT, 'renders')
const STATE = join(PROJECT, '.state')
const PROGRESS = join(STATE, 'progress.json')

/**
 * 找 Python：不再写死 `.venv\Scripts\python.exe`。
 *
 * 顺序（先到先用）：
 *   1. 环境变量 FYB_PYTHON —— 想指定某个解释器就设它
 *   2. 画板目录里的 venv（Windows / POSIX 两种布局）
 *   3. PATH 上的 python / python3 / py -3
 *
 * 找不到就把 null 留着，工具调用时给一句人话提示，而不是 spawn 失败报 ENOENT。
 */
function findPython() {
  const env = (process.env.FYB_PYTHON || '').trim()
  const cands = []
  if (env) cands.push(env)
  cands.push(
    join(PROJECT, '.venv', 'Scripts', 'python.exe'),   // Windows venv
    join(PROJECT, '.venv', 'bin', 'python'),           // POSIX venv
    join(PROJECT, '.venv', 'bin', 'python3'),
  )
  for (const c of cands) {
    if (existsSync(c)) return c
  }
  // PATH 上的通用解释器：让 spawn 自己解析名字
  return process.platform === 'win32' ? 'python' : 'python3'
}

const PYTHON = findPython()

function pythonHint() {
  return [
    '没找到能用的 Python。',
    `期望位置：${join(PROJECT, '.venv', 'Scripts', 'python.exe')}（Windows）`,
    '或 .venv/bin/python（macOS / Linux）。',
    '做法：在画板目录双击 安装.cmd（Windows）/ 跑 python -m venv .venv 再装依赖；',
    '或者设环境变量 FYB_PYTHON 指向任意装了 requirements.txt 的解释器。',
  ].join('\n')
}

/** 解释器看着可用吗？（PATH 上的名字没法便宜地验，交给 spawn 报错） */
function pythonLooksAvailable() {
  if (!PYTHON) return false
  const isPath = PYTHON.includes('/') || PYTHON.includes('\\')
  return isPath ? existsSync(PYTHON) : true
}



export const inject = ['webServer', 'tools']

const sendJson = (res, data, code = 200) => {
  const body = JSON.stringify(data)
  res.writeHead(code, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
  })
  res.end(body)
}

function writeProgress(patch) {
  try {
    mkdirSync(STATE, { recursive: true })
    const now = { at: Date.now(), ...patch }
    writeFileSync(PROGRESS, JSON.stringify(now), 'utf8')
  } catch { /* 进度写不进去不影响出图 */ }
}

function listRenders(limit = 12) {
  if (!existsSync(RENDERS)) return []
  const out = []
  for (const name of readdirSync(RENDERS)) {
    if (!/\.(png|jpe?g|apng)$/i.test(name)) continue
    if (name.startsWith('_')) continue          // _preview.png 单独在预览区，不进画库
    const full = join(RENDERS, name)
    try {
      const st = statSync(full)
      if (!st.isFile()) continue
      out.push({ name, bytes: st.size, mtime: st.mtimeMs })
    } catch { /* 单个文件读不到就跳过 */ }
  }
  out.sort((a, b) => b.mtime - a.mtime)
  return out.slice(0, limit)
}

function safeName(raw) {
  const name = basename(String(raw || ''))
  if (!name || name.startsWith('.')) return null
  if (!/\.(png|jpe?g|apng)$/i.test(name)) return null
  return join(RENDERS, name)
}

function run(args, timeoutMs = 180000) {
  return new Promise((done) => {
    const child = spawn(PYTHON, ['-m', 'fyb', ...args], {
      cwd: PROJECT,
      windowsHide: true,
      env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
    })
    let stdout = ''
    let stderr = ''
    const timer = setTimeout(() => { try { child.kill() } catch { /* 已退出 */ } }, timeoutMs)
    child.stdout.on('data', (d) => { stdout += d.toString('utf8') })
    child.stderr.on('data', (d) => { stderr += d.toString('utf8') })
    child.on('error', (err) => {
      clearTimeout(timer)
      done({ code: -1, stdout, stderr: `${String(err)}\n${pythonHint()}` })
    })
    child.on('close', (code) => { clearTimeout(timer); done({ code, stdout, stderr }) })
  })
}

function resolveScene(raw) {
  const text = String(raw || '').trim()
  if (!text) return null
  const candidates = [text, join(SCENES, text), join(SCENES, `${text}.fyb`)]
  for (const c of candidates) {
    const full = resolve(PROJECT, c)
    if (existsSync(full) && /\.fyb$/i.test(full)) return full
  }
  return null
}

export function apply(ctx) {
  // ── 实时预览 ─────────────────────────────────────────────
  // 插件一加载就起 watcher：预览不该取决于"你正看着哪一页"。
  // 插件卸载时 kill 掉，不留孤儿进程；/preview 路由还会顺手自愈。
  const PREVIEW_JSON = join(STATE, 'preview.json')
  let watcher = null

  const ensureWatcher = () => {
    if (watcher && watcher.exitCode === null) return true
    if (!pythonLooksAvailable() || !existsSync(SCENES)) return false
    try {
      watcher = spawn(PYTHON, ['-m', 'fyb', 'watch', SCENES, '--scale', '1'],
        { cwd: PROJECT, windowsHide: true,
          env: { ...process.env, PYTHONIOENCODING: 'utf-8' } })
      watcher.on('exit', () => { watcher = null })
      watcher.on('error', () => { watcher = null })
      return true
    } catch {
      watcher = null
      return false
    }
  }

  ctx.effect(() => {
    ensureWatcher()
    return () => {
      try { if (watcher) watcher.kill() } catch { /* 已经退了 */ }
      watcher = null
    }
  }, 'feiyu-board: watcher')

  const route = (path, tag, handler) => ctx.effect(() => ctx.webServer.register({
    kind: 'exact',
    path,
    handler: async (req, res) => {
      try {
        await handler(req, res)
      } catch (err) {
        sendJson(res, { ok: false, error: String(err?.message ?? err) }, 500)
      }
    },
  }), `feiyu-board: ${tag}`)

  route('/dsh-feiyu-board/gallery', 'gallery', async (req, res) => {
    sendJson(res, { ok: true, items: listRenders(12) })
  })

  route('/dsh-feiyu-board/state', 'state', async (req, res) => {
    let progress = null
    try {
      progress = JSON.parse(readFileSync(PROGRESS, 'utf8'))
    } catch { /* 没有进度文件就是空闲 */ }
    const running = progress && progress.running && Date.now() - progress.at < 300000
    sendJson(res, { ok: true, running: Boolean(running), progress })
  })

  route('/dsh-feiyu-board/preview', 'preview', async (req, res) => {
    const alive = ensureWatcher()
    let status = null
    try {
      status = JSON.parse(readFileSync(PREVIEW_JSON, 'utf8'))
    } catch { /* 还没画过 */ }
    const fresh = status && Date.now() - Number(status.at || 0) < 120000
    sendJson(res, {
      ok: true,
      watching: alive,
      has: Boolean(status) && existsSync(join(RENDERS, '_preview.png')),
      status: fresh ? status : null,
    })
  })

  route('/dsh-feiyu-board/image', 'image', async (req, res) => {
    const url = new URL(req.url, 'http://local')
    const full = safeName(url.searchParams.get('name'))
    if (!full || !existsSync(full)) return sendJson(res, { ok: false, error: '没有这张' }, 404)
    const type = extname(full).toLowerCase() === '.png' || full.endsWith('.apng')
      ? 'image/png'
      : 'image/jpeg'
    res.writeHead(200, { 'content-type': type, 'cache-control': 'no-cache' })
    createReadStream(full).pipe(res)
  })

  // ── 工具：画一张 ──────────────────────────────────────────
  ctx.effect(() => ctx.tools.register({
    name: 'fyb_draw',
    description: '用小飞鱼画板渲染一张 .fyb 场景（可生成逐笔动画）。返回 PNG 路径，画会自动进画库。'
      + '不确定 DSL 怎么写就先调 fyb_doc；场景文件放在工程的 scenes/ 下，用 fyb_scenes 看现有的。',
    parameters: {
      type: 'object',
      properties: {
        scene: { type: 'string', description: '场景名（如 rain-window）或 .fyb 的绝对路径' },
        scale: { type: 'integer', description: '超采样倍率，默认 2（输出 = 画布 × 倍率）' },
        anim: { type: 'boolean', description: 'true = 顺便生成逐笔动画（APNG）' },
        out: { type: 'string', description: '输出文件名（放在 renders/ 下），默认同场景名' },
        under: { type: 'string', description: '临摹用：垫在最下面的参考图绝对路径' },
      },
      required: ['scene'],
      additionalProperties: false,
    },
    output: {
      schema: { type: 'object', additionalProperties: true },
      render: (_a, v) => [{ type: 'text', text: String(v?.summary || '') }],
    },
    async execute(args) {
      const a = args || {}
      const scene = resolveScene(a.scene)
      if (!scene) {
        const names = existsSync(SCENES)
          ? readdirSync(SCENES).filter((n) => n.endsWith('.fyb')).map((n) => n.replace(/\.fyb$/, ''))
          : []
        return { ok: false, summary: `找不到场景 ${a.scene}。现有：${names.join(', ') || '（空）'}` }
      }
      const stem = a.out ? String(a.out).replace(/\.(png|apng)$/i, '') : basename(scene, '.fyb')
      const png = join(RENDERS, `${stem}.png`)
      const scale = Math.max(1, Math.min(4, Number(a.scale) || 2))
      const argsList = ['render', scene, '--out', png, '--scale', String(scale)]
      if (a.under) argsList.push('--under', String(a.under))

      writeProgress({ running: true, scene, note: '正在画', done: 0, total: 1 })
      const t0 = Date.now()
      const r = await run(argsList)
      const ms = Date.now() - t0

      if (r.code !== 0 || !existsSync(png)) {
        const msg = (r.stdout + r.stderr).trim().split('\n').slice(-6).join('\n') || `退出码 ${r.code}`
        writeProgress({ running: false, scene, note: '失败', error: msg })
        return { ok: false, summary: `画失败：\n${msg}` }
      }

      let animPath = null
      if (a.anim) {
        animPath = join(RENDERS, `${stem}.apng`)
        writeProgress({ running: true, scene, note: '正在生成逐笔动画', done: 0, total: 1 })
        await run(['anim', scene, '--out', animPath, '--scale', '1'], 300000)
      }

      writeProgress({ running: false, scene, note: '完成', done: 1, total: 1, ms, png })
      const size = (statSync(png).size / 1024).toFixed(0)
      return {
        ok: true,
        png,
        anim: animPath,
        ms,
        summary: `画好了：${png}（${size} KB，${ms} ms）${animPath ? `\n逐笔动画：${animPath}` : ''}`,
      }
    },
  }), 'feiyu-board: fyb_draw')

  // ── 工具：让任何会话都能自己学会怎么画 ────────────────────
  ctx.effect(() => ctx.tools.register({
    name: 'fyb_doc',
    description: '返回小飞鱼画板的 DSL 速查（命令表、属性范围、五种构图套路、五条必知、已知边界）。'
      + '第一次用这个画板、或者不确定某个命令怎么写的时候，先调它。',
    parameters: { type: 'object', properties: {}, additionalProperties: false },
    output: {
      schema: { type: 'object', additionalProperties: true },
      render: (_a, v) => [{ type: 'text', text: String(v?.summary || '') }],
    },
    async execute() {
      const file = join(PROJECT, 'DSL.md')
      if (!existsSync(file)) {
        return { ok: false, summary: 'DSL.md 不见了：' + file }
      }
      const doc = readFileSync(file, 'utf8')
      return { ok: true, path: file, summary: doc }
    },
  }), 'feiyu-board: fyb_doc')

  ctx.effect(() => ctx.tools.register({
    name: 'fyb_scenes',
    description: '列出小飞鱼画板里现有的场景文件。',
    parameters: { type: 'object', properties: {}, additionalProperties: false },
    output: {
      schema: { type: 'object', additionalProperties: true },
      render: (_a, v) => [{ type: 'text', text: String(v?.summary || '') }],
    },
    async execute() {
      if (!existsSync(SCENES)) return { ok: true, scenes: [], summary: '还没有场景' }
      const scenes = readdirSync(SCENES)
        .filter((n) => n.endsWith('.fyb'))
        .map((n) => {
          const st = statSync(join(SCENES, n))
          return { name: n.replace(/\.fyb$/, ''), mtime: st.mtimeMs }
        })
        .sort((x, y) => y.mtime - x.mtime)
      return {
        ok: true,
        scenes,
        summary: scenes.length
          ? `现有场景：${scenes.map((s) => s.name).join(', ')}`
          : '还没有场景',
      }
    },
  }), 'feiyu-board: fyb_scenes')

  // ── 只编译不渲染：写完场景先自检，别等一分钟后才发现写错 ���─────────
  ctx.effect(() => ctx.tools.register({
    name: 'fyb_check',
    description: '只编译 .fyb 不渲染，用来快速自查语法。返回错误列表（带行号和错误码）；'
      + '全部通过时 ok=true。改完场景先跑这个，比渲染快一个数量级。',
    parameters: {
      type: 'object',
      properties: {
        scene: { type: 'string', description: '场景名（如 apple）或 .fyb 的完整路径' },
      },
      required: ['scene'],
      additionalProperties: false,
    },
    output: {
      schema: { type: 'object', additionalProperties: true },
      render: (_a, v) => [{ type: 'text', text: String(v?.summary || '') }],
    },
    async execute(args) {
      const scene = resolveScene((args || {}).scene)
      if (!scene) return { ok: false, summary: `找不到场景 ${args?.scene}` }
      const r = await run(['check', scene], 60000)
      const text = (r.stdout + r.stderr).trim()
      return {
        ok: r.code === 0,
        output: text,
        summary: r.code === 0
          ? `✓ 编译通过\n${text.split('\n').slice(0, 3).join('\n')}`
          : `✗ 有错\n${text}`,
      }
    },
  }), 'feiyu-board: fyb_check')

  // ── 图元统计：画错了先看数字对不对 ─────────────────────────
  ctx.effect(() => ctx.tools.register({
    name: 'fyb_meta',
    description: '打印场景的图元统计（画布大小、图元总数、各类型数量、编译耗时）。'
      + '画出来不对时可以拿它核对"该有的东西有没有生成"。',
    parameters: {
      type: 'object',
      properties: {
        scene: { type: 'string', description: '场景名或 .fyb 的完整路径' },
      },
      required: ['scene'],
      additionalProperties: false,
    },
    output: {
      schema: { type: 'object', additionalProperties: true },
      render: (_a, v) => [{ type: 'text', text: String(v?.summary || '') }],
    },
    async execute(args) {
      const scene = resolveScene((args || {}).scene)
      if (!scene) return { ok: false, summary: `找不到场景 ${args?.scene}` }
      const r = await run(['meta', scene], 60000)
      const text = (r.stdout + r.stderr).trim()
      if (r.code !== 0) return { ok: false, output: text, summary: `读不了：\n${text}` }
      // meta 吐的是 JSON；摘要要给人看的角度重排一下，别把原始 JSON 当摘要
      let m = null
      try { m = JSON.parse(text) } catch { /* 不是 JSON 就退回原文 */ }
      if (!m || !m.canvas) return { ok: true, output: text, summary: text.slice(0, 800) }
      const parts = Object.entries(m.prims || {})
        .sort((a, b) => b[1] - a[1])
        .map(([k, n]) => `${k} ${n}`)
        .join(' / ')
      const names = (m.names || []).join(', ')
      const summary = [
        `${m.canvas[0]}×${m.canvas[1]} · ${m.total} 个图元`,
        parts,
        names ? `命名：${names}` : '',
      ].filter(Boolean).join('\n')
      return { ok: true, output: text, meta: m, summary }
    },
  }), 'feiyu-board: fyb_meta')

  // ── 参考图 → 场景：临摹用 ────────────────────────────────
  ctx.effect(() => ctx.tools.register({
    name: 'fyb_trace',
    description: '把参考图（照片/线稿）追踪成 .fyb 场景，得到可编辑的点列。'
      + 'mode=skeleton 适合线稿（得到笔画中线），mode=contour 适合照片（得到物体外缘）。'
      + '临摹时先用它把位置拿到，再按自己的笔重画。',
    parameters: {
      type: 'object',
      properties: {
        image: { type: 'string', description: '参考图的完整路径' },
        out: { type: 'string', description: '输出场景名（不含 .fyb）' },
        mode: { type: 'string', enum: ['skeleton', 'contour'], description: '默认 skeleton' },
        threshold: { type: 'number', description: '0~1；骨架默认 0.86，传 0 用 Otsu' },
        invert: { type: 'boolean', description: '亮的当墨（黑底线稿用）' },
      },
      required: ['image', 'out'],
      additionalProperties: false,
    },
    output: {
      schema: { type: 'object', additionalProperties: true },
      render: (_a, v) => [{ type: 'text', text: String(v?.summary || '') }],
    },
    async execute(args) {
      const a = args || {}
      const outPath = join(SCENES, `${String(a.out).replace(/\.fyb$/, '')}.fyb`)
      const argv = ['trace', String(a.image), '--out', outPath,
        '--mode', a.mode === 'contour' ? 'contour' : 'skeleton']
      if (a.threshold != null) argv.push('--threshold', String(a.threshold))
      if (a.invert) argv.push('--invert')
      const r = await run(argv, 180000)
      const text = (r.stdout + r.stderr).trim()
      return { ok: r.code === 0, scene: outPath, summary: text.split('\n').slice(-2).join('\n') }
    },
  }), 'feiyu-board: fyb_trace')

  // ── 换笔参数批量出图：挑手感 ─────────────────────────────
  ctx.effect(() => ctx.tools.register({
    name: 'fyb_sweep',
    description: '把同一个场景的一个笔参数换成几个值，批量渲染拼成一张对照图。'
      + 'set 写 "key=v1,v2"，key 可以是 preset（clean/ink/pencil/brush/child/messy）'
      + '或数值参数（jitter / taper / width / rough…）。用来看"哪种笔更对"。',
    parameters: {
      type: 'object',
      properties: {
        scene: { type: 'string', description: '场景名或 .fyb 的完整路径' },
        set: {
          type: 'string',
          description: '要扫的参数，如 "preset=ink,pencil,messy" 或 "jitter=0.3,0.6,0.9"'
            + '（默认 preset=ink,pencil,brush）',
        },
        cols: { type: 'integer', description: '每行几格（默认 3）' },
      },
      required: ['scene'],
      additionalProperties: false,
    },
    output: {
      schema: { type: 'object', additionalProperties: true },
      render: (_a, v) => [{ type: 'text', text: String(v?.summary || '') }],
    },
    async execute(args) {
      const a = args || {}
      const scene = resolveScene(a.scene)
      if (!scene) return { ok: false, summary: `找不到场景 ${a.scene}` }
      const stem = basename(scene, '.fyb')
      const out = join(RENDERS, `${stem}-sweep.png`)
      const argv = ['sweep', scene, '--out', out,
        '--set', String(a.set || 'preset=ink,pencil,brush')]
      if (a.cols) argv.push('--cols', String(a.cols))
      const r = await run(argv, 300000)
      const text = (r.stdout + r.stderr).trim()
      return { ok: r.code === 0, png: out, summary: text.split('\n').slice(-2).join('\n') }
    },
  }), 'feiyu-board: fyb_sweep')

  // ── 图片 → 按颜色分层的场景（色块分明的插画/图标）───────────
  ctx.effect(() => ctx.tools.register({
    name: 'fyb_posterize',
    description: '把一张参考图按颜色分层、矢量化成 .fyb 场景。'
      + '适合**色块分明的插画/图标**（不适合照片和渐变多的图）。'
      + '产出的场景可继续用 fyb_draw 渲染，也可手改。'
      + '颜色数是最常调的：人物脸发白就往上加（28~32）。',
    parameters: {
      type: 'object',
      properties: {
        image: { type: 'string', description: '参考图的完整路径' },
        out: { type: 'string', description: '输出场景名（不含 .fyb），默认用图名' },
        colors: { type: 'integer', description: '量化成几种颜色，默认 24；人物建议 28~32' },
        height: { type: 'integer', description: '输出画布高度，默认 1200' },
        eps: { type: 'number', description: '轮廓简化容差，默认 1.8' },
      },
      required: ['image'],
      additionalProperties: false,
    },
    output: {
      schema: { type: 'object', additionalProperties: true },
      render: (_a, v) => [{ type: 'text', text: String(v?.summary || '') }],
    },
    async execute(args) {
      const a = args || {}
      const stem = a.out ? String(a.out).replace(/\.fyb$/, '') : basename(a.image, extname(a.image))
      const outPath = join(SCENES, `${stem}.fyb`)
      const argv = ['posterize', String(a.image), '--out', outPath]
      if (a.colors) argv.push('--colors', String(a.colors))
      if (a.height) argv.push('--height', String(a.height))
      if (a.eps != null) argv.push('--eps', String(a.eps))
      const r = await run(argv, 300000)
      const text = (r.stdout + r.stderr).trim()
      return {
        ok: r.code === 0,
        scene: outPath,
        summary: r.code === 0
          ? `生成了场景 ${stem}.fyb\n${text.split('\n').slice(-2).join('\n')}`
          : `失败：\n${text}`,
      }
    },
  }), 'feiyu-board: fyb_posterize')

  // ── 构图体检：覆盖率网格 + 重心 + 空角 ──────────────────────
  ctx.effect(() => ctx.tools.register({
    name: 'fyb_balance',
    description: '构图体检：把画面切成网格，量每格"有墨"的占比，报出哪几格是空的、'
      + '重心偏没偏。并出一张叠了三分线的标注图。'
      + '**判断"这张画空不空"就靠它**——别凭感觉。',
    parameters: {
      type: 'object',
      properties: {
        scene: { type: 'string', description: '场景名或 .fyb 的完整路径' },
        cells: { type: 'string', description: '网格，默认 "4x3"（列x行，2~8）' },
        grid: {
          type: 'string',
          enum: ['thirds', 'golden', 'none'],
          description: '叠哪种构图线，默认三分',
        },
      },
      required: ['scene'],
      additionalProperties: false,
    },
    output: {
      schema: { type: 'object', additionalProperties: true },
      render: (_a, v) => [{ type: 'text', text: String(v?.summary || '') }],
    },
    async execute(args) {
      const a = args || {}
      const scene = resolveScene(a.scene)
      if (!scene) return { ok: false, summary: `找不到场景 ${a.scene}` }
      const stem = basename(scene, '.fyb')
      const out = join(RENDERS, `_balance_${stem}.png`)
      const argv = ['balance', scene, '--out', out,
        '--cells', String(a.cells || '4x3'),
        '--grid', String(a.grid || 'thirds')]
      const r = await run(argv, 180000)
      const text = (r.stdout + r.stderr).trim()
      return { ok: r.code === 0, png: out, summary: text }
    },
  }), 'feiyu-board: fyb_balance')
}
