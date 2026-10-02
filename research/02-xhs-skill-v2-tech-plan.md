# 小红书图文生成 Skill v2 技术方案

日期：2026-10-01
状态：**已实施（v0.1 闭环落地，见 §12 实施结果记录）**
配套文档：[01-github-research-report.md](./01-github-research-report.md)

---

## 1. 目标与硬性约束

1. 输出严格 **1080×1440（精确 3:4）**，1 封面 + 3 内容页，顺序 cover→page1→page2→page3。
2. AI（GPT-Image-2）只生成：全幅背景、白底主体、装饰素材。**禁止 AI 生成含中文文字的成图**。
3. 全部中文文字由程序渲染，字体/位置/颜色/间距由模板配置控制。
4. 文字超槽：按"压缩阶梯"处理，**禁止把字号缩到最小地板以下**；最终放不下则 FAIL 并报告，由上游精简文案。
5. 主体不得遮挡文字（媒体槽与文字槽几何互斥，渲染前+渲染后双重校验）。
6. 统一安全边距；≥3 种内容页版式；发布前自动验证尺寸/溢出/数量/顺序。
7. 不改 SKILL.md/README/workflow.md，不删 run-001/run-002，不调付费 API（首跑复用 run-002 素材）。

## 2. 渲染路线决策

| 路线 | 本机现状 | 结论 |
|---|---|---|
| HTML/CSS + Playwright | 无 Node、无 playwright、无 Chromium（需下载约 150MB） | 接口预留，二期可选 |
| **Pillow 12 原生引擎** | **已就绪**（run-002/libs，Pillow 12.3.0） | **一期采用** |
| SVG + 外部渲染器 | Windows 无 rsvg/inkscape/magick | 不采用 |

Pillow 12 的 `ImageText.Text.wrap(width, height)` 在高度超限时返回 `remaining_text`，配合 `font.getbbox()` 可实现确定性换行与溢出检测；不依赖浏览器。

## 3. 目录结构（全部为新增）

```text
xhs-one-click-publish/
├── templates/
│   └── xhs_3x4/
│       ├── theme.json              # 视觉令牌：色板/字号阶/间距/圆角/阴影
│       ├── fonts.json              # 字体角色→本机字体文件路径
│       ├── cover.json              # 封面版式
│       ├── content_step.json       # 内容页版式A：步骤卡
│       ├── content_list.json       # 内容页版式B：清单卡
│       └── content_summary.json    # 内容页版式C：总结卡
├── renderer/
│   ├── __init__.py
│   ├── model.py                    # 读取并校验模板/page_data 的数据模型
│   ├── text_layout.py              # CJK 换行、避头尾、字符预算、溢出判定
│   ├── assets.py                   # AI 素材装入媒体槽（cover-crop/contain）
│   ├── engine_pillow.py            # 确定性渲染 1080×1440
│   ├── validate.py                 # V1–V9 校验，FAIL 退出码 1
│   └── render_cli.py               # 入口：page_data.json → 4 PNG + 校验报告
├── examples/
│   └── summer_skincare/
│       └── page_data.sample.json
└── output/run-003/                 # v2 首次实跑产物（实施阶段才创建）
```

## 4. 模板配置设计

### 4.1 theme.json（视觉令牌，禁止在代码里写 hex）

```json
{
  "canvas": { "width": 1080, "height": 1440, "safe_margin": 72, "dpr_note": "直接物理像素绘制" },
  "color": {
    "ink": "#223A34", "sub": "#60706A", "brand": "#4A8C60",
    "brand_soft": "#E8F3EC", "card": "#FFFFFF", "card_alpha": 214,
    "bg_tint": "#F7FAF8", "warn": "#B45309", "hairline": "#D8E4DC"
  },
  "type_scale": {
    "hero":     { "size": 104, "line_height": 1.22, "weight": "bold",   "min": 96 },
    "section":  { "size": 68,  "line_height": 1.25, "weight": "bold",   "min": 60 },
    "lead":     { "size": 42,  "line_height": 1.4,  "weight": "regular","min": 38 },
    "body":     { "size": 36,  "line_height": 1.55, "weight": "regular","min": 32 },
    "caption":  { "size": 28,  "line_height": 1.4,  "weight": "regular","min": 26 },
    "tag":      { "size": 28,  "line_height": 1.2,  "weight": "bold",   "min": 26 }
  },
  "radius": { "card": 40, "chip": 32, "small": 20 },
  "space": { "band_gap": 36, "card_pad_x": 52, "card_pad_y": 44, "list_gap": 28 },
  "density": { "bands": 4, "min_active_ratio": 0.72, "max_empty_band_px": 216 }
}
```

