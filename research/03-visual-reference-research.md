# 视觉参考调研报告（模板/排版方向专项）

日期：2026-10-01
范围：在 01 报告（guizang / xhs-note-creator / xhs-imagen / baoyu / openclaw）之外，专项补调「模板 Schema、排版引擎、Pillow 中文排版、编辑设计感」方向。
方法：GitHub API 实查 star/许可/更新时间 + 阅读官方文档/核心架构资料。**只学设计思想与 Schema 结构，不复制任何第三方代码。**

---

## 一、结论：GitHub 上没有"高质量小红书封面设计器"

中文关键词下的项目仍然是三类：发布机器人、AI 直出图（文字不可控）、简单 Pillow 贴图。真正值得学的是**通用社交卡片/设计编辑器/排版引擎**项目。最终保留 4 个主参考 + 2 个技巧补充。

## 二、最终保留的 4 个项目

### 1. op7418/guizang-social-card-skill —— 社交卡片"设计系统 + 质检门禁"

- 地址：https://github.com/op7418/guizang-social-card-skill
- 实测：7,325 stars，AGPL-3.0，TypeScript/HTML，最近 push 2026-07-01
- **借鉴什么**：
  - 视觉三层正交：种子结构 × 主题令牌（10 套预设，禁自定义 hex）× 28 个版式配方。
  - 语义化文字角色：kicker / h-xl / h-hero / lead / body / cap / foot，字号即层级。
  - 发布前 9 条 DOM 实测门禁：scrollHeight 溢出 >4px FAIL、最小字号地板、3:4 四等分密度带（空带 >216px / 填充 <75% 告警）、大标题 2 行 8 字硬上限。
- **为什么值得**：是唯一把"好看"量化成可执行检查规则的项目，直接指导我们的 validate 设计。
- 注意：AGPL-3.0，只学规则，不抄代码/CSS。

### 2. vercel/satori —— 声明式排版引擎的管线架构

- 地址：https://github.com/vercel/satori
- 实测：13,987 stars，MPL-2.0，TypeScript，最近 push 2026-09-22（活跃）
- **借鉴什么**：
  - 管线分层：元素树 → 样式展开/归并（expand/compute）→ 布局引擎（Yoga Flexbox）→ SVG 输出。我们的 Pillow 引擎照此分层：模板+数据 → 样式解析 → 测量排版（text_layout）→ 位图绘制。
  - 字体子系统：字体以 `{name, data, weight, style}` 数组显式注册，按 weight/style 匹配，支持多语言；所有元素必须给**显式宽高**，容器固定、`textOverflow` 策略明确。
  - "画布尺寸由调用方锁定（如 1200×630），渲染必须确定"的理念。
- **为什么值得**：证明"声明式 JSON/元素树 + 固定画布 + 确定性测量"是工业界生成社交图的主流范式。
- 注意：MPL-2.0 文件级传染，不复制源码；我们用 Python/Pillow 自行实现等价分层。

### 3. Polotno —— Canva 类模板的 JSON Schema 与品牌锁定模型（Schema 首参考）

- 地址：https://github.com/polotno-project/polotno（SDK 商业 License；Schema 文档公开：https://polotno.com/docs/schema）
- **借鉴什么（全部是公开文档中的数据模型思想）**：
  - Design 根：`schemaVersion / width / height（默认 1080）/ fonts[] / pages[] / bleed（四边独立）`。
  - TextElement 字段集：`x,y,width,height`、`text/placeholder`、`fontSize/fontFamily/fontStyle/fontWeight`、`fill`、`align/verticalAlign`、`lineHeight（倍数|auto）`、`letterSpacing（字号的比例值）`、`backgroundEnabled/Color/Opacity/CornerRadius/Padding`、`shadow*`。
  - ImageElement：`cropX/cropY/cropWidth/cropHeight`（0–1 比例裁切）、`cornerRadius`——这正是"保持比例 + cover/contain + 锚点"的可配置表达。
  - 品牌锁定四规则层（与用户 18 项要求一一对应）：
    1. 结构层：位置锁定、安全区、bleed；
    2. 内容层：`locked / contentOnly / bounded` 三档可编辑性、`required`；
    3. 样式层：`styleToken` 选令牌、`allowStyleOverrides:false`；
    4. 输出层：导出前 preflight（分辨率/字体可用性/溢出），不合格不允许渲染。
  - 核心目标：**确定性**——同模板版本 + 同数据必出同结果。
