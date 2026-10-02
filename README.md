# xhs-one-click-publish

小红书图文一键发布 Skill：将用户输入的主题或素材，转化为一套完整的小红书图文笔记，并真实发布到小红书——**标题 + 正文 + 1 张封面 + 3 张内容页**，全部由 Pillow 确定性渲染为严格 1080×1440（3:4），经 V1–V9 自动校验与发布准备包组装后，由 Playwright 驱动本机浏览器完成上传与填写，**经人工确认闸口后发布**。

> **全链路已于 2026-10-02 用真实账号端到端跑通**：素材 → 四页渲染 → V1–V9 校验 → 浏览器上传 4 图 / 填标题正文 → 人工确认 → 小红书真实发布成功。样例见 [output/run-004/](output/run-004/publish_data.json)（`status=published`，[publish_result.json](output/run-004/publish_result.json)）。
>
> 发布红线：**首次登录需人工扫码；发布前必须经过人工确认，程序不做无人值守发布**；不识别/绕过验证码与滑块，遇到登录失效一律暂停交人工处理。

## 1. 项目解决的问题

传统小红书图文制作需要在文案、图片生成、抠图、排版、发布等多个工具之间反复切换，常见问题：

- 文案与图片不对应，图片顺序错乱
- 封面与内容页风格不一致
- AI 直接生成成图时中文文字不可控（错字、乱排）
- 图片比例不严格、留白失衡、文字被主体遮挡
- 关键字段缺失仍然进入发布
- 最后一步仍需手动逐张上传、复制粘贴，无法闭环

本 Skill 把这条生产链整理为一条**固定输入 → 处理步骤 → 输出结构 → 质量检查**的流水线：AI 只负责生成视觉素材（透明主体、装饰、背景），**所有中文文字由程序渲染**，排版由模板盒模型确定，发布前由自动校验 + 人工确认双重把关，最后由浏览器自动完成上传与填写。

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
⑫ 浏览器发布（Playwright）        → 扫码登录（仅首次）→ 上传 4 图 → 填标题正文 → 人工确认闸口
  ↓
⑬ 发布并核验                      → 点击发布 → 强成功信号判定 → status=published + publish_result.json
```

各节点详细输入输出、判断标准与异常处理见 [references/workflow.md](references/workflow.md)；Skill 完整定义见 [SKILL.md](SKILL.md)。

## 3. 项目目录结构

```text
xhs-one-click-publish/
├── SKILL.md                        # Skill 核心定义（触发、流程、输入输出、约束、验证）
├── README.md                       # 本文件
├── LICENSE                         # MIT 许可证
├── requirements.txt                # Pillow + playwright（复用本机 Chrome/Edge）
├── .env.example                    # APIMART_API_KEY / APIMART_BASE（.env 不入库）
├── services/
│   └── gpt_image2.py               # gpt-image-2 封装：透明背景直出、重试、任务轮询
├── pipeline/
│   ├── generate_assets.py          # 节点③④：素材生成 + alpha 验收门禁 → assets_manifest.json
│   ├── assemble_publish.py         # 节点⑪：发布准备包校验与组装 → publish_data.json
│   └── publish_xhs.py              # 节点⑫⑬：Playwright 浏览器发布（登录态持久化/上传/填写/人工闸口/结果回写）
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
    └── run-004/                    # ★ 完整闭环真实样例（素材→渲染→校验→真实发布，status=published）
        └── .publish/               # 浏览器登录态/过程截图/闸口信号（已 gitignore，绝不入库）
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
| [pipeline/publish_xhs.py](pipeline/publish_xhs.py) | Playwright 浏览器发布：本机 Chrome/Edge（无需下载 Chromium）、持久化登录配置（首次人工扫码，之后复用）、按序上传 4 图、自动填写标题正文、**文件信号人工确认闸口**、强成功信号判定（跳转作品管理/「发布成功」提示，防止误入草稿箱）、回写 publish_data.json 与 publish_result.json |

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
├── publish_data.json       # 发布数据包（成功后 status=published，含 published_at）
└── publish_result.json     # 发布结果记录（状态/时间/成功信号/证据）
```

## 6. 运行方式

```bash
pip install -r requirements.txt        # Pillow + playwright（浏览器复用本机 Chrome/Edge）
cp .env.example .env                   # 填入 APIMART_API_KEY（仅素材生成需要）

# ① 生成素材（已有验收通过的素材则自动跳过；--force 强制重新生成）
python pipeline/generate_assets.py --run output/run-004

# ② 四页渲染 + 逐页 V1–V9 校验（也可 --template cover 单页）
python renderer/render_cli.py --run output/run-004

# ③ 组装发布准备包（校验通过后产出 publish_data.json，status=ready_for_review）
python pipeline/assemble_publish.py --run output/run-004

