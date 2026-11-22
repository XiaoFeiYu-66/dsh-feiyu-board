# 小飞鱼画板 · DSL 速查

> **版本 1.8.0**（2026-11-22）。改了行为看 `CHANGELOG.md`；
> 如果这里的描述和你手上的包对不上，先比版本号——文档漂移比 bug 更难查。

给任何要画一张的会话看：**先读完这一段，再动手**。
工具：`fyb_doc`（要这份文档）、`fyb_scenes`（现有场景）、`fyb_draw`（渲染）。

**工程目录**（就是这份 DSL.md 所在的目录，写场景、找图都在这）：
- 场景：`scenes\<名字>.fyb`
- 出图：`renders\<名字>.png`
- 共享库：`scenes\lib\parts.fyb`（用 `include "../lib/parts.fyb"` 引）

---

## 0. 三分钟上手

```
canvas 1920x1080          ← 必须第一行
bg #0B1014                ← 底色
circle 960,540,300 fill=#4B93D8        ← 位置直接写数字，逗号分隔
ink [400,700 700,600 960,520] w=9 color=#7FD3F7 taper=0.5   ← 一笔
text 120,140 "夜里的海" 44 align=left color=#E8F4FF hand=0.3
```

存成 `scenes/<名字>.fyb`，然后 `fyb_draw(scene="<名字>")`。

**规则**：一行一条命令；`#` 开头的整行是注释；行尾 `\` 续行（点列可以跨行，只要方括号不被切开）；
逗号是顶层分隔符，所以 `at=[520,440]` 要带方括号，不能写成 `at=520,440`。

---

## 1. 命令表

| 命令 | 例子 | 备注 |
|---|---|---|
| `canvas WxH` | `canvas 1920x1080` | 必须第一行，否则 E008 |
| `bg` | `bg #0B1014` | |
| `rect` | `rect 200,100,880,700 fill=#16232E r=8` | 四个位置参数 x,y,w,h |
| `circle` | `circle 960,540,300 fill=#4B93D8` | cx,cy,r |
| `ellipse` | `ellipse 960,470,300,262 fill=#F6C48B` | cx,cy,rx,ry |
| `curve` | `curve [x1,y1 x2,y2 …] fill=#… closed` | 平滑曲线；点列在方括号里，空格或逗号分隔都行 |
| `poly` | `poly [x1,y1 …] fill=#…` | 直边多边形 |
| `ink` | `ink [x1,y1 x2,y2 …] w=9 color=#… taper=0.5` | **一笔**：有起收、抖动、出锋；加 `tex=` 就是纹理笔 |
| `text` | `text 120,140 "字" 44 align=left color=#fff hand=0.3` | 四个位置参数，正文必须带引号 |
| `group` / `endgroup` | `group at=[960,540] scale=1.12 about=[960,540]` | 变换组 |
| `clip` / `endclip` | `clip glass` … `endclip` | 块内图元按引用形状裁剪 |
| `shadow` | `shadow ref=glass dx=0 dy=16 blur=20 alpha=0.32` | 按引用轮廓投影子；`blur=` 就是软阴影 |
| `blur` / `endblur` | `blur 12` … `endblur` | 块内整体模糊（见 §4） |
| `hatch` | `hatch ref=gshadow angle=-12 spacing=15 w=3` | 在引用形状里排平行线（每条是笔画） |
| `bool` | `bool op=subtract base=body with=hole fill=#2B4A80` | op = subtract / union / intersect |
| `along` | `along ref=hairline group=frill count=7` | 沿路径等距复制一组 |
| `use` | `use fish at=[120,60] scale=0.5` | 按额外变换复用一组 |
| `grad` | `grad rect 0,0,1920,1012 from=#131C23 to=#0A0F14 dir=90` | 线性（dir=角度）或 `grad circle cx,cy,r`（中心→边缘） |
| `layer` | `layer 30` | 之后图元的起始 z |
| `hand` | `hand preset=ink jitter=1.2 seed=17` | 全局手感与随机种子 |
| `let` / `include` / `def` | `let 主色 = #C0392B` / `include "lib/parts.fyb"` / `def 孔 (x,y,r)` … `enddef` | 变量、跨文件复用、宏（见 §2） |
| `blend` / `endblend` | `blend multiply` … `endblend` | 混合模式（见 §4） |

