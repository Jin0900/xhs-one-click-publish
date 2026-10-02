# xhs-one-click-publish

小红书图文生成 Skill（v0.1）：将用户输入的主题或素材，转化为一套可直接用于小红书发布的完整图文内容——**标题 + 正文 + 1 张封面 + 3 张内容页**，全部由 Pillow 确定性渲染为严格 1080×1440（3:4），并经 V1–V9 自动校验与发布准备包组装，停在 `ready_for_review` 等待人工确认。

> 当前版本为 **v0.1 闭环**：流程到「发布准备包」为止，**未实现自动发布**（Playwright 自动发布列入 v0.2 规划）。完整闭环真实样例见 [output/run-004/](output/run-004/page_data.json)。

## 1. 项目解决的问题

传统小红书图文制作需要在文案、图片生成、抠图、排版、发布等多个工具之间反复切换，常见问题：

- 文案与图片不对应，图片顺序错乱
- 封面与内容页风格不一致
- AI 直接生成成图时中文文字不可控（错字、乱排）
- 图片比例不严格、留白失衡、文字被主体遮挡
- 关键字段缺失仍然进入发布

本 Skill 把这条生产链整理为一条**固定输入 → 处理步骤 → 输出结构 → 质量检查**的流水线：AI 只负责生成视觉素材（透明主体、装饰、背景），**所有中文文字由程序渲染**，排版由模板盒模型确定，发布前由自动校验 + 人工确认双重把关。

## 2. Skill 工作流

```text
主题/输入
  ↓
① 文案生成                        → title / reasoning_content
  ↓
② 视觉元素拆分                    → main_image / element_img1 / element_img2
  ↓
③ 主图/副图生成（透明背景直出）    → main_subject.png / element_1.png / element_2.png
  ↓                                （gpt-image-2，background=transparent + PNG）
④ 素材透明度验收（alpha 门禁）     → assets_manifest.json
  ↓
⑤ 首页文字拆分                    → page_data.json（pages 四页内容 + publish）
  ↓
⑥–⑨ 封面/内容页制作（Pillow 渲染） → final/01_cover.png … 04_page3.png（逐页 V1–V9 校验）
  ↓
⑩ 图片整理/内容组合               → 固定顺序 4 张集合
  ↓
⑪ 发布准备                        → publish_data.json（status=ready_for_review）
  ↓
⑫ 人工确认                        → 确认通过 / 退回修改
  ↓
⑬ 发布（外部工具，v0.1 未实现）
```

各节点详细输入输出、判断标准与异常处理见 [references/workflow.md](references/workflow.md)；Skill 完整定义见 [SKILL.md](SKILL.md)。

## 3. 项目目录结构

```text
xhs-one-click-publish/
├── SKILL.md                        # Skill 核心定义（触发、流程、输入输出、约束、验证）
├── README.md                       # 本文件
├── LICENSE                         # MIT 许可证
├── requirements.txt                # Pillow>=12.3,<13
├── .env.example                    # APIMART_API_KEY / APIMART_BASE（.env 不入库）
├── services/
│   └── gpt_image2.py               # gpt-image-2 封装：透明背景直出、重试、任务轮询
├── pipeline/
│   ├── generate_assets.py          # 节点③④：素材生成 + alpha 验收门禁 → assets_manifest.json
│   └── assemble_publish.py         # 节点⑪：发布准备包校验与组装 → publish_data.json
├── renderer/
│   ├── model.py                    # 模板/page_data 加载与结构校验（pages 多页契约）
│   ├── text_layout.py              # 字体注册/fallback、CJK 换行、避头尾、溢出判定
│   ├── assets.py                   # 素材装入：cover/contain、锚点、trimTransparent、阴影
│   ├── engine_pillow.py            # 确定性渲染引擎（文字永远最上层）
│   ├── validate.py                 # V1–V9 发布前校验
│   └── render_cli.py               # 渲染入口：--template all（四页）或单页
├── templates/xhs_3x4/
│   ├── theme.json                  # 视觉令牌：色板 / 8 级字号阶 / 间距 / 圆角 / 密度
│   ├── fonts.json                  # 字体角色 → 本机字体链（含字形抽检清单）
│   ├── template.schema.json        # 模板结构说明
│   └── cover / page1 / page2 / page3.json   # 四页版式（盒模型 + 槽位）
├── references/workflow.md          # 工作流逐步说明（含 Coze 画布对照、v0.1 实现映射）
├── research/                       # 调研与技术方案（含实施结果记录）
└── output/
    ├── run-001/ run-002/           # 历史实验产物（含离线 Pillow libs，非当前正式实现）
    ├── run-003/                    # M3 封面小样
    └── run-004/                    # ★ v0.1 完整闭环样例（素材→渲染→校验→发布包）
```

