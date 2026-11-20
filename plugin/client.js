/**
 * 小飞鱼画板 · Client
 *
 * 和「记忆日记」同一个套路：左边栏一个图标，点开是中间一整块面板。
 * 面板里是画库（网格），点一张在新标签页看原图。
 *
 * 仍然是只读：所有数据从 /dsh-feiyu-board/* 拿，写操作只有 Host 那两个工具。
 */
window.__ModuleLoader__.load({
  id: '@local/dsh-feiyu-board',
  factory(require) {
    const React = require('react')
    const h = React.createElement
    const { useCallback, useEffect, useState } = React

    const B = '/dsh-feiyu-board'
    const get = (p) => fetch(B + p, { cache: 'no-store' }).then((r) => r.json())

    const CSS = `
.fyb-root { height: 100%; display: flex; flex-direction: column; color: var(--dsw-alias-label-primary, inherit); font-size: 13px; background: var(--dsw-alias-bg-base, transparent); }
.fyb-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; padding: 18px 22px 10px; max-width: 1180px; width: 100%; box-sizing: border-box; }
.fyb-title { font-size: 18px; font-weight: 600; letter-spacing: .3px; }
.fyb-sub { margin-top: 4px; font-size: 12px; color: var(--dsw-alias-label-secondary, #888); }
.fyb-actions { display: flex; gap: 8px; align-items: center; }
.fyb-btn { padding: 5px 12px; border-radius: 7px; border: 1px solid var(--dsw-alias-border-l2, rgba(128,128,128,.35)); background: transparent; color: inherit; cursor: pointer; font-size: 12px; line-height: 1.6; }
.fyb-btn:hover { background: var(--dsw-alias-bg-layer-2, rgba(128,128,128,.10)); }
.fyb-body { flex: 1; overflow: auto; padding: 8px 22px 40px; max-width: 1180px; width: 100%; box-sizing: border-box; }
.fyb-pv { margin: 0 0 16px; border: 1px solid var(--dsw-alias-border-l1, rgba(128,128,128,.2)); border-radius: 12px; overflow: hidden; background: var(--dsw-alias-bg-layer-1, rgba(128,128,128,.05)); }
.fyb-pv-img { display: block; width: 100%; max-height: 46vh; object-fit: contain; background: rgba(128,128,128,.06); }
.fyb-pv-bar { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 7px 12px; font-size: 12px; border-top: 1px solid var(--dsw-alias-border-l1, rgba(128,128,128,.18)); }
.fyb-pv-err { padding: 8px 12px; font-size: 12px; line-height: 1.6; color: var(--dsw-alias-state-error-primary, #b04040); border-top: 1px solid var(--dsw-alias-border-l1, rgba(128,128,128,.18)); white-space: pre-wrap; }
.fyb-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 14px; }
.fyb-card { border: 1px solid var(--dsw-alias-border-l1, rgba(128,128,128,.2)); border-radius: 10px; overflow: hidden; background: var(--dsw-alias-bg-layer-1, rgba(128,128,128,.05)); cursor: pointer; transition: border-color .12s ease; }
.fyb-card:hover { border-color: var(--dsw-alias-brand-primary, #4f7cff); }
.fyb-thumb { display: block; width: 100%; aspect-ratio: 16 / 9; object-fit: cover; background: rgba(128,128,128,.08); }
.fyb-meta { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 8px 10px; font-size: 12px; }
.fyb-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fyb-dim { color: var(--dsw-alias-label-secondary, #888); white-space: nowrap; }
.fyb-empty { padding: 28px 4px; color: var(--dsw-alias-label-secondary, #888); font-size: 13px; line-height: 1.9; }
.fyb-live { display: inline-flex; align-items: center; gap: 6px; color: var(--dsw-alias-brand-primary, #4f7cff); }
.fyb-dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; animation: fyb-pulse 1s ease-in-out infinite; }
@keyframes fyb-pulse { 0%,100% { opacity: .35 } 50% { opacity: 1 } }
`

    const ago = (ms) => {
      const d = Date.now() - Number(ms || 0)
      if (!Number.isFinite(d) || d < 0) return ''
      const m = Math.floor(d / 60000)
      if (m < 1) return '刚刚'
      if (m < 60) return `${m} 分钟前`
      const hr = Math.floor(m / 60)
      if (hr < 24) return `${hr} 小时前`
      return `${Math.floor(hr / 24)} 天前`
    }

    const kb = (n) => `${Math.max(1, Math.round(Number(n || 0) / 1024))} KB`

    function Icon(props) {
      const size = (props && props.size) || 18
      const active = !!(props && props.active)
      return h('svg', {
        width: size, height: size, viewBox: '0 0 24 24', fill: 'none',
        stroke: 'currentColor', strokeWidth: active ? 1.9 : 1.6,
        strokeLinecap: 'round', strokeLinejoin: 'round',
        'aria-hidden': true, focusable: false,
      },
        h('path', { d: 'M3 12.5c0-3.4 3.1-5.5 7-5.5 2.7 0 4.6.9 6 2.4l3-2.6v11.4l-3-2.6c-1.4 1.5-3.3 2.4-6 2.4-3.9 0-7-2.1-7-5.5z' }),
        h('circle', { cx: 8.4, cy: 11.4, r: 1.15, fill: 'currentColor', stroke: 'none' }),
        h('path', { d: 'M14.5 14.2c1 0 1.8-.3 2.4-.8' }))
    }

    function Panel() {
      const [items, setItems] = useState([])
      const [pv, setPv] = useState(null)
      const [running, setRunning] = useState(false)
      const [note, setNote] = useState('')
      const [dead, setDead] = useState(false)
      const [tick, setTick] = useState(0)

      const load = useCallback(async () => {
        try {
          const [g, s, p] = await Promise.all([get('/gallery'), get('/state'), get('/preview')])
          setItems(Array.isArray(g?.items) ? g.items : [])
          setRunning(Boolean(s?.running))
          setNote(String(s?.progress?.note || ''))
          setPv(p || null)
          setDead(false)
          setTick((x) => x + 1)
        } catch {
          setDead(true)
        }
      }, [])

      useEffect(() => {
        load()
        // 1.2 秒一轮：预览要"改一行就看见"，不能等
        const t = setInterval(load, running ? 1500 : 1200)
        return () => clearInterval(t)
      }, [load, running])

      const open = (name) => {
        window.open(`${B}/image?name=${encodeURIComponent(name)}`, '_blank', 'noopener')
      }

      const status = dead
        ? '连不上画板（刷新页面试试）'
        : running
          ? (note || '正在画…')
          : items.length
            ? `${items.length} 张画`
            : '还没有画'

      return h('div', { className: 'fyb-root' },
        h('style', null, CSS),
        h('div', { className: 'fyb-head' },
          h('div', null,
            h('div', { className: 'fyb-title' }, '🐟 小飞鱼画板'),
            h('div', { className: 'fyb-sub' },
              running ? h('span', { className: 'fyb-live' },
                h('span', { className: 'fyb-dot' }), status) : status)),
          h('div', { className: 'fyb-actions' },
            h('button', { className: 'fyb-btn', type: 'button', onClick: load }, '刷新'))),
        h('div', { className: 'fyb-body' },
          pv && pv.has
            ? h('div', { className: 'fyb-pv' },
              h('img', {
                className: 'fyb-pv-img',
                src: `${B}/image?name=_preview.png&t=${tick}`,
                alt: '预览',
              }),
              h('div', { className: 'fyb-pv-bar' },
                h('span', null,
                  '预览 · ',
                  pv.status ? pv.status.scene : '场景',
                  pv.watching ? '' : '（监视没起来）'),
                h('span', { className: 'fyb-dim' },
                  pv.status
                    ? `${ago(pv.status.at)}${pv.status.ms ? ` · ${pv.status.ms} ms` : ''}`
                    : '')),
              pv.status && pv.status.ok === false
                ? h('div', { className: 'fyb-pv-err' }, pv.status.error || '编译失败')
                : null)
            : null,
          items.length === 0
            ? h('div', { className: 'fyb-empty' },
              '还没有画。',
              h('br'),
              '让 Agent 说一句「画一张 rain-window」——它会调 fyb_draw，画完就出现在这里。')
            : h('div', { className: 'fyb-grid' }, items.map((it) => h('div', {
              key: it.name,
              className: 'fyb-card',
              onClick: () => open(it.name),
              title: it.name,
            },
            h('img', {
              className: 'fyb-thumb',
              src: `${B}/image?name=${encodeURIComponent(it.name)}&t=${tick}`,
              alt: it.name,
              loading: 'lazy',
            }),
            h('div', { className: 'fyb-meta' },
              h('span', { className: 'fyb-name' }, it.name),
              h('span', { className: 'fyb-dim' }, `${ago(it.mtime)} · ${kb(it.bytes)}`)))))))
    }

    return {
      inject: ['slots'],
      apply(ctx) {
        const slots = ctx.get ? ctx.get('slots') : ctx.slots
        if (!slots) return
        slots.inject('sidebar.panellist', () => slots.register({
          name: 'sidebar.panellist',
          id: 'feiyu-board',
          order: 22,
          label: () => '小飞鱼画板',
        }, Icon))
        slots.inject('main', () => slots.register({
          name: 'main',
          key: 'feiyu-board',
        }, Panel))
      },
    }
  },
})