---

## 2. 变量与宏（先学这个，能省一半力气）

**变量**：`let 名字 = 值`，用 `$名字` 引用。纯数字表达式会算出来。

```
let 主色 = #C0392B
let 半径 = 300
let 一半 = $半径 * 0.5
circle 960,540,$一半 fill=$主色
```

颜色、数字、坐标、整个点列都能存。**改一处，全场跟着变**——这是这套 DSL 里唯一的结构。

**宏**：`def 名字 (p1, p2)` … `enddef`，按位置传参。

```
def 气孔 (x, y, r)
  circle $x,$y,$r fill=#A8130A alpha=0.22
enddef

气孔 300,470,7
气孔 360,520,6
```

规则：

- 宏里能用全局变量；`def` 里不能再 `def`。
- 报错行号永远指向**调用点**，不是宏定义那一行。
- 调自己会停（深度上限 12），不会把编译器卡死。
- `$$` 表示一个字面的 `$`。
- 宏名不能和命令名（`circle`、`ink`…）或变量名重复，会报 E014。

**实测**：橘子那张 16 个气孔，改 `let 孔色` 一行，16 个一起变（`tests/run_macro.py` 就是这么验的）。

**跨文件复用**：`include "lib/parts.fyb"`，路径相对当前文件。

```
include "lib/parts.fyb"     # 库里的 let 和 def 全并进来
let 孔色 = #0055FF          # 想改库里的值，场景里再写一行就行
```

- 库里只该放 `let` 和 `def`，别放会真的画出来的命令。
- 循环包含会被拦下（E018），最多嵌 8 层。
- include 进来的行出错，报的是 `include` 那一行。
- **`let` 与位置无关**：写在文件哪一行，全文件都认（包括宏体里）。

---

## 3. 属性

### 属性名对照表（先看这张，能少踩一类错）

同一个概念在不同命令上名字不一样。**下面这些别名现在都认**，写哪个都行：

| 概念 | 形状族（rect / circle / ellipse / curve / poly / bool） | 笔族（ink / hatch / hand） | 别名 |
|---|---|---|---|
| 描边色 | `stroke=` | `color=` | 两个都认 |
| 线宽 | `width=` | `w=` | 两个都认 |
| 不透明度 | `alpha=` | `alpha=` | 一致 |
| 字体大小 | — | `text` 用 `size=` | — |

```
ellipse 520,820,280,180 stroke=#10102A w=6      # 形状族用 w= 也行
ink [20,60 280,60] w=18 stroke=#222             # 笔族用 stroke= 也行
```
只有 `curve` / `poly` 两族都是（它们既画形状又用笔描边），所以四个名字全认。

### 形状（rect / circle / ellipse / curve / poly）
`fill=` `stroke=` `width=` `alpha=` `name=`
- `fill=none stroke=none` = **只当几何**：不画出来，给 `clip` / `hatch` / `bool` / `along` 当靶子。
- `curve` / `poly` 带 `w=` 时，描边改用「笔」——平滑且带手味（推荐，比 `width=` 的 QPen 描边好看）。

### 笔（ink，也给 curve/poly 用）
| 属性 | 范围 | 默认 | 含义 |
|---|---|---|---|
| `w=` | 0.1–400 | 3 | 笔宽 |
| `taper=` | 0–1 | 0.2 | 起收笔收细 |
| `press=` | 0.05–3 | 无 | **笔压曲线**：`press=0.3:1:0.5`（2~5 个数，沿笔长的宽度倍率） |
| `jitter=` | 0–3 | 0.62 | 抖动量 |
| `rough=` | 0.4–2.5 | 1.0 | 整体粗糙倍率 |
| `wavelength=` | 0–2000 | 48 | 抖动的空间波长（太小像锯条） |
| `overshoot=` | 0–40 | w×0.28 | 线头冲出量 |
| `step=` | 1–100 | 6 | 重采样间距（手味的前提） |
| `wave=` | 0–2 | 0 | 正弦附加项，画图时建议 0 |
| `color=` `alpha=` `closed` `name=` | | | |

