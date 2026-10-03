# 小红书一键发布工作流说明

本文件记录小红书一键发布工作流的完整执行步骤，包含每步的输入输出、数据结构、判断标准、异常处理与发布前检查。

---

## 工作流总览

```text
主题/输入
  ↓
① 文案生成
  ↓
② 视觉元素拆分
  ↓
③ 主图/副图生成（透明背景直出）
  ↓
④ 素材透明度验收
  ↓
⑤ 首页文字拆分
  ↓
⑥ 封面制作
  ↓
⑦ 内容页1
  ↓
⑧ 内容页2
  ↓
⑨ 内容页3
  ↓
⑩ 图片整理/内容组合
  ↓
⑪ 发布准备
  ↓
⑫ 人工确认
  ↓
⑬ 发布
```

---

## 与实际工作流画布的节点对照表

本工作流依据扣子（Coze）平台的「小红书一键发布工作流」画布整理，Skill 步骤与画布节点的对应关系如下：

| 画布节点 | 输入 | 输出 | 对应 Skill 步骤 |
|---|---|---|---|
| 开始 | `zhanghao` | — | 输入 |
| 小红书文案生成 | 主题 `input` | `title`、`reasoning_content` | ① 文案生成 |
| 元素拆分 | 文案结果 | `main_image`、`element_img1`、`element_img2` | ② 视觉元素拆分 |
| 主图 / 副图1 / 副图2 | 元素拆分结果 | 3 张生成图片 | ③ 主图/副图生成 |
| ~~主图抠图 / 副图1抠图 / 副图2抠图~~ | ~~对应生成图片~~ | ~~3 张透明主体素材~~ | ④（v0.1 已取消抠图，改为素材透明度验收，见下文说明） |
| 首页文字拆分 | 标题、正文 | 封面文字结构、正文三页信息分配 | ⑤ 首页文字拆分 |
| 图层 | 3 张透明素材 | `cover`（合成封面） | ⑥ 封面制作 |
| 海报_1 / 海报_2 / 海报_3 | 正文要点、主体素材 | `page1`、`page2`、`page3` | ⑦⑧⑨ 内容页1/2/3 |
| 代码 | 4 张图片 | 有序图片集合 | ⑩ 图片整理/内容组合 |
| 小红书发布 | `zhanghao`、`images`、`title`、`content` | 发布结果 | ⑪ 发布准备 + ⑬ 发布 |
| 结束 | 发布结果 | 输出 | 输出 |

说明：

1. 画布中「小红书发布」为外部平台发布节点；Skill 在其之前增加 ⑫ 人工确认环节，正式发布前必须经过人工确认。
2. 画布通过「代码」节点完成图片排序与发布数据组装；Skill 将其整理为 ⑩ 图片整理/内容组合与 ⑪ 发布准备两个可检查步骤。
3. Skill 在画布节点基础上补充判断标准、异常处理与验证规则，这些规则不依赖特定平台，画布变更时只需同步本对照表。

### v0.1 实现映射（2026-10-02）

| Skill 步骤 | 当前实现 | 代码位置 |
|---|---|---|
| ③ 主图/副图生成 | gpt-image-2 透明背景直出：主体/装饰以 `background=transparent` + PNG 输出，不再生成白底图 | [services/gpt_image2.py](../services/gpt_image2.py)、[pipeline/generate_assets.py](../pipeline/generate_assets.py) |
| ④ 素材透明度验收 | alpha 门禁：RGBA、四角 alpha≤8、透明占比>30%、主体占比 5%~95%；画布抠图节点取消，不使用后处理抠图 | [pipeline/generate_assets.py](../pipeline/generate_assets.py) |
| ⑤ 首页文字拆分 | 产出 page_data.json 的 pages 多页内容结构（cover/page1/page2/page3 各自的 content） | [output/run-004/page_data.json](../output/run-004/page_data.json) |
| ⑥–⑨ 封面/内容页制作 | 模板盒模型 + Pillow 确定性渲染，一次渲染四页并逐页校验 | [renderer/render_cli.py](../renderer/render_cli.py)、[templates/xhs_3x4/](../templates/xhs_3x4/cover.json) |
| ⑩ 图片整理/内容组合 | 输出文件名固定 01_cover.png → 04_page3.png，顺序由渲染器固定保证 | [renderer/render_cli.py](../renderer/render_cli.py) |
| ⑪ 发布准备 | 校验通过后组装 publish_data.json，status=ready_for_review，等待人工确认 | [pipeline/assemble_publish.py](../pipeline/assemble_publish.py) |
| ⑬ 发布 | 已实现：pipeline/publish_xhs.py（Playwright 本机 Chrome/Edge）；首次人工扫码、人工确认闸口后发布，强成功信号判定，回写 status=published；2026-10-02 run-004 真实发布验证通过 | [pipeline/publish_xhs.py](../pipeline/publish_xhs.py) |