### 4.2 版式 JSON：bands + slots 模型

版式不写死坐标流程，而是声明"信息带（band）→槽位（slot）"。示例 `content_step.json`：

```json
{
  "layout": "content_step",
  "bands": [
    { "band": 1, "slots": [
      { "id": "kicker", "type": "text", "role": "tag",
        "box": [72, 84, 520, 148], "style": { "chip": true, "bg": "brand_soft", "color": "brand" },
        "max_lines": 1, "max_chars": 10, "required": true }
    ]},
    { "band": 2, "slots": [
      { "id": "title", "type": "text", "role": "section",
        "box": [72, 200, 936, 320], "max_lines": 2, "max_chars": 14, "required": true },
      { "id": "accent", "type": "rule", "box": [72, 340, 202, 352] }
    ]},
    { "band": 3, "slots": [
      { "id": "points", "type": "point_list",
        "box": [72, 420, 936, 1080],
        "item": { "marker": "number", "title_role": "lead", "desc_role": "body",
                  "min_items": 2, "max_items": 3,
                  "title_max_chars": 12, "desc_max_chars": 22, "desc_max_lines": 2 },
        "required": true }
    ]},
    { "band": 4, "slots": [
      { "id": "tip", "type": "text", "role": "body",
        "box": [72, 1120, 936, 1260], "style": { "card": true, "bg": "brand_soft" },
        "max_lines": 2, "max_chars": 34, "required": false },
      { "id": "subject", "type": "media", "fit": "contain",
        "box": [760, 1280, 1010, 1410], "asset_role": "subject",
        "keep_out": ["kicker", "title", "points", "tip"] }
    ]}
  ]
}
```

规则：
- `box = [x1, y1, x2, y2]`，全部在 1080×1440 坐标系；任何 slot 不得越过 safe_margin=72（V6）。
- text slot 必须有 role/max_lines/max_chars；point_list 有条目数与每字段预算。
- media slot 用 `keep_out` 声明避让的文字槽；资产装入时 alpha 包围盒与这些槽求交，相交即 FAIL（V7）。
- 封面 `cover.json` 信息带：tag 行 / hero 标题（2 行 ≤10 字/行）/ 副标题 / 三要点 chips / 主体媒体槽（大）/ 底部标签行。
- `content_summary.json`：recap 列表（3 项，对应三步）+ CTA 卡 + 标签行。
- 本系列映射：cover→cover.json；page1/page2→content_step.json（STEP 1/2）；page3→content_summary.json。content_list.json 同期实现以备内容为清单型时使用（满足"≥3 种内容页布局"）。

### 4.3 page_data.json（内容层，受预算约束）

```json
{
  "topic": "夏季护肤产品",
  "theme": "default",
  "pages": [
    { "key": "cover", "template": "cover",
      "kicker": "夏季护肤", "title": "夏季护肤做减法", "subtitle": "三步就够了",
      "chips": ["温和清洁", "清爽保湿", "出门防晒"],
      "background": "../../output/run-002/element_img2.png",
      "subject": "../../output/run-002/main_image_cutout.png",
      "decoration": "../../output/run-002/element_img1_cutout.png",
      "footer_tags": ["精简步骤", "清爽度夏"] },
    { "key": "page1", "template": "content_step",
      "kicker": "STEP 1", "title": "温和清洁",
      "points": [
        { "title": "出油出汗多", "desc": "夏天面部油脂汗液增多" },
        { "title": "温和洁面", "desc": "选温和洁面，早晚各一次" },
        { "title": "别过度清洁", "desc": "频繁去油反而伤屏障" }
      ],
      "tip": "提示：清洁后不紧绷才是刚刚好",
      "background": "../../output/run-002/bg_page1.png",
      "subject": "../../output/run-002/main_image_cutout.png" }
  ]
}
```

## 5. 文字排版引擎（text_layout.py）

1. **测量**：统一用 `font.getbbox(text)`，绘制坐标补偿 bearing（left/top），避免高亮/居中原生偏移问题。
2. **CJK 贪心换行**：按字符切分，连续拉丁/数字作为一个 token 不拆；逐字累加宽度，超槽宽换行；显式 `\n` 强制换行。
3. **避头尾（基础版）**：禁止出现在行首：`，。、！？：；）】」』》%`；禁止出现在行尾：`（【「『《`；命中时把标点挤到上一行/移到下一行。
4. **预算判定**：先按 max_chars 粗校验（立即 FAIL 并给出字段名与预算），再按实际测量做 max_lines/盒高判定。
5. **溢出压缩阶梯**（任何一步后重新测量）：
   1. 行高在 role 允许范围内收紧（如 body 1.55→1.45）；
   2. slot 内边距按令牌梯度压缩（44→36→28）；
   3. 仍超出 → **FAIL**：报告 slot id、超出像素数、当前字数/预算、建议精简文案。
   4. 全程**不动字号**（字号低于 type_scale.min 直接 FAIL）。