### 纹理笔（同一张表后面的四个）
| 属性 | 范围 | 默认 | 含义 |
|---|---|---|---|
| `tex=` | `paper` / `grain` / `dry` / `fiber` / `none` | none | 用哪种纹理遮罩 |
| `tex_scale=` | 0.1–12 | 1 | 纹理颗粒大小（越小越细） |
| `tex_alpha=` | 0–1 | 1 | 纹理强弱 |
| `passes=` | 1–6 | 1 | 同一笔画几遍（干笔） |
| `spread=` | 0–2 | 0.35 | 多遍之间错开多少（× 笔宽） |

```
ink [80,300 400,260 760,300] w=26 color=#2B3A4A tex=paper tex_scale=0.45
ink [80,400 400,360 760,400] w=26 color=#2B3A4A tex=dry passes=3 spread=0.5
```

- 纹理是**程序化生成**的（值噪声），没有外部素材，同一 seed 出同一张。
- 有纹理时**笔宽也会跟着抖**（±30%）——只压 alpha 的话细线上根本看不出来，
  看着还是矢量描边；让边毛起来才像铅笔。
- `dry` 不是"变淡"，是**真的有洞**（阈值化噪声），所以像炭笔吃不上纸。
- 纹理是**跟着笔走**的（按这一笔的平均走向旋转，以笔的起点为锚）。
  `fiber` 的纤维会顺着笔画铺开，不会像以前那样不管笔往哪走都横着一条条。
  实测：横笔和竖笔的"横切起伏 / 顺笔起伏"都在 5 左右；改回画布空间的话竖笔会掉到 0.8。

### 笔压（press）

`taper` 是"两头自然收细"，`press` 是"这一笔按了多重"——两者相乘。

```fyb
ink [80,430 520,430] w=40 color=#3B342B press=0.3:1:0.5   # 轻起、中段重、收笔提
```

- 写法：2~5 个数，**用冒号隔开**（逗号在这个 DSL 里是切词的分隔符，写了会被拆开）。
- 实测（w=18、taper=0.5 的横线）：不压起笔 11.9px；`press=0.25:1:0.45` 起笔变 3.0px，中段仍是 17.8px。
- 适合：厚笔、铅笔排线、树枝、任何"该有轻重"的线。
  细线（w<6）上几乎看不出来——别指望它把细线变成手写感。

### 文字
`size=` `align=left|center|right` `color=` `hand=0..1`（>0 时字形轮廓也会抖，就是手写体）

### 组
`at=[x,y]` `scale=` `rot=`（度）`flip=x|y` `about=[x,y]`（绕哪点缩放/旋转）`name=` `template=1` `alpha=`
- `template=1`：这一组**不自己画**，只当 `along` / `use` 的零件。
- `alpha=0..1`：**组透明**——整组先画到一层，再按 alpha 合成。
  跟"把每个子图元 alpha 调小"不一样：组里两笔重叠的地方**不会叠出深色**。
  嵌套时逐层相乘，而且每层仍然按"组"合成。

```
group alpha=0.5 name=fin
  curve [...] fill=$鳍色          # 这两笔有重叠
  curve [...] fill=$鳍色
endgroup                          # 重叠处是均匀的 50%，不是 75%
```

### 组透明用在哪
画**半透明的复杂零件**：鱼鳍、花瓣、薄纱、玻璃、烟雾团。
用逐个调 alpha 的做法，重叠处会深一块，看起来像"没洗干净"。

### 手感预设
`hand preset=clean|ink|pencil|brush|child|messy`
单笔属性永远优先于 preset。

---

## 4. 混合模式与模糊

