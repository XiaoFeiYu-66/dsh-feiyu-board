# 小飞鱼画板 · DSH 插件（含网页面板）

这个目录是画板的 DSH 插件，三部分：

| 文件 | 作用 |
|---|---|
| `index.js` | Host 侧：注册工具（`fyb_draw` 等）、提供画库路由、起实时预览 |
| `client.js` | **网页面板（GUI）**：左侧栏图标 → 画库网格，点开看原图 |
| `cordis.patch.yml` | 把插件插进 DSH 的谱系 |
| `locale/*.json` | 中英文案 |
| `icon.svg` | 侧栏图标 |

## 前提

- 跑着 DSH（DeepSeek Harness）
- 画板本体的依赖已装好（用 `安装.cmd`，或 `pip install -r requirements.txt`）

## 装法

插件必须出现在 DSH 的 profile 里。两种做法，任选：

### A. 建目录链接（推荐，改代码立即生效）

Windows PowerShell（管理员）：

```powershell
$src = "D:\你的路径\feiyu-board\plugin"
$dst = "$env:USERPROFILE\.dsh\profiles\desktop\node_modules\@local\dsh-feiyu-board"
New-Item -ItemType Directory -Force (Split-Path $dst) | Out-Null
New-Item -ItemType Junction -Path $dst -Target $src
```

macOS / Linux：

```bash
ln -s ~/feiyu-board/plugin ~/.dsh/profiles/desktop/node_modules/@local/dsh-feiyu-board
```

### B. 直接复制

把整个 `plugin` 目录复制成
`<profile>/node_modules/@local/dsh-feiyu-board`。
注意：复制之后改了源码要重新复制。

## 生效

装完重启 DSH（或用 `plugin_manager` 关开一次插件），左侧栏会出现画板图标，
同时 Agent 会多出 `fyb_draw` 等工具。

## Python 从哪找

插件不写死解释器路径，按这个顺序找：

1. 环境变量 `FYB_PYTHON`（想指定某个解释器就设它）
2. 画板目录下的 `.venv`：`.venv\Scripts\python.exe`（Windows）
   或 `.venv/bin/python`（macOS / Linux）
3. PATH 上的 `python`（Windows）/ `python3`（其他）

都找不到时，工具调用会返回一段说明告诉你去装哪一个，而不是抛 ENOENT。

## 说明

- 面板是**只读**的：数据都从 `/dsh-feiyu-board/*` 取，写操作只走 Host 的工具。
- 插件靠 `plugin/..` 找画板本体，所以**别把 plugin 目录单独搬走**。
