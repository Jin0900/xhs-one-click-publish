# GitHub 小红书图文生成技术调研报告

调研日期：2026-10-01
调研目标：为 xhs-one-click-publish 的图片排版系统 v2 寻找可学习的**设计思想与模板渲染架构**（非发布机器人）。
数据来源：GitHub REST API（star/许可/更新时间为 2026-10-01 实测值）、各仓库 README/SKILL.md/核心源码实际阅读。

---

## 1. 搜索过的项目

搜索分五组关键词：小红书专用（中/英）、社交媒体图片排版、信息图/模板卡片、中文排版（Pillow/SVG/HTML/Playwright）、AI+模板混合管线。

经过滤，5 个项目具备真实技术价值（另排除了大量纯发布机器人、prompt 集合和低质量教程仓库）。

## 2. 候选项目调研表

| 项目 | GitHub | Star（实测） | 最近 push | License | 技术栈 | 模板体系 | 自定义文字 | 中文字体 | 严格3:4 | 多页面 | 图文组合 | 自动换行 | 溢出检测 | HTML/SVG | 批量生成 | 适合度 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| guizang-social-card-skill | [op7418](https://github.com/op7418/guizang-social-card-skill) | 7,325 | 2026-07-01 | **AGPL-3.0** | HTML/CSS + Node Playwright | ✅ 28版式骨架+10主题 | ✅ 语义化文字类 | ✅ 含宋体/黑体字体栈 | ✅ 1080×1440 | ✅ section 组图 | ✅ | ✅ 浏览器原生 | ✅ **9条DOM规则** | HTML | ✅ 整组校验 | ⭐⭐⭐⭐⭐ 学思想，不可抄代码 |
| xhs-note-creator（ai-collab-playbook） | [cnfjlhj](https://github.com/cnfjlhj/ai-collab-playbook) | 451（整库） | 2026-09-14 | **未声明** | Python+Markdown+Playwright | ✅ 8 CSS 主题 | ✅ YAML+MD | ✅ 浏览器系统字体 | ✅ 1080×1440 DPR2 | ✅ cover+cards | ✅ | ✅ CSS | ⚠️ 仅 auto-fit 缩放 | HTML | ✅ CLI | ⭐⭐⭐⭐ 学管线，不可抄代码 |
| xhs-imagen（原 free-imagegen） | [NimaChu](https://github.com/NimaChu/xhs-imagen) | 120 | 2026-07-28 | **MIT** | Python + SVG + 外部渲染器 | ✅ project.json 驱动 | ✅ SVG 文本 | ✅ | ✅ 封面1080×1440* | ✅ | ✅ | ✅ SVG | ✅ validate 脚本+比例校验 | SVG | ✅ | ⭐⭐⭐⭐ MIT 安全 |
| baoyu-skills / baoyu-xhs-images | [JimLiu](https://github.com/JimLiu/baoyu-skills) | 26,247（合集） | 2026-09-10 | MIT | TypeScript Skill 合集 | ✅ 风格×布局矩阵 | ⚠️ 靠 AI 出图 | ⚠️ 依赖生图模型 | ⚠️ prompt 约定 | ✅ 1-10页 | ⚠️ | ❌ | ❌ | ❌ | ✅ | ⭐⭐⭐ 只学分类法 |
| xiaohongshu-post-gen（openclaw/skills） | [openclaw](https://github.com/openclaw/skills) | 合集条目，star 未单列 | 2026-08（v1.1.0） | 随合集 | Python，AI 出图（nano-banana-2） | ⚠️ 6种页面类型 | ❌ AI 渲染文字 | ❌ 不可控 | ⚠️ 1792×2400 | ✅ cover+9页 | ⚠️ | ❌ | ❌ | ❌ | ✅ | ⭐⭐ 学页面类型解析 |

\* xhs-imagen 内容页默认 1080×1920（9:16），与我们全 3:4 的要求不同，仅尺寸策略可参考。

## 3. 重点项目深入分析（3 个）

### 3.1 op7418/guizang-social-card-skill（最高参考价值）

实际阅读文件：`validate-social-deck.mjs`（360 行校验器全文）、仓库目录树、两篇第三方技术评测。

**架构**：种子 HTML（`template-editorial-card.html` / `template-swiss-card.html`）+ 版式配方（references/layout-recipes.md，28 个）+ 主题预设（10 套，禁止自定义 hex）→ Agent 把版式 HTML 块填入 `POSTERS_HERE` 占位符生成单文件 index.html → Playwright 对每个 `<section class="poster xhs">` 截图为 PNG → `validate-social-deck.mjs` 用真实 DOM 测量值做 9 条规则校验，FAIL 退出码 1。

针对 12 个问题：

1. **画布尺寸**：CSS 固定 1080×1440 像素，截图 viewport 1400×1700 容纳，按 section 元素截图；`deviceScaleFactor` 输出 2 倍图。
2. **3:4 实现**：固定像素 + 校验器按宽高比识别板型（0.75±0.02 判为 xhs）。
3. **文字区域**：语义类名 `.kicker .h-xl .h-hero .lead .body .cap .foot`，每个版式配方规定块的位置与层级，不是自由绘制。
4. **自动换行**：完全交给浏览器 CSS 排版引擎（`overflow-wrap`、行高、字重类）。
5. **中文字体**：字体栈含 Noto Serif/Songti/SimSun；校验器用 `SERIF_TOKENS` 识别风格（含 `songti/stsong/simsun`）。
6. **避免溢出（最值得学）**：
   - R1：`scrollHeight - clientHeight > 4px` 即溢出；
   - R8：遍历所有"有意义节点"取 `getBoundingClientRect`，测真实内容上下边界、底部留白、越界量；
   - R6：大标题硬上限（xhs 板 ≤2 行、≤8 字）；
   - R4：最小字号地板（body 22、lead 26、caption 18px——它的基准画布约 1080）；
   - 修复建议按溢出量分级（40/90/160px：先调间距→压块高→减标题→换高容量版式），**不是缩小字体**。
7. **层级体系**：类型化字号类 + Swiss 规则"越大越细"（R3 校验 ≥72px 且 weight≥600 即违规）。
8. **主体定位**：references/image-overlay.md + portrait-fill.md 规定图片填充规则与人脸避让；绝对定位全幅背景层在校验时被排除碰撞判定（≥85%/95% 面积规则）。
9. **模板复用**：种子模板（结构）× 主题令牌（颜色字体）× 版式配方（布局）三层正交组合。
10. **多主题套用**：同一内容数据可配 Editorial/Swiss 两套视觉，主题只改令牌。
11. **多页支持**：原生设计就是 deck（一组 section）。
12. **封面+内容页模式**：有，版式按页角色区分（封面图主导、KPI 塔、H 型条形图等），且 11 个垂类适配手册。

另有 **R5 密度带规则**：把 3:4 板面四等分，逐像素扫描占用度，任一带空隙 >216px 或总填充 <75% 报警——这条直接解释了"什么叫太空"。

**许可结论**：AGPL-3.0，**严禁复制其 HTML/CSS/JS 代码**到本项目（传染条款）。只学习规则与架构思想，自行实现。

### 3.2 cnfjlhj xhs-note-creator（管线最贴近）

实际阅读：`render_xhs.py`（457 行）、目录结构、requirements.txt。

**架构**：Markdown（YAML 头写封面 emoji/title/subtitle，标题 ≤15 字）→ `markdown` 库转 HTML → 注入主题 CSS（assets/themes 共 8 套）→ Playwright 1080×1440、DPR=2 截图 cover.png/card_N.png。截图前 `await document.fonts.ready`。

四种分页模式：
- `separator`：按 `---` 手动分页（每段约 200 字，**先控量再渲染**——最稳）；
- `auto-fit`：测 `.card-content` 原始尺寸后对整块做 CSS `transform: scale()` 缩放；
- `auto-split`：按测量高度自动切页；
- `dynamic`：画布高度可变（上限 4320）。

针对 12 问：画布/3:4 同上；文字区域由卡片 CSS 类定义；中文靠浏览器系统字体；溢出处理是**缩放整块**（与你"不得缩到不可读"的要求冲突，我们只借鉴 separator 的"内容预算"思想）；模板复用 = 主题 CSS 文件；批量 = CLI。

**许可结论**：仓库**未声明 License**（默认保留全部权利），不复制任何代码，只学管线设计。

### 3.3 NimaChu/xhs-imagen（无浏览器路线与比例校验）

实际阅读：`references/local-rendering.md`、`scripts/check_png_ratios.py`（全文）、目录树。

**架构**：`project.json`（内容+选页）→ Python 生成确定性 SVG → 调用外部渲染器导出 PNG。渲染器优先级：rsvg-convert → inkscape → sips → qlmanage → ImageMagick。另含 `patch_image_text.py`（在 AI 图上叠加 SVG 文字层，文字不交给 AI）和 `validate_project.py`。

可学要点：
- **内容→版式映射表**：定义/讲解→article_page、分组工具→catalog、步骤机制→mechanism、前后对比→comparison、流程→flow、时间线→timeline、收尾建议→checklist。这是成熟的"页面类型分类法"。
- **比例校验**：`check_png_ratios.py` 用纯标准库解析 PNG IHDR，容差 0.015，cover 校 3:4、page 校 9:16，FAIL 返回退出码 1。
- 输出命名固定（cover.png / page-01.png），顺序只体现在文件名。
- MIT 许可，可在注明来源后复用；但其依赖的外部 SVG 渲染器在 Windows 上默认全缺（本机实测无 rsvg/inkscape/ImageMagick）。

## 4. 其他发现（作为技术选型佐证）

- **Pillow 12 新能力**：`ImageText.Text.wrap(width, height)` 在高度超限时通过 `remaining_text` 返回未排完的文本——意味着纯 Pillow 路线也能做**确定性溢出检测**，不必依赖浏览器。本机 run-002/libs 已有 Pillow 12.3.0。
- Playwright/HTML 路线（capturist、ejs2img、OG image 系列教程）证明"HTML 模板 + 固定 viewport + 元素截图 + document.fonts.ready"是业界成熟范式。
- 混合管线共识（dev.to 等工程文章）：**LLM/AI 只产出结构化内容与素材，确定性渲染引擎负责文字与坐标**，可实现零文字幻觉。与我们既定原则一致。

## 5. 中文排版方案对比

| 方案 | 中文换行 | 字体 | 溢出检测 | 本机成本 | 视觉上限 |
|---|---|---|---|---|---|
| HTML/CSS + Playwright | 浏览器原生（最强） | 系统字体，加载稳 | DOM 实测（最强） | 需装 playwright + 下载 Chromium 约 150MB | 高 |
| 纯 Pillow | 自实现贪心换行（CJK 逐字+拉丁词分组+避头尾） | 直接用 msyh.ttc | bbox/ImageText 预算 | **零新增重依赖**（已就绪） | 中高 |
| SVG + 外部渲染器 | SVG 原生 | 依赖渲染器配置 | 需二次测量 | Windows 需装 rsvg/inkscape | 中高 |

## 6. 3:4 实现方案

- 统一输出 **1080×1440 严格像素**（不是近似比例），校验时做精确相等判断。
- 素材源（现有 AI 图 1024×1536）通过模板媒体槽 cover-crop 裁切，不拉伸。
- DPR/清晰度：Pillow 直接以 1080×1440 物理像素绘制（字体按该坐标系选型号），不存在低分放大问题。

## 7. 多页面实现方案

- 固定 4 页：cover + page1-3；文件名 `01_cover.png … 04_page3.png`。
- 页面类型 ≥3 种：`cover`、`content_step`（步骤卡）、`content_list`（清单）、`content_summary`（总结）。
- 一次渲染一个 `page_data.json`（含 4 页数据），批量产出 + 整组校验。

## 8. 当前项目存在的问题（对照成熟项目）

检查对象：SKILL.md、output/run-002 的 step3/step4/step6/step8 脚本与成图。

1. **尺寸不合规**：现图 1024×1536 = **2:3（0.667）**，不是 3:4（0.75）。我们自己的自动校验只查了"全部同尺寸"，没查比例。
2. **像简单海报的根因（信息架构层面）**：
   - 每页只有"一个居中文本卡 + 一个主体/装饰"，属于海报语法；成熟小红书图文是**多信息带（band）结构**：顶部 meta 行 → hero 标题 → 要点列表（序号/图标+引导词+说明）→ 高亮提示框 → 底部标签/总结条。
   - 用 guizang R8/R5 度量：现页面有效内容 activeRatio 约 0.5，底部/中部存在 >216px 空带；三页共用同一版式，没有页面类型差异。
   - 绿叶/瓶身是"角落贴纸"，不承载信息；成熟模板中每个组件都在信息层级里有角色。
3. **无模板系统**：位置、字号、颜色、圆角全部硬编码在 step6_compose.py 一个文件里；换主题/换版式要改代码。
4. **无文字工程**：换行靠手工预断行字符串；无字符预算、无最大行数/高度、无溢出检测；字号没有最小地板约束。
5. **无安全区/避让保证**：主体坐标写死，没有文字框-媒体框 keep-out 关系声明（今天已实际出现过瓶位出血、瓶底阴影问题）。
6. **校验层薄弱**：只有数量/顺序/尺寸/MD5；缺溢出、密度、最小字号、安全边距、主体遮挡、跨页一致性检查。
7. **抠图脆弱**：白底 floodfill 阈值法对白色瓶身+接触阴影需要反复试阈值（今天实测 thresh 40/55/72 各有问题，最终靠重新生成无阴影素材解决）。v2 应在资产契约上规避（AI 直接产出悬浮无阴影白底图），而不是靠更强的抠图算法。

## 9. 建议采用的技术方案（摘要，详见 v2 技术方案文档）

- 渲染路线：**Pillow 原生确定性引擎 + JSON 模板配置**（本机零重依赖；Pillow 12 支持高度受限换行与 remaining_text 溢出检测）；接口预留 HTML/Playwright 渲染器作为未来高质量选项。
- 配置与代码分离：templates/xhs_3x4/*.json（主题令牌 + 4 个版式）。
- 文字全部程序渲染；AI 只产出全幅背景与白底主体；媒体槽带 keep-out。
- 校验 V1–V9：严格尺寸、数量顺序、字符预算、溢出 FAIL（绝不缩小字号）、最小字号、安全区、密度带、跨页一致性、主题一致。
- 内容预算先行（学 separator 模式）：每个文字槽有 maxChars/maxLines，文案生成阶段即受约束。

## 10. 建议修改/新增的文件

- **新增**：templates/xhs_3x4/（theme.json + 4 个版式 json + fonts.json）、renderer/（model/text_layout/engine_pillow/assets/validate/render_cli）、examples/。
- **暂不修改**：SKILL.md、README.md、references/workflow.md、run-001、run-002（待 v2 跑通后再把文档中"建议 3:4"升级为"严格 1080×1440"）。
- **复用**：run-002 已生成的 AI 背景/主体素材可直接供 v2 首次渲染，**无需再调付费 API**。

## 11. 依赖变化

- 必需：无新增重依赖（Pillow 12.3.0 已在 run-002/libs；v2 会把 libs 提升为项目级 renderer 依赖目录或 requirements 声明）。
- 可选未来项：playwright + Chromium（HTML 渲染路线，需你批准安装，约 150MB）。

## 12. License 风险

| 项目 | 可否借鉴思想 | 可否复制代码/素材 |
|---|---|---|
| guizang（AGPL-3.0） | ✅ | ❌ 会触发 AGPL 传染 |
| xhs-note-creator（无 License） | ✅ | ❌ 默认保留全部权利 |
| xhs-imagen（MIT） | ✅ | ✅ 可，需保留版权声明（建议仍自行实现） |
| baoyu-skills（MIT） | ✅ 分类法 | 无需复制（prompt 型） |
| openclaw 条目 | ✅ | 不建议 |

结论：**v2 零第三方代码复制**，全部自行实现；规则与架构在文档中标注参考来源。

## 13. 最终推荐的模板系统架构

```text
内容层  page_data.json（标题/分页正文/页面类型/素材路径，受字符预算约束）
配置层  theme.json（色板/字号阶/间距/圆角令牌）
        cover.json / content_step.json / content_list.json / content_summary.json
        （bands 信息带 + text/media slots：盒模型、角色、maxLines/maxChars、keep-out）
渲染层  text_layout（CJK 换行/避头尾/预算）→ engine_pillow（确定性绘制 1080×1440）
资产层  assets.py（AI 背景 cover-crop / 白底主体 contain，仅放入媒体槽）
校验层  validate.py（V1–V9，FAIL 退出码 1，给出超槽名称/超出量/预算提示）
```