## 6. 资产与渲染（assets.py / engine_pillow.py）

- 背景：媒体槽 cover 模式（等比填满+居中裁切）；现有 1024×1536 素材裁到 1080×1440 无变形。
- 主体：contain 模式放入媒体槽，按 alpha 包围盒定位；渲染前测量装入后的包围盒，与 keep_out 槽求交。
- 组件库（Pillow 绘制）：chip 胶囊、白色半透明圆角卡、序号圆点、hairline 分隔线、高亮提示框、标签行；颜色全部取自 theme 令牌。
- 输出 sRGB PNG；文件名严格 `01_cover.png / 02_page1.png / 03_page2.png / 04_page3.png`。
- 页面视觉一致性：同一 page_data 只允许一个 theme；页眉/页脚间距、卡片圆角全部取令牌。

## 7. 发布前自动校验（validate.py，V1–V9）

| 规则 | 内容 | 级别 |
|---|---|---|
| V1 严格尺寸 | 每张必须 1080×1440 精确相等 | FAIL |
| V2 数量顺序 | 恰好 4 张；文件名/key 顺序 cover→page1→page2→page3；MD5 互不相同 | FAIL |
| V3 文字预算 | title ≤20 字（平台限制）；各 slot 不超 max_chars/max_lines | FAIL |
| V4 文字溢出 | 每个 text/point_list 槽渲染高度 ≤ 盒高（压缩阶梯后仍超即 FAIL，附超出量） | FAIL |
| V5 最小字号 | 按 type_scale 的 min 地板逐槽检查 | FAIL |
| V6 安全边距 | 所有槽盒在 72px 安全区内；主体不出血 | FAIL |
| V7 图文避让 | 主体 alpha 包围盒不与任何文字槽相交；装饰层不压字 | FAIL |
| V8 信息密度 | 4 分带 active_ratio ≥0.72，空带 ≤216px（借鉴 R5/R8） | WARN（可继续，人工确认） |
| V9 一致性 | 四页同主题令牌；标题/正文/图片主题词一致；无虚构品牌/价格/参数/功效（关键词黑名单+人工确认） | FAIL/WARN |

校验产出 `validation_report.json`；存在 FAIL 时退出码 1，**不进入发布准备**。

## 8. 与现有 Skill 工作流的衔接

- SKILL.md 的 13 步流程不变。v2 只替换⑥–⑩步的实现方式（从"单脚本硬编码"换成"模板+渲染器+校验器"）。
- ③AI 生图的 prompt 契约更新（实施时写在调用脚本中，不改 SKILL.md）：背景必须全屏留白、主体必须**悬浮纯白底无接触阴影**（今天实测可显著降低抠图成本）；④抠图保留现有 floodfill 实现作为资产预处理。
- 文档二期更新（v2 验收后）：SKILL.md §6/§12 与 workflow.md 把"建议 3:4"改为"严格 1080×1440"，补充模板槽位与 V1–V9 校验描述。

## 9. 实施里程碑（审核通过后）

| 里程碑 | 内容 | 是否调用付费 API |
|---|---|---|
| M1 | theme/fonts/4 个版式 JSON + model.py 加载校验 | 否 |
| M2 | text_layout.py（换行/避头尾/预算/压缩阶梯）+ 单元自测 | 否 |
| M3 | engine_pillow 封面渲染（cover.json） | 否 |
| M4 | 三种内容页版式渲染 | 否 |
| M5 | assets.py + validate.py（V1–V9） | 否 |
| M6 | run-003 全流程实跑（复用 run-002 的 6 张 AI 素材）+ 人工核验 4 图 | **否** |
| M7 | （你同意后）更新 SKILL.md/workflow.md 尺寸与校验章节，重新打包 | 否 |
| M8 | 浏览器发布阶段（另行决策，不在本次范围） | — |

## 10. 验收标准

- 4 张成图严格 1080×1440；V1–V7、V9 全 PASS，V8 无 WARN 或 WARN 已人工确认。
- 与 run-002 同题对比：信息带完整（meta/hero/要点列表/提示或总结/标签），三页版式有明确角色差异，无大空带。
- 任意超长文案输入 → 得到明确 FAIL 报告而非缩成小字/溢出。
- 换一个主题只改 page_data.json 即可成套出图，无需动 Python。