```
blend multiply
  grad circle 480,700,300 from=#C0200AE6 to=#C0200A00
endblend
```

可用：`normal`（默认）/ `multiply` / `screen` / `overlay` / `darken` / `lighten` /
`dodge` / `burn` / `softlight` / `hardlight` / `difference` / `exclusion` / `add`

- 块内所有图元都用这个模式（`hatch` / `shadow` / `along` 画出来的也算）。
- 可以嵌套，取最内层。
- **`multiply` 压暗**：画暗部、纹理、投影。比盖一层半透明色干净——不会发灰发脏。
- **`screen` 提亮**：画光、雾气、反光。
- 配上会淡出的渐变（`from=#RRGGBBAA to=#RRGGBB00`），就是没有硬边的色块。

⚠️ 混合模式是跟"**下面已经画过的东西**"混合，所以顺序很重要：先铺底，再 `blend`。
⚠️ 底色是透明的地方，multiply 等于没画。

### 模糊

```
shadow ref=影子椭圆 dx=4 dy=2 blur=14 alpha=0.5   # 软阴影
blur 12                                            # 一整块模糊
  circle 800,300,120 fill=#2B6FD8
endblur
```

- `shadow` 加 `blur=` 就是软阴影；半径 0 是原来的硬边。
- `blur <半径>` 到 `endblur`：块里所有东西先画到一层，整层模糊后合成。适合光晕、雾、景深。
- 半径上限 300（画布逻辑像素），内部按 2 倍超采样算，所以视觉上更柔。
- 大半径会自动降采样再模糊（模糊本来就是低频），4K 上 r=24 大约 1 秒。
- 模糊块里的 `blend` 照常生效，但**块本身和外面是分开合成的**：块内看不清外面的底色做 multiply。

**软阴影的正确画法**：影子**不要**用物体本身的轮廓——那会像贴纸浮在墙上。
用一个扁椭圆当投影体，贴在物体底部，再 `clip` 到地面：

```
ellipse 960,908,270,26 fill=none stroke=none name=sh
rect 0,900,1920,180 fill=none stroke=none name=tablearea
clip tablearea
  shadow ref=sh dx=4 dy=2 blur=14 alpha=0.50 color=#7E5836
  shadow ref=sh dx=16 dy=12 blur=46 alpha=0.22 color=#7E5836
endclip
```

两层叠：紧的那层交代接触，散的那层交代环境光。

---

## 5. 六条必须知道的

1. **层序 = 书写顺序**（也可以用 `layer` 抬）。后写的盖先写的；`shadow` 要写在被投影的东西**前面**，否则盖不住。
2. **`curve` 闭不闭合是两回事**：开曲线平滑时两端不会被拉在一起；但如果你写了 `closed`，最后一点会连回第一点。
3. **`clip` 的名字可以是图元名，也可以是组名**（组 = 组内所有形状的并）。
4. **`hatch` / `bool` / `along` 的引用可以指向后面才定义的名字**（编译期最后统一检查）。
5. **报错一次报全**：`fyb check` 会把所有错一起列出来，带行号和插入符。先 check 再 render，省得盲跑。
6. **`let` / `def` 是编译前展开的**：改宏定义，所有调用点一起变；报错指向调用点。

---

## 5.5 渐变：三种写法和该用哪种

```fyb
grad rect 100,100,600,400 from=#FFB35A to=#2B4C8C dir=90     # ① 矩形里
grad circle 400,300,200 from=#FFF to=#FFF0                    # ② 圆里（径向）
grad ref=叶子 from=#3F8422 to=#7CC244 p0=[100,300] p1=[420,180]  # ③ 形状里 + 自定义轴
```

**③ 是给有机形状用的**，两个好处：

- `ref=` 让渐变**裁进那个形状**，不用再 `clip` + 手算包围盒（估小了露白、估大了被拉平）。
- `p0=` / `p1=` 用两个点定义渐变轴，不必再用"角度 + 包围盒中心"去猜。
  弯曲的叶子、斜着的身体，颜色才铺得对。不给 `p0/p1` 就退回包围盒 + `dir=`。