## 4. 核心模块说明

| 模块 | 职责 |
|---|---|
| [services/gpt_image2.py](services/gpt_image2.py) | gpt-image-2（OpenAI 兼容异步接口，经 APIMart 中转）封装：`background=transparent` + PNG 透明素材直出、429/5xx 指数退避重试、任务轮询。API key 从 `.env` 读取，不入库 |
| [pipeline/generate_assets.py](pipeline/generate_assets.py) | 读取 `<run>/asset_jobs.json`，逐任务生成素材；alpha 门禁验收（RGBA、四角 alpha≤8、透明占比>30%、主体占比 5%~95%）；已存在默认跳过（`--force` 重生成） |
| [renderer/model.py](renderer/model.py) | 模板与 page_data 的加载、结构校验；`pages` 多页契约与 `view(key)` 按页视图 |
| [renderer/text_layout.py](renderer/text_layout.py) | CJK 贪心换行、避头尾、字距、字符预算、溢出判定；字号永不缩到地板以下 |
| [renderer/engine_pillow.py](renderer/engine_pillow.py) | 按模板槽位确定性渲染 1080×1440：背景 cover + wash/scrim、文字槽程序化排版、素材 contain + trimTransparent + 软阴影、媒体 keepOut |
| [renderer/validate.py](renderer/validate.py) | V1–V9 校验，FAIL 阻断、WARN 人工确认 |
| [pipeline/assemble_publish.py](pipeline/assemble_publish.py) | 校验四图与文案契约 → 产出 publish_data.json，status=ready_for_review |

设计原则：**AI 不生成任何成图中文文字**；一切位置来自模板盒模型、一切尺寸来自实测，放不下就 FAIL 报告而不是缩小硬塞。

## 5. 输入输出

**输入**（`<run>/page_data.json`）：

- `topic`：主题
- `pages`：cover/page1/page2/page3 四页各自的 `content`（标题、正文要点、标签等）与 `assets`（素材路径）
- `publish`：`title`（≤20 字）、`content`（≤1000 字）、`images`（固定 4 张顺序）、`status`

**素材输入**（`<run>/asset_jobs.json` + [pipeline/generate_assets.py](pipeline/generate_assets.py)）：三张素材的 prompt 与透明要求 → 生成 `main_subject.png`（透明主体）、`element_1.png`（透明装饰）、`element_2.png`（背景）。

**输出**：

```text
<run>/
├── assets/                 # 三张素材 + assets_manifest.json（alpha 门禁结果）
├── final/01_cover.png … 04_page3.png   # 4 张 1080×1440 成图
├── validation.json         # V1–V9 逐页校验 + overall 汇总
├── layout_manifest.json    # 每页槽位实测数据（字号/行数/包围盒）
└── publish_data.json       # 发布准备包（status=ready_for_review）
```

## 6. 运行方式

```bash
pip install -r requirements.txt        # 或离线复用 output/run-002/libs 自带 Pillow
cp .env.example .env                   # 填入 APIMART_API_KEY（仅素材生成需要）

# ① 生成素材（已有验收通过的素材则自动跳过；--force 强制重新生成）
python pipeline/generate_assets.py --run output/run-004

# ② 四页渲染 + 逐页 V1–V9 校验（也可 --template cover 单页）
python renderer/render_cli.py --run output/run-004

# ③ 组装发布准备包（校验通过后产出 publish_data.json）
python pipeline/assemble_publish.py --run output/run-004
```

任一环节校验 FAIL 时退出码 1 并给出具体原因（如 `[title] 字符超预算: 27 > maxChars=8`），修正 page_data 后重跑即可；不盲目重跑全流程。

## 7. 4 页图片规格

| 项 | 规格 |
|---|---|
| 数量 | 固定 4 张：1 封面 + 3 内容页 |
| 尺寸 | 严格 1080×1440 px，精确 3:4（V1 校验 width/height == 0.75） |
| 格式 | PNG（sRGB） |
| 文件名/顺序 | `01_cover.png → 02_page1.png → 03_page2.png → 04_page3.png`，以 [output/run-004/](output/run-004/page_data.json) 实际产物为准 |
| 版式 | cover（封面：主标题/副标题/三步骤/主体/标签）、page1·page2（page_step：胶囊 kicker/标题/英文小标/正文/主体/装饰）、page3（page_summary：三步 recap 胶囊行/正文/标签行） |
| 文字 | 全部程序渲染：CJK 自动换行、避头尾、8 级字号阶、最小字号地板、72px 安全边距 |
| 主题 | 同一 run 共用一套 theme 视觉令牌（植物系夏日 `botanical_summer`） |