---

## 各步骤输入输出

### ① 文案生成

**输入**

- `input`（String）：小红书主题、关键词或原始素材
- 可选：风格要求、商品信息、目标人群、参考图片、品牌信息

**输出**

```json
{
  "title": "小红书标题",
  "reasoning_content": "小红书正文"
}
```

**作用**：根据用户主题生成小红书标题和正文内容，为后续视觉拆分提供内容基础。

**判断标准**

- 标题非空且与主题一致
- 正文非空且与主题一致
- 未虚构用户未提供的品牌、价格、产品参数、功效

**异常处理**

- 重新执行文案生成
- 连续失败则停止工作流 → 保留错误信息 → 要求重新输入主题

---

### ② 视觉元素拆分

**输入**

- 文案生成结果：`title`、`reasoning_content`

**输出**

```json
{
  "main_image": "主要视觉元素",
  "element_img1": "辅助元素1",
  "element_img2": "辅助元素2"
}
```

**作用**：把文字内容转化为图片生成所需要的主要视觉元素与辅助视觉元素。

**判断标准**

- `main_image`、`element_img1`、`element_img2` 均非空
- 元素与文案内容对应，不脱离主题

**异常处理**

- 检查文案输出是否完整；文案不完整则返回文案节点重新生成
- 文案完整但拆分失败，则重新执行元素拆分

---

### ③ 主图/副图生成（透明背景直出）

**输入**

- 元素拆分结果：`main_image`、`element_img1`、`element_img2`

**输出**

- `main_subject.png`：透明背景主体素材（依据 `main_image`，PNG + alpha 通道）
- `element_1.png`：透明背景装饰素材（依据 `element_img1`）
- `element_2.png`：背景氛围素材（依据 `element_img2`，不透明）

**作用**：调用 gpt-image-2（OpenAI 兼容异步接口，经 APIMart 中转）生成后续封面与内容页排版所需的素材。主体与装饰直接要求 isolated subject / fully transparent background 由 AI 直出透明 PNG，prompt 中显式约束；不再生成白底图、不需要后处理抠图。

**判断标准**

- 三张素材均成功生成（生成失败有 429/5xx 退避重试）
- 主体/装饰为 RGBA PNG 且内容与元素描述一致
- 主体与装饰风格基本统一

**异常处理**

- 只重新生成对应失败的素材，不重跑整个工作流
- 已存在且验收通过的素材默认跳过（`--force` 强制重新生成），避免重复消耗

---

### ④ 素材透明度验收

**输入**

- ③ 生成的三张素材

**输出**

- 通过验收的素材集合 + `assets_manifest.json`（含文件大小、md5、alpha 统计、逐项 ok/reason）

**作用**：在素材进入渲染器之前做确定性验收（alpha 门禁），替代原「图片主体处理/抠图」节点。抠图节点已于 v0.1 取消（gpt-image-2 preview 支持 transparent background，2026-10-02 探针实测 RGBA/四角全透/边缘干净），不再需要后处理抠图工具。

**判断标准（alpha 门禁，任一不满足即 FAIL）**

- 格式为 RGBA PNG
- 四角 alpha ≤ 8（角部透明）
- 透明像素占比 > 30%
- 主体像素占比在 5%~95% 之间

**异常处理**

- 验收失败：先用更强调的 prompt 重新生成该素材
- 连续失败：保留纯色背景备选方案（方便后续处理），并停止流程人工介入

---

### ⑤ 首页文字拆分

**输入**

- 标题（`title`）
- 正文（`reasoning_content`）

**输出**

- 主标题
- 副标题
- 核心信息
- 辅助说明
- 正文三页信息分配（`page1` / `page2` / `page3` 各自承载的正文要点）