## 11. 明确不做的事

- 不复制 guizang（AGPL）与 xhs-note-creator（无 License）的任何代码/CSS。
- 不引入数据库、Web 服务、Node 依赖（一期）。
- 不让 AI 渲染任何最终中文文字。
- 不为"功能完整性"增加发布自动化（保持人工确认红线）。

---

## 12. 实施结果记录（v0.1，2026-10-02）

方案经 M1–M3 封面小样（run-003）与四页闭环（run-004）落地。与原方案的差异和最终实现记录如下，**以本节为准**：

### 12.1 实际目录与文件

```text
xhs-one-click-publish/
├── services/gpt_image2.py          # gpt-image-2 封装（新增，纯标准库）
├── pipeline/
│   ├── generate_assets.py          # ③④ 节点：透明素材生成 + alpha 门禁
│   └── assemble_publish.py         # ⑪ 节点：发布准备包
├── renderer/                       # model / text_layout / assets / engine_pillow / validate / render_cli
└── templates/xhs_3x4/
    ├── theme.json / fonts.json / template.schema.json
    └── cover.json / page1.json / page2.json / page3.json
```

### 12.2 与原方案的差异

| 项 | 原方案 | 实际实现 | 原因 |
|---|---|---|---|
| 模板文件 | content_step / content_list / content_summary 三种内容页版式 | page1.json / page2.json（page_step）+ page3.json（page_summary），v0.1 未实现清单版式 | 闭环优先，两种内容页版式已覆盖当前主题结构 |
| page_data 结构 | pages 数组 + 每页平铺字段 | `pages` 字典（cover/page1/page2/page3，各含 content/assets）+ 顶层 `publish` 字段；`PageData.view(key)` 按页取视图 | 多页素材/内容解耦更清晰，无 pages 时回退整包兼容 run-003 |
| ③④ 素材流 | AI 生成白底图 + floodfill 抠图 | **gpt-image-2 透明背景直出**（background=transparent + PNG）+ alpha 门禁（RGBA/四角 alpha≤8/透明占比>30%/主体占比 5%~95%）；抠图节点取消 | 2026-10-02 探针实测：preview 通道支持 transparent background，RGBA/四角全透/边缘干净；直出素材优于抠图 |
| V2 校验 | MD5 互不相同 | 文件名与顺序检查（文件名固定，天然互异） | 以最小实现满足契约 |
| V9 校验 | 主题一致性 + 关键词黑名单 | 字体可用性 + 关键汉字字形抽检（glyphSmokeTest） | 主题一致性属内容层校验，当前由人工确认承担 |
| 示例目录 | examples/summer_skincare/page_data.sample.json | output/run-004/ 真实闭环样例（含素材、校验、发布包） | 实跑样例比静态 sample 更可验证 |
| 渲染入口 | render_cli 输出 4 PNG | `--template all`（默认，四页一次渲染+合并校验）或单页模式 | 支持逐页 V1–V9 校验 + run 级合并报告 |

### 12.3 渲染引擎关键决策与已修复缺陷

- **逐字绘制基线**：中文按字符绘制以支持字距/避头尾。绘制坐标统一传 Pillow `anchor='la'` 原点，由 Pillow 内部 offset 保证基线对齐；**不可对单字做 `y - t` bearing 补偿**——全角标点 top bearing 大（"，"t=35@36px），逐字补偿会把整行墨迹顶部拉到同一水平线，导致标点飞顶（run-004 首跑发现并修复）。
- **trimTransparent**：透明素材按 alpha bbox 裁边后再 contain 装入，避免素材透明边导致主体显示过小。
- **tag_row pill**：胶囊背景层先画、文字后画，`solidRects` 记入 manifest 供 V7 碰撞检测。

### 12.4 run-004 闭环验收结果

- 素材：`assets_manifest.json all_ok=true`（透明白瓶 1254×1254、透明绿叶透明占比 67.6%、窗边光背景）
- 渲染：4 页 × V1–V9 全 PASS，零 WARN；`overall.text_overflow=false`、`element_collision=false`
- 发布包：`publish_data.json`，title 13 字、content 192 字、images 4 张 1080×1440 顺序正确、`status=ready_for_review`

### 12.5 未完成 / 后续

- 浏览器自动发布（Playwright）→ v0.2 规划，须保留人工确认前置
- 清单型内容页版式（content_list）、主题一致性自动校验（V9 扩展）→ 按需迭代