`ref=` 也可以指向**组名**（组的包围盒 + 组内的每个形状都被裁到）。

---

## 6. 常见构图套路

- **有体积的东西**：先 `shadow`，再主体，再受光侧一道暖色 `ink` 勾边。
- **玻璃/水**：一个 `curve` 当容器（起名），`clip` 它，里面铺 `grad rect` 当水。
- **一朵云/花边/铆钉**：`curve` 当路径 + `template` 组 + `along`。
- **复合有机结构**（果枝上的叶、叶上的脉）：**`along` 可以嵌套**——外层沿枝摆叶，
  叶里再沿脉摆脉络；内层的 `ref` 路径写在外层模板的局部坐标里，跟着一起走。
- **挖洞（眼睛、把手、镂空）**：两个 `fill=none stroke=none` 的形状 + `bool op=subtract`。
- **暗部/阴影**：`hatch ref=<形状> angle=… spacing=…` 比手写一排线省事。
- **光**：`grad circle`（灯晕）+ `grad poly`（光锥）+ 全局一层暗角 `grad circle`（从透明到黑）。

---

## 7. 命令行（不通过工具也能用）

```powershell
$py = "…\dsh-feiyu-board\.venv\Scripts\python.exe"
& $py -m fyb check  scenes\x.fyb
& $py -m fyb render scenes\x.fyb --out renders\x.png [--scale 2] [--under 参考图]
& $py -m fyb anim   scenes\x.fyb --out renders\x.apng
& $py -m fyb sweep  scenes\x.fyb --set preset=ink,pencil,child --cols 2
& $py -m fyb feedback scenes\x.fyb --tags too_messy,too_thin --apply
& $py -m fyb watch  scenes --scale 1     # 盯目录，改了自动重画 renders\_preview.png
& $py -m fyb trace  refs\hands.jpg --mode skeleton --out scenes\hand.fyb
& $py -m fyb trace  refs\room.jpg  --mode contour  --invert --out scenes\room.fyb
& $py -m fyb posterize 参考图.png --out scenes\chibi.fyb --colors 28
& $py -m fyb balance scenes\x.fyb --cells 4x3 --grid thirds
```

### `render` 的 `--scale` 到底缩放什么

**输出尺寸恒等于画布尺寸**。`--scale` 只影响超采样质量，不改文件大小：

| 参数 | 渲染 | 落盘 |
|---|---|---|
| 默认 `--scale 2` | 2 倍超采样，再缩回 | 画布尺寸（1920 画布 → 1920） |
| `--fast` | 不超采样，抗锯齿也关 | 画布尺寸（最快，草稿用） |
| `--raw` | 2 倍超采样，**不缩回** | 画布 × 倍率（1920 → 3840） |

想要更大的图，改 `canvas` 声明，别指望 `--scale`。

### `fyb trace`：参考图 → 点列

| 参数 | 说明 |
|---|---|
| `--mode skeleton` | 线稿用：二值化 → 细化成骨架 → 走成折线。得到**笔画中线**，能用我的笔重描 |
| `--mode contour` | 照片用：二值化 → 沿格边走出**物体外缘** |
| `--threshold 0.86` | 骨架模式**默认 0.86**；传 `0` 用 Otsu |
| `--invert` | 亮的当墨（黑底线稿、深色背景用） |
| `--min-len 12` | 骨架模式：短于这么多点的线丢掉（去碎屑） |
| `--simplify 1.5` | Douglas-Peucker 容差，越大点越少 |
| `--dilate 1` | 先膨胀几圈补断口（0~3） |
| `--join 5` | 端点相距多少像素内就接上 |
| `--adaptive 0` | 自适应阈值窗口（0=关）。光照极不均时才开 |
| `--height 1000` | 输出画布高度 |

**经验（都是一路踩出来的）**：
- **别用 Otsu 描铅笔稿**。它只迁就最黑的那几笔，淡的地方掉成背景，描出来是断线。
  实测一只手在 Otsu 下断成 **27 个连通块**，换成 0.86 只剩 3~4 块。