**作用**：对封面文字进行结构化拆分，避免封面直接使用大段正文；同时将正文要点分配到三张内容页，作为步骤⑦⑧⑨的输入依据。

**判断标准**

- 拆分后的文字能够概括封面核心信息
- 文字量适合封面排版
- 正文要点完整分配到三张内容页，无遗漏、无重复

---

### ⑥ 封面制作

**输入**

- 首页文字（主标题、副标题、核心信息、辅助说明）
- 主要图片素材（经主体处理后的主图）
- 辅助视觉元素（副图1、副图2，或从中提取的素材）

**输出**

- `cover`（1 张封面图片）

**作用**：（对应画布「图层」节点）将标题文字、主要图片素材、辅助视觉元素合成为封面。v0.1 实现方式：由 [renderer/render_cli.py](../renderer/render_cli.py) 按 [templates/xhs_3x4/cover.json](../templates/xhs_3x4/cover.json) 模板盒模型渲染——背景 cover 填充、文字槽程序化排版（CJK 自动换行/避头尾）、素材 contain 装入 + trimTransparent + 软阴影，输出严格 1080×1440。**AI 不生成任何成图中文文字**。

**判断标准**

- 主题明确、主要视觉对象明确
- 标题可识别、视觉焦点清楚
- 与正文内容保持一致

---

### ⑦ 内容页1

**输入**

- 正文结构（依据 `reasoning_content` 拆分出的第一个主要信息）
- 主体素材（主图或副图相关素材）

**输出**

- `page1`（1 张内容页图片）

**作用**：（对应画布「海报_1」节点）表达第一个主要信息，作为正文内容页的开端。v0.1 实现方式：按 [templates/xhs_3x4/page1.json](../templates/xhs_3x4/page1.json)（page_step 版式：胶囊 kicker / heading / 英文小标 / 正文 / 主体 / 装饰）渲染，渲染命令一次输出四页（`python renderer/render_cli.py --run output/run-XXX`）。

**判断标准**

- 页面内容对应正文第一个主要信息
- 文字可读，无大面积遮挡
- 与封面风格统一

---

### ⑧ 内容页2

**输入**

- 正文结构（依据 `reasoning_content` 拆分出的第二个主要信息）
- 主体素材

**输出**

- `page2`（1 张内容页图片）

**作用**：（对应画布「海报_2」节点）表达第二个主要信息，承接内容页1并展开内容。v0.1 实现方式：与 page1 同用 page_step 版式（page2.json），靠 page_data 中各页 content 区分内容。

**判断标准**

- 页面内容对应正文第二个主要信息
- 与内容页1有递进关系，不重复

---

### ⑨ 内容页3

**输入**

- 正文结构（依据 `reasoning_content` 拆分出的补充/总结/行动信息）
- 主体素材

**输出**

- `page3`（1 张内容页图片）

**作用**：（对应画布「海报_3」节点）完成补充、总结或行动信息，三张内容页之间形成完整信息链。v0.1 实现方式：按 [templates/xhs_3x4/page3.json](../templates/xhs_3x4/page3.json)（page_summary 版式：三步 recap 胶囊行 / 正文 / 标签行）渲染。

**判断标准**

- 页面内容承担不同信息任务
- 与内容页1、内容页2不重复
- 信息结构完整：核心信息 → 具体内容 → 补充/总结

---

### ⑩ 图片整理/内容组合

**输入**

- `cover`、`page1`、`page2`、`page3`

**输出**

- 4 张图片的固定有序集合

**作用**：（对应画布「代码」节点）确认图片数量、顺序、格式，处理缺失或错位问题。

**排序规则**

```text
images = [
  "cover",
  "page1",
  "page2",
  "page3"
]
```

**判断标准**

- 数量为 4
- 顺序为 cover → page1 → page2 → page3
- 无缺失、无重复

**异常处理**

- 数量不足：检查缺少哪一张，重新生成对应内容
- 顺序错误：重新排序恢复固定顺序

---

### ⑪ 发布准备

**输入**

- 标题（`title`）
- 正文（`reasoning_content` 或整理后的 `content`）
- 图片集合（`images`：cover、page1、page2、page3）
- 账号信息（`zhanghao`）

**输出**

- `publish_data.json`（发布准备包清单，位于 run 目录下）：