## 8. 验证规则（V1–V9）

每页渲染后逐页执行（[renderer/validate.py](renderer/validate.py)），合并报告写入 `validation.json`（`pages` 逐页 + `overall` 汇总）：

| 规则 | 内容 | 级别 |
|---|---|---|
| V1 严格尺寸 | 每张 1080×1440 精确相等，width/height == 0.75 | FAIL |
| V2 数量顺序 | 文件名/顺序 01_cover.png → 04_page3.png | FAIL |
| V3 平台标题 | title ≤ 20 字 | FAIL |
| V4 文字溢出 | 无超行/超字/超宽（`text_overflow`） | FAIL |
| V5 字号地板 | 所有文字 ≥ role 最小字号 | FAIL |
| V6 安全边距 | 所有槽位在 72px 安全区内 | FAIL |
| V7 元素碰撞 | 主体实际像素不遮挡文字（`element_collision`） | FAIL |
| V8 信息密度 | 四信息带覆盖率（疑似空带告警） | WARN |
| V9 字体可用 | 字体加载与关键汉字字形抽检 | FAIL |

发布准备（[pipeline/assemble_publish.py](pipeline/assemble_publish.py)）再校验：`render_success == true`、四图存在且 1080×1440、`images` 恰好 4 张且顺序正确、title/content 契约——全部通过才产出 publish_data.json。

## 9. 发布前人工确认机制

发布准备包的 `status` 固定为 **`ready_for_review`**，流程到此为止，**不会自动发布**。人工确认重点：

1. 标题、正文
2. 封面与三张内容页内容
3. 图片顺序（cover → page1 → page2 → page3）
4. 是否有敏感或不宜发布的信息
5. 发布账号

人工确认通过后，才由（未来的）发布环节提交；发现问题则退回修改并重新走校验。AI 生成内容需按小红书平台规则进行 AI 生成标注。

## 10. 当前示例：run-004

[output/run-004/](output/run-004/page_data.json) 是 v0.1 完整闭环的真实产物，主题「夏季护肤做减法，三步就够了」：

```text
run-004/
├── asset_jobs.json / assets/（main_subject.png、element_1.png、element_2.png）
├── assets_manifest.json     # all_ok: true（透明素材 alpha 门禁全过）
├── page_data.json           # pages 四页内容 + publish 契约
├── final/01_cover.png … 04_page3.png   # 4×1080×1440
├── validation.json          # 4 页 × V1–V9 全 PASS，零 WARN
└── publish_data.json        # title 13 字 / content 192 字 / status=ready_for_review
```

注：`output/run-001`、`run-002` 为早期实验产物（白底生成 + 抠图路线），仅作历史对比与离线 Pillow 依赖来源，**不是当前正式实现**；`run-003` 为渲染器封面小样。

## 11. 已知限制

- **不自动发布**：v0.1 只到发布准备包；发布动作需人工在平台完成（或等待 v0.2 的浏览器自动发布）。
- **内容页版式两种**：page_step / page_summary；清单型版式（content_list）未实现。
- **主题一致性靠人工**：V9 是字体/字形校验；标题、正文、图片的主题一致性与虚构信息检查目前由人工确认承担。
- **依赖本机字体**：fonts.json 指向 Windows 自带字体（微软雅黑链），无字体时 V9 FAIL。
- **素材生成依赖外部 API**：gpt-image-2 经 APIMart 中转，需要网络与 key；探针结论基于 2026-10-02 实测，接口行为可能变化（alpha 门禁会兜底拦截）。
- **单主题令牌**：一个 run 一套 theme；多主题混排未支持。
- run-001/run-002 的历史脚本（抠图、floodfill 等）保留在 output 下仅供追溯，不再维护。

## 12. 后续计划

- **v0.2 浏览器自动发布**：Playwright 接入小红书发布流程，前置条件保持人工确认（status 由 ready_for_review 流转）。
- 清单型内容页版式（content_list），覆盖非步骤型主题。
- 主题一致性自动校验（V9 扩展：标题/正文/图片关键词一致性）。
- 多 theme 支持（不同视觉风格模板包）。

## 许可证

本项目以 [MIT License](LICENSE) 开源。第三方依赖 Pillow（HPND 许可）与所调用的图像生成服务归其各自权利人所有；AI 生成内容的版权与平台合规性由使用者自行评估。