- **线断了先查掩码，不要先调参数**。把掩码和骨架各存一张 PNG 看一眼，
  就知道是"认不出墨"还是"走线走丢"——这两种病因的修法完全相反。
- **`--dilate 1` 基本都要开**：笔画的淡口往往只有 1~2 像素，膨胀一下就接上。
- **`--adaptive` 慎用**：它能救光照不均，但也会把纸纹吃进来，线会变毛。
- 骨架会提出**参考图里所有的线**，包括相邻物体的。先裁切干净再描。

### `fyb posterize`：图片 → 按颜色分层的场景

参考图是**色块分明的插画/图标**时，硬照着画不划算（形状太多、每笔都要判断）。
这条命令换个思路：按颜色分层，逐层抽轮廓，按"面积大的先画"叠起来。

```powershell
& $py -m fyb posterize 参考图.png --out scenes\chibi.fyb --colors 28
```

| 参数 | 说明 |
|---|---|
| `--colors 24` | 量化成几种颜色。**这是最能调的一档**：人物脸容易丢，就加到 28~32 |
| `--blur 1.0` | 量化前模糊，压掉抗锯齿过渡带；0 = 不模糊（噪点多） |
| `--eps 1.8` | 轮廓简化容差；太小留像素台阶，太大丢细节 |
| `--height 1200` | 输出画布高度 |
| `--min-area 380` | 小于这个面积的色块当噪声丢掉 |
| `--win 7` | 多数表决窗口，用来去麻点 |

**经验**：
- **量化算法选 OCTREE**（内部已固定）。MEDIANCUT 在"大面积白 + 少量肤色"的图上
  会把肤色也量化成白的——人物的脸直接发灰。
- **脸变白 = 颜色数不够**，加到 28 以上。这是这条命令最常踩的坑。
- 它产出的是**纯色块**，没有笔触和纹理，也没有发丝、褶边这类细节。
  是"简化"，不是复刻。
- 只适合色块分明的图；照片、渐变多的图会碎成上千块。

### `fyb balance`：构图体检

"这张画空不空"不该凭感觉。这条命令把画面切成网格，量每格**有墨的像素占比**。

```powershell
& $py -m fyb balance scenes\房间.fyb            # 4x3 网格 + 三分线
& $py -m fyb balance scenes\x.fyb --cells 3x3 --grid golden
```

输出三段：覆盖率网格表、提示（哪几格空、重心偏没偏）、一张标注图
（`renders\_balance_<场景>.png`，叠三分线 + 每格百分比 + 结论）。

| 参数 | 说明 |
|---|---|
| `--cells 4x3` | 网格（列x行），2~8 |
| `--grid thirds` | 叠三分线 / `golden` 黄金分割 / `none` |
| `--no-png` | 只打文字，不出图 |

**经验**：
- **基准是场景自己的底色**（`bg`），不是白。米色底按白算会把整张量成 100%（踩过）。
- "太满"只在**每格都超过 40%** 时才报——满版构图（房间、风景）不该被误判。
- 空格超过 4 个就只报数量 + 集中在哪几列/行，免得刷屏。
- 数字只是提示：**居中构图本来就该四角空**（马克杯、图标），别机械地追求"填满"。

## 8. 已知的边界

- 没有沿路径渐变、没有滤镜、没有布尔以外的矢量运算。
- ~~`along` 不能嵌套~~ ——**现在能了**（内层路径写在外层模板的局部坐标里）。
  环会被查出来报 `E019`，不会再死循环或静默少画。
- `use` 可以把"含 `along` 的模板组"整个搬走（含旋转/缩放），但 use 写在组里时
  **不会**再叠一层组的变换（源图元的坐标已经烘焙过了）。
- 组透明只支持 `alpha`，没有组级混合模式。
- 文字的手写是**轮廓抖动**，不是笔顺。
- 层序写错编译器抓不到，只能靠看。