```json
{
  "schemaVersion": 1,
  "run": "run-004",
  "title": "最终标题",
  "content": "最终正文",
  "images": [
    { "role": "cover",  "file": "01_cover.png",  "path": "…/final/01_cover.png",  "width": 1080, "height": 1440 },
    { "role": "page1", "file": "02_page1.png", "path": "…/final/02_page1.png", "width": 1080, "height": 1440 },
    { "role": "page2", "file": "03_page2.png", "path": "…/final/03_page2.png", "width": 1080, "height": 1440 },
    { "role": "page3", "file": "04_page3.png", "path": "…/final/04_page3.png", "width": 1080, "height": 1440 }
  ],
  "order": ["cover", "page1", "page2", "page3"],
  "status": "ready_for_review",
  "validation": { "render_success": true, "errors": [], "warnings": [] }
}
```

伴随字段：`zhanghao`（发布账号标识），随发布数据一起提交给发布工具，但不属于发布内容本身。

**作用**：汇总所有待发布信息，形成完整的发布数据包。v0.1 实现方式：[pipeline/assemble_publish.py](../pipeline/assemble_publish.py) 校验通过后产出 publish_data.json，并把 page_data.json 的 `publish.status` 更新为 `ready_for_review`。

**判断标准（assemble 校验项，任一失败退出码 1、不产出发布包）**

- validation.json 的 `overall.render_success == true`
- final/ 下四张图存在、为 PNG、严格 1080×1440（3:4）
- `publish.images` 恰好 4 张且顺序 cover → page1 → page2 → page3
- `title` 非空且 ≤ 20 字；`content` 非空且 ≤ 1000 字

---

### ⑫ 人工确认

**输入**

- 发布数据包（标题、正文、4 张图片、账号）

**输出**

- 确认通过 / 退回修改

**重点检查清单**

1. 标题
2. 正文
3. 封面
4. 图片顺序
5. 图片内容
6. 是否存在敏感或不适合发布的信息
7. 发布账号

**处理规则**

- 人工确认通过，才能执行最终发布
- 发现问题则退回修改，修改后重新进入人工确认
- 发布准备包 `status` 在确认前为 `ready_for_review`；**人工确认放行后才允许浏览器执行发布**，程序不做无人值守发布；发布确认成功后才流转 `published`

---

### ⑬ 发布

**输入**

- 人工确认放行后的发布数据包（publish_data.json）

**输出**

- 平台发布结果；publish_data.json 更新 `status=published` + `published_at`
- publish_result.json：状态、时间、成功信号（`auto:url_changed` / `auto:toast_text` / `manual:*` 如实区分）、结果页 URL、截图

**v0.1 实现方式（2026-10-02 已真实跑通）**

由 [pipeline/publish_xhs.py](../pipeline/publish_xhs.py) 用 Playwright 驱动本机 Chrome/Edge 完成：持久化登录态（首次人工扫码）→ 进入图文发布页 → 按序上传 4 图（智能等待预览稳定）→ 填写标题正文（轮询回读校验）→ 文件信号人工确认闸口 → 点击发布（处理二次确认弹窗）→ 强成功信号判定（跳转作品管理页 /「发布成功」提示，证据不足转人工裁定，防止误入草稿箱）。

**处理规则**

- 登录失效、验证码、滑块：立即暂停并保留现场，交人工处理，不做任何绕过；登录失效会明确提示，不误判为发布失败
- 自动判定失败：不重复提交，publish_data.json 不改动，写清 stage/reason/截图到 publish_result.json，等待人工处理
- 证据不足（unknown）：保留浏览器现场，由人工目检后给信号，或事后用 `mark` 子命令裁定
- 只在有明确成功证据（或人工裁定）时才写 `published`，绝不把"点过按钮"当成发布成功

---

## 数据结构汇总

### 文案结果

```json
{
  "title": "小红书标题",
  "reasoning_content": "小红书正文"
}
```

### 元素拆分结果

```json
{
  "main_image": "主要视觉元素",
  "element_img1": "辅助元素1",
  "element_img2": "辅助元素2"
}
```

### 最终发布数据

```json
{
  "title": "最终标题",
  "content": "最终正文",
  "images": [
    "cover",
    "page1",
    "page2",
    "page3"
  ]
}
```

### 平台字段约束

- `title`：不超过 20 个字符（小红书标题上限）
- `content`：不超过 1000 字（小红书正文上限）
- 图片：**严格 1080×1440（精确 3:4）竖版**，由渲染器固定画布保证，逐张校验
- 完全由 AI 生成的内容，按小红书平台规则进行 AI 生成内容标注