# ④ 浏览器真实发布（首次会弹出浏览器，需人工扫码登录一次）
python -m pipeline.publish_xhs publish --run output/run-004
#   仅预先完成登录并保存登录态，可先执行：
#   python -m pipeline.publish_xhs login --run output/run-004
```

任一内容环节校验 FAIL 时退出码 1 并给出具体原因（如 `[title] 字符超预算: 27 > maxChars=8`），修正 page_data 后重跑即可；不盲目重跑全流程。

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

## 9. 发布流程与人工确认机制

[pipeline/publish_xhs.py](pipeline/publish_xhs.py) 的发布步骤：

1. **启动本机浏览器**：复用已安装的 Chrome/Edge（不下载 Playwright 自带 Chromium），使用独立持久化配置目录 `<run>/.publish/browser-profile/`
2. **登录**：首次运行打开小红书创作服务平台，由**人工扫码登录**（程序不接触账号密码）；登录态保存在本地配置目录，之后运行自动复用
3. **进入图文发布页**：`creator.xiaohongshu.com/publish/publish?target=image`，按 publish_data.json 的顺序用文件选择器上传 4 张图片，并等待图片预览出现
4. **填写标题与正文**：自动填充并回读校验；全过程截图留存在 `<run>/.publish/`
5. **人工确认闸口**：填充完成后脚本暂停并写 `pending.json`，等待文件信号——人工目检浏览器后：
   - 放行：创建 `<run>/.publish/confirm`
   - 中止：创建 `<run>/.publish/abort`
6. **发布与强成功判定**：放行后点击「发布」（含可能的二次确认弹窗），仅当捕获**强成功信号**（跳转作品管理页 / 出现「发布成功」提示）才判定成功；否则判定失败/未知并保留浏览器现场，等待人工裁定，**绝不把"点过按钮"当成发布成功**（防止误入草稿箱）
7. **结果回写**：成功后 publish_data.json 更新为 `status=published` + `published_at`，并写 publish_result.json

遇到验证码、滑块、登录失效：脚本直接暂停并保留现场，交人工处理，**不做任何绕过**。

> 2026-10-02 run-004 的真实验证中：登录、上传、填写均由脚本自动完成；发布按钮由人工在浏览器点击，结果经人工目检确认（记录于 publish_result.json，信号 `manual_click_and_confirmation`）。脚本内置的自动点击与强信号判定逻辑保留，供后续复跑使用。

## 10. 当前示例：run-004（已真实发布）

[output/run-004/](output/run-004/publish_data.json) 是完整闭环的真实产物，主题「夏季护肤做减法，三步就够了」：

```text
run-004/
├── asset_jobs.json / assets/（main_subject.png、element_1.png、element_2.png）
├── assets_manifest.json     # all_ok: true（透明素材 alpha 门禁全过）
├── page_data.json           # pages 四页内容 + publish 契约
├── final/01_cover.png … 04_page3.png   # 4×1080×1440
├── validation.json          # 4 页 × V1–V9 全 PASS，零 WARN
├── publish_data.json        # title 13 字 / content 192 字 / status=published
└── publish_result.json      # 2026-10-02 真实发布结果记录
```

注：`output/run-001`、`run-002` 为早期实验产物（白底生成 + 抠图路线），仅作历史对比与离线 Pillow 依赖来源，**不是当前正式实现**；`run-003` 为渲染器封面小样。

## 11. 已知限制

- **人工确认是发布红线**：程序不会在无人确认时发布；首次登录必须人工扫码。
- **验证码/滑块/登录失效不自动处理**：直接暂停交人工，不做绕过。
- **发布页面选择器随平台可能变化**：标题/正文/发布按钮采用多候选选择器，平台改版后可能需要更新。
- **内容页版式两种**：page_step / page_summary；清单型版式（content_list）未实现。
- **主题一致性靠人工**：V9 是字体/字形校验；标题、正文、图片的主题一致性与虚构信息检查目前由人工确认承担。
- **依赖本机字体**：fonts.json 指向 Windows 自带字体（微软雅黑链），无字体时 V9 FAIL。
- **素材生成依赖外部 API**：gpt-image-2 经 APIMart 中转，需要网络与 key；探针结论基于 2026-10-02 实测，接口行为可能变化（alpha 门禁会兜底拦截）。
- **单主题令牌**：一个 run 一套 theme；多主题混排未支持。
- run-001/run-002 的历史脚本（抠图、floodfill 等）保留在 output 下仅供追溯，不再维护。

## 12. 后续计划

- 发布脚本的下一次真实复跑：验证「自动点击发布 + 强成功信号自动判定」全自动化路径（本次人工点击已确认链路可用）。
- 发布失败/草稿箱的自动识别与一键退回填充态。
- 清单型内容页版式（content_list），覆盖非步骤型主题。
- 主题一致性自动校验（V9 扩展：标题/正文/图片关键词一致性）。
- 多 theme 支持（不同视觉风格模板包）。

## 许可证

本项目以 [MIT License](LICENSE) 开源。第三方依赖 Pillow（HPND 许可）、Playwright（Apache-2.0）与所调用的图像生成服务归其各自权利人所有；AI 生成内容的版权与平台合规性（含 AI 生成标注义务）由使用者自行评估。