- **为什么值得**：它的 JSON 字段命名与锁定模型是经过商用验证的模板 Schema，直接指导我们 18 项 Schema 补全。
- 注意：商业 License，不引用任何代码。

### 4. NimaChu/xhs-imagen —— 同领域 Python 项目（MIT，可自由参考）

- 地址：https://github.com/NimaChu/xhs-imagen
- 实测：120 stars，MIT，Python，最近 push 2026-07-28
- **借鉴什么**：
  - `project.json` 内容模型 → 确定性渲染（文字全部 SVG 程序绘制，AI 只出素材）。
  - 页面类型分类法：article / catalog / mechanism / comparison / flow / timeline / checklist。
  - `check_png_ratios.py`：纯标准库解析 PNG IHDR，容差校 3:4，FAIL 退出码 1（我们改为**精确 1080×1440**）。
  - 固定输出名 cover.png / page-01.png 体现顺序。
- **为什么值得**：领域最近、许可最干净、Python 栈一致；其 Windows 渲染器短板（依赖 rsvg/inkscape）正是我们用 Pillow 规避的。

### 技巧补充（不进主榜）

- JimLiu/baoyu-skills（MIT，26,247★ 合集）：学"风格 × 版式"二维矩阵的分类组织方式；它是 prompt 驱动，不解决文字确定性。
- preangelleo/youtube-thumbnail-generator（MIT，仅 7★，2025-08 后停更）：仅取其 Pillow 中英文排版微经验——中文按字符数预算（9/20 字档）、3 行截断省略号、中文使用更大字号、文字永远最后绘制在最上层。项目体量/活跃度不足以进主榜。

## 三、最终采用到封面小样的设计决策

| 决策 | 来源 |
|---|---|
| 根文档锁定 width/height=1080×1440、schemaVersion、fonts 显式注册 | satori / Polotno |
| 颜色/字号/行距/间距/圆角全部走 theme 令牌，模板不写裸值 | guizang / Polotno styleToken |
| 元素字段：box(x,y,w,h)、role、align/verticalAlign、lineHeight、letterSpacing、fontWeight、max_lines、max_chars、overflow_policy、required、editability | Polotno TextElement + guizang 预算 |
| 媒体字段：fit=contain/cover、anchor、比例裁切、margin、keep_out 列表 | Polotno crop 模型 + 既有 cover/contain 契约经验 |
| 溢出策略：压缩行距/内边距 → 仍超 FAIL（禁止缩字号、禁止省略号掩盖） | guizang 分级修复 + 用户硬性要求 |
| 渲染分层：model → text_layout（测量先行）→ assets → engine → validate | satori 管线 |
| 校验门禁：精确尺寸/数量顺序/预算/溢出/最小字号/安全区/图文碰撞/字体可用性，FAIL 退出码 1 | guizang preflight + xhs-imagen IHDR + Polotno 输出层 |
| CJK 换行：逐字贪心 + 拉丁成组 + 避头尾 + bbox bearing 补偿 | 自行实现（Pillow 通行做法） |

## 四、License 红线汇总

| 项目 | 许可 | 可用方式 |
|---|---|---|
| guizang | AGPL-3.0 | 只学思想 |
| satori | MPL-2.0 | 只学架构，不引源码 |
| Polotno | 商业 | 只学公开 Schema 模型 |
| xhs-imagen | MIT | 可自由参考（仍自行实现） |

v2 渲染器零第三方代码复制。