---

## 判断标准汇总

### 合格结果

- 标题存在
- 正文完整
- 图片数量正确（4 张）
- 封面存在
- 三张内容页存在
- 图片顺序正确（cover → page1 → page2 → page3）
- 图片内容与文案一致
- 图片整体风格基本统一
- 没有明显乱码
- 没有关键字段为空
- 发布信息完整

### 不合格结果

| 类别 | 问题 |
|---|---|
| 文案问题 | 标题缺失、正文缺失、内容与主题明显无关、出现明显虚构信息 |
| 图片问题 | 图片数量不足、图片重复、图片内容与主题无关、主体明显缺失、图片之间风格冲突严重 |
| 排版问题 | 封面文字无法识别、文字被主要视觉元素遮挡、页面信息过度拥挤、内容页出现大量重复信息 |
| 工作流问题 | 图片顺序错误、关键字段为空、节点输出无法被下一节点使用 |
| 发布问题 | 账号信息缺失、发布数据不完整、外部发布工具返回失败 |

---

## 异常处理汇总

| 异常 | 处理方式 |
|---|---|
| 文案生成失败 | 重新执行文案生成；连续失败则停止工作流、保留错误信息、要求重新输入主题 |
| 元素拆分失败 | 先检查文案输出是否完整；文案不完整则返回文案节点，文案完整则重新执行元素拆分 |
| 图片生成失败 | 只重新生成对应图片，不重跑整个工作流 |
| 图片数量不足 | 检查封面、内容页1、内容页2、内容页3，缺少哪一张就重新生成对应内容 |
| 图片顺序错误 | 进入图片整理步骤重新排序，恢复为封面 → 内容页1 → 内容页2 → 内容页3 |
| 发布失败 | 不重复提交，保留当前标题、正文和 4 张图片，保存错误信息，等待人工处理 |

---

## 发布前检查（Pre-publish Checklist）

执行发布前，必须完成以下检查：

### 自动验证

- [ ] `title` 非空
- [ ] `content` 非空
- [ ] `images.length == 4`
- [ ] `cover` 存在
- [ ] `page1` 存在
- [ ] `page2` 存在
- [ ] `page3` 存在

### 渲染校验 V1–V9（renderer/validate.py，自动执行）

每页渲染后逐页执行；合并报告写入 run 目录 validation.json（`pages` 逐页 + `overall` 汇总）。FAIL 阻断发布准备，WARN 需人工确认。

- [ ] V1 严格尺寸：每张 1080×1440 精确相等，width/height == 0.75（FAIL）
- [ ] V2 数量顺序：文件名/顺序 01_cover.png → 04_page3.png（FAIL）
- [ ] V3 平台标题：title ≤ 20 字（FAIL）
- [ ] V4 文字溢出：无超行/超字/超宽（`text_overflow`，FAIL）
- [ ] V5 字号地板：所有文字 ≥ role 最小字号（FAIL）
- [ ] V6 安全边距：所有槽位在 72px 安全区内（FAIL）
- [ ] V7 元素碰撞：主体像素不遮挡文字（`element_collision`，FAIL）
- [ ] V8 信息密度：四信息带覆盖率（低于阈值 WARN，人工确认）
- [ ] V9 字体可用：字体加载与关键汉字字形抽检（FAIL）

### 内容验证

- [ ] 标题对应主题
- [ ] 正文完整
- [ ] 图片对应正文
- [ ] 无虚构信息

### 视觉验证

- [ ] 封面清晰
- [ ] 主体明确
- [ ] 文字可读
- [ ] 图片风格统一
- [ ] 内容页无明显重复

### 平台规则验证

- [ ] 标题不超过 20 字
- [ ] 正文不超过 1000 字
- [ ] 图片为严格 1080×1440（3:4）竖版（V1 已自动校验）
- [ ] AI 生成内容已按平台规则标注

### 人工确认

- [ ] 标题已确认
- [ ] 正文已确认
- [ ] 封面已确认
- [ ] 图片顺序已确认
- [ ] 图片内容已确认
- [ ] 无敏感/不适合发布的信息
- [ ] 发布账号已确认

**仅当所有检查项均通过，才允许进入发布步骤。**
