# -*- coding: utf-8 -*-
"""小红书浏览器发布闭环（「最后一公里」，稳定性增强版）。

职责边界：
  读取 <run>/publish_data.json
    → 复用本地登录态；无登录态/登录态失效时打开浏览器由【人工扫码登录】
    → 进入小红书创作服务平台「发布图文」页
    → 按 publish_data.json 的顺序上传 4 张图片（智能等待，不靠固定 sleep）
    → 填写标题与正文（轮询回读校验）
    → 暂停在【人工确认闸口】（文件信号），由人工目检后放行
    → 点击发布，处理可能的二次确认弹窗
    → 只在捕获到【强成功信号】时判定自动成功；证据不足时转人工裁定
    → 成功后才回写 publish_data.json(status=published/published_at) 并写 publish_result.json

安全红线：
  - 不保存账号密码；首次登录必须人工扫码
  - 不识别/绕过验证码、滑块或平台风控；登录失效一律暂停交人工
  - publish_data.json 只在确认发布成功后才修改；任何失败都不会破坏它
  - 登录态、截图、闸口信号全部在 <run>/.publish/ 下（.gitignore 已忽略，不入库）

子命令（在项目根目录 xhs-one-click-publish/ 下）：
  python -m pipeline.publish_xhs login   --run output/run-004
      仅完成扫码登录并持久化登录态，不打开发布页、不发布
  python -m pipeline.publish_xhs doctor  --run output/run-004
      纯本地发布前体检（契约/图片尺寸/浏览器/依赖/忽略规则），不开浏览器、不发布
  python -m pipeline.publish_xhs publish --run output/run-004
      完整发布流程（含人工确认闸口）
  python -m pipeline.publish_xhs mark    --run output/run-004 --status published|failed [--note ...]
      浏览器已关闭后，对证据不足（unknown）的结果做人工裁定并回写，不重开浏览器

人工确认闸口（后台运行时无法使用键盘输入，采用文件信号）：
  填充完成后写 <run>/.publish/pending.json，等待：
    <run>/.publish/confirm   → 放行，执行发布
    <run>/.publish/abort     → 中止，不发布
  发布后 25 秒内无强信号时等待：
    <run>/.publish/mark_published / mark_failed

断点/失败恢复：
  - 素材生成不在本脚本职责内，任何重跑都不会重新生成素材
  - 登录态持久化在 <run>/.publish/browser-profile/，重跑通常无需再扫码
  - 每个阶段写 <run>/.publish/stage.json；失败写清 stage/reason/截图
  - 平台编辑器为无状态页面，重跑会从「打开发布页」重新上传/填写（这是正常且安全的）
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:
    sys.exit("缺少依赖 playwright。请执行：python -m pip install playwright\n"
             "（浏览器复用本机 Chrome/Edge，无需 playwright install chromium）")

# ───────────────────────── 常量（集中管理，消除魔法数字） ─────────────────────────

CREATOR_HOME = "https://creator.xiaohongshu.com/"
PUBLISH_URL = "https://creator.xiaohongshu.com/publish/publish?from=menu&target=image"
EXPECTED_IMAGE_COUNT = 4
CANVAS_W, CANVAS_H = 1080, 1440

# 超时 / 轮询（秒）
LOGIN_WAIT_SECONDS = 480       # 人工扫码登录最多等 8 分钟
CONFIRM_WAIT_SECONDS = 900     # 人工确认闸口最多等 15 分钟
UPLOAD_WAIT_SECONDS = 90       # 图片上传完成最多等 90 秒
RESULT_WAIT_SECONDS = 25      # 点击发布后强成功信号观察窗口
SETTLE_WAIT_SECONDS = 8       # 登录重定向 settle 观察窗口
FIELD_READBACK_WAIT = 5       # 填写后等待回读匹配的最长时间
DIALOG_WAIT_SECONDS = 3       # 二次确认弹窗出现的观察窗口
NAV_TIMEOUT_MS = 60000
CONTROL_TIMEOUT_MS = 6000
POLL_SECONDS = 2
POLL_FAST_SECONDS = 0.5

CN_TZ = timezone(timedelta(hours=8))

# 本机浏览器候选路径（不依赖 playwright install chromium 下载自带 Chromium）
_CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    str(Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe"),
]
_EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

# 多候选选择器（平台页面结构可能调整，按顺序尝试）
TITLE_SELECTORS = [
    "#post-title",
    'div[contenteditable="true"][placeholder*="标题"]',
    'div[contenteditable="true"][data-placeholder*="标题"]',
    'input[placeholder*="标题"]',
]
BODY_SELECTORS = [
    "#post-textarea",
    ".tiptap.ProseMirror[contenteditable='true']",
    'div[contenteditable="true"][placeholder*="分享"]',
    'div[contenteditable="true"][data-placeholder*="分享"]',
    'div[contenteditable="true"][placeholder*="生活"]',
]
FILE_INPUT_SELECTOR = 'input[type="file"]'
BLOB_PREVIEW_SELECTOR = 'img[src^="blob:"]'
CONFIRM_DIALOG_SELECTOR = (
    '.el-dialog__wrapper:visible, .el-dialog:visible, .modal-container:visible, '
    '[role="dialog"]:visible, [class*="dialog"]:visible, [class*="confirm"]:visible'
)
LOGIN_AFTER_TEXT = ("发布笔记", "笔记管理", "发布图文笔记")

# 自动成功信号（明确证据才判成功，防止误入草稿箱）
SUCCESS_URL_MARKERS = ("/manage", "/success")
SUCCESS_TEXT = "发布成功"
FAILURE_TEXT = "发布失败"


# ───────────────────────── 基础工具 ─────────────────────────

def now_cn_iso() -> str:
    return datetime.now(CN_TZ).isoformat(timespec="seconds")


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize(text: str) -> str:
    """归一化文本用于回读比较：去掉所有空白。"""
    return "".join((text or "").split())


def read_png_size(path: Path):
    """纯标准库解析 PNG IHDR 宽高；非 PNG 返回 None。"""
    try:
        with open(path, "rb") as f:
            head = f.read(24)
        if len(head) >= 24 and head[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">II", head[16:24])
    except OSError:
        return None
    return None


def shot(page, work_dir: Path, name: str) -> str:
    """截图留证；截图本身失败不阻断主流程。"""
    work_dir.mkdir(parents=True, exist_ok=True)
    p = work_dir / f"{name}.png"
    try:
        page.screenshot(path=str(p), full_page=False)
    except Exception as e:
        return f"截图失败: {e}"
    return str(p)


class StepError(RuntimeError):
    """发布流程某一步失败：携带阶段名、原因、截图文件名。"""

    def __init__(self, stage: str, reason: str, shot_name: str = ""):
        super().__init__(f"[{stage}] {reason}")
        self.stage = stage
        self.reason = reason
        self.shot_name = shot_name


# ───────────────────────── 数据契约 / 结果记录 ─────────────────────────

def load_publish_data(run_dir: Path) -> dict:
    p = run_dir / "publish_data.json"
    if not p.exists():
        sys.exit(f"找不到 {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"publish_data.json 解析失败：{e}")
    images = data.get("images") or []
    if len(images) != EXPECTED_IMAGE_COUNT:
        sys.exit(f"publish_data.json 中 images 数量为 {len(images)}，预期 {EXPECTED_IMAGE_COUNT} 张，终止。")
    for img in images:
        if not Path(img["path"]).exists():
            sys.exit(f"图片不存在：{img['path']}")
    if not (data.get("title") and data.get("content")):
        sys.exit("title 或 content 为空，终止。")
    return data


def write_stage(work_dir: Path, stage: str, **extra) -> None:
    payload = {"stage": stage, "updated_at": now_cn_iso()}
    payload.update(extra)
    write_json(work_dir / "stage.json", payload)


def write_result(run_dir: Path, status: str, **fields) -> Path:
    """统一写 publish_result.json。注意：任何失败状态都不会触碰 publish_data.json。"""
    payload = {"status": status, "at": now_cn_iso(), "run": run_dir.name}
    payload.update(fields)
    out = run_dir / "publish_result.json"
    write_json(out, payload)
    return out


# ───────────────────────── 浏览器启动与登录 ─────────────────────────

def launch_persistent_context(p, profile_dir: Path):
    """用独立用户数据目录启动本机 Chrome/Edge（持久化上下文）。
    登录态天然保存在 profile_dir 中，下次启动直接复用。channel 优先，显式路径兜底。"""
    profile_dir.mkdir(parents=True, exist_ok=True)
    common = dict(headless=False, locale="zh-CN", viewport={"width": 1440, "height": 900})
    errors = []
    for channel in ("chrome", "msedge"):
        try:
            ctx = p.chromium.launch_persistent_context(str(profile_dir), channel=channel, **common)
            print(f"[浏览器] 已通过 channel={channel} 启动（持久化配置目录：{profile_dir}）", flush=True)
            return ctx
        except Exception as e:
            errors.append(f"channel={channel}: {e}")
    for exe in _CHROME_PATHS + _EDGE_PATHS:
        if Path(exe).exists():
            try:
                ctx = p.chromium.launch_persistent_context(str(profile_dir), executable_path=exe, **common)
                print(f"[浏览器] 已通过 executable_path 启动：{exe}（持久化配置目录：{profile_dir}）", flush=True)
                return ctx
            except Exception as e:
                errors.append(f"executable_path={exe}: {e}")
    sys.exit("无法启动本机 Chrome/Edge，请确认已安装其一。原始错误：\n" + "\n".join(errors))


def _login_cookie_ok(context) -> bool:
    """cookie 层面的登录信号。"""
    for c in context.cookies():
        n = c.get("name", "").lower()
        if not c.get("value"):
            continue
        if "web_session" in n or ("session" in n and "xs" in n) or n in ("a1", "webId"):
            return True
    return False


def is_logged_in(page, context) -> bool:
    """登录成功判据：离开 /login 且（命中登录 cookie 或页面出现登录后特征）。"""
    try:
        url = page.url
    except Exception:
        return False
    if "/login" in url or url.startswith("about:"):
        return False
    if _login_cookie_ok(context):
        return True
    for text in LOGIN_AFTER_TEXT:
        try:
            if page.get_by_text(text, exact=False).first.is_visible():
                return True
        except Exception:
            pass
    return False


def find_logged_in_page(context):
    """在所有标签页中寻找已登录页面（扫码后平台可能在新标签打开创作中心）。"""
    for pg in list(context.pages):
        try:
            if is_logged_in(pg, context):
                return pg
        except Exception:
            continue
    return None


def debug_pages(context) -> str:
    parts = []
    for pg in list(context.pages):
        try:
            parts.append(pg.url)
        except Exception:
            parts.append("<closed?>")
    names = ",".join(c.get("name", "") for c in context.cookies()[:12])
    return f"pages={parts} cookies={names}"


def wait_manual_login(context, work_dir: Path, profile_dir: Path):
    """打开创作中心，轮询所有标签页等待人工登录；返回已登录的 page。"""
    had_profile = any(profile_dir.iterdir()) if profile_dir.exists() else False
    page = context.pages[0] if context.pages else context.new_page()
    print("[登录] 正在打开小红书创作服务平台……", flush=True)
    page.goto(CREATOR_HOME, wait_until="commit", timeout=NAV_TIMEOUT_MS)
    reason = "检测到登录态已失效（cookie 过期或被登出）" if had_profile else "当前为首次登录"
    print(
        f"[登录] {reason}。请在弹出的浏览器中【人工扫码登录】（最多等待 {LOGIN_WAIT_SECONDS // 60} 分钟）。"
        "脚本不会接触账号密码；登录成功（无论在当前页还是新开标签页）后会自动接管。",
        flush=True,
    )
    deadline = time.time() + LOGIN_WAIT_SECONDS
    last_debug = 0.0
    while time.time() < deadline:
        logged = find_logged_in_page(context)
        if logged is not None:
            shot(logged, work_dir, "01_logged_in")
            print("[登录] 检测到登录成功，登录态已持久化到本地配置目录。", flush=True)
            write_stage(work_dir, "logged_in")
            return logged
        now = time.time()
        if now - last_debug >= 10:
            print("[登录·等待中] " + debug_pages(context), flush=True)
            last_debug = now
        time.sleep(POLL_SECONDS)
    shot(context.pages[0] if context.pages else page, work_dir, "01_login_timeout")
    raise StepError("login", "等待人工扫码登录超时（可能遇到验证码/滑块，或未完成登录）", "01_login_timeout")


def wait_url_settle(page, seconds: int = SETTLE_WAIT_SECONDS) -> str:
    """等待 SPA 重定向 settle：URL 连续 1 秒不变即认为稳定。"""
    last_url, stable_since = "", 0.0
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            url = page.url
        except Exception:
            url = ""
        if url == last_url and url:
            if stable_since and time.time() - stable_since >= 1:
                return url
            stable_since = stable_since or time.time()
        else:
            last_url, stable_since = url, 0.0
        time.sleep(POLL_FAST_SECONDS)
    return last_url


def ensure_login_and_open_editor(context, work_dir: Path, profile_dir: Path, page):
    """保证登录态有效并打开图文发布页；登录失效给出明确提示（走人工扫码，不误判为发布失败）。"""
    page.goto(PUBLISH_URL, wait_until="commit", timeout=NAV_TIMEOUT_MS)
    wait_url_settle(page)

    logged = find_logged_in_page(context)
    if logged is None:
        # 可能是登录态过期被重定向，也可能从未登录——wait_manual_login 会区分提示
        page = wait_manual_login(context, work_dir, profile_dir)
    else:
        page = logged
    try:
        page.bring_to_front()
    except Exception:
        pass
    page.goto(PUBLISH_URL, wait_until="commit", timeout=NAV_TIMEOUT_MS)
    wait_url_settle(page)

    # 发布过程中被登出的兜底检测：落在 /login 明确报「登录态失效」，而不是后续控件超时
    if "/login" in page.url:
        shot(page, work_dir, "02_login_expired")
        raise StepError("login", "登录态已失效，被重定向到登录页；请重新扫码登录后再跑（不会重复生成素材）",
                        "02_login_expired")
    print("[发布页] 已进入发布图文页，等待上传控件……", flush=True)
    try:
        page.locator(FILE_INPUT_SELECTOR).first.wait_for(state="attached", timeout=30000)
    except PWTimeout:
        shot(page, work_dir, "02_no_file_input")
        raise StepError("open_editor", "未找到图片上传控件（可能未落在图文发布页 target=image）",
                        "02_no_file_input")
    shot(page, work_dir, "02_publish_page_ready")
    write_stage(work_dir, "editor_opened", url=page.url)
    return page


# ───────────────────────── 人工闸口 ─────────────────────────

def wait_for_signal(work_dir: Path, flag: str, abort_flag: str, seconds: int, note: dict) -> bool:
    """文件信号人工闸口。返回 True=放行，False=中止。"""
    (work_dir / flag).unlink(missing_ok=True)
    (work_dir / abort_flag).unlink(missing_ok=True)
    write_json(work_dir / "pending.json", note)
    print(f"[人工闸口] {note.get('message', '等待人工确认')}", flush=True)
    print(f"[人工闸口] 放行请创建文件：{work_dir / flag}", flush=True)
    print(f"[人工闸口] 中止请创建文件：{work_dir / abort_flag}", flush=True)
    deadline = time.time() + seconds
    while time.time() < deadline:
        if (work_dir / abort_flag).exists():
            print("[人工闸口] 收到 abort 信号，中止。", flush=True)
            return False
        if (work_dir / flag).exists():
            print("[人工闸口] 收到 confirm 信号，继续。", flush=True)
            return True
        time.sleep(POLL_SECONDS)
    raise StepError("manual_gate", "等待人工确认超时（未做任何发布动作）")


# ───────────────────────── 上传 / 填写 ─────────────────────────

def upload_images(page, image_paths, work_dir: Path) -> None:
    """按序提交图片，智能等待预览稳定（连续两次观测到足够预览，取代固定 sleep）。"""
    file_inputs = page.locator(FILE_INPUT_SELECTOR)
    target_input = None
    for i in range(file_inputs.count()):
        inp = file_inputs.nth(i)
        accept = inp.get_attribute("accept") or ""
        if "image" in accept or not accept:
            target_input = inp
            break
    target_input = target_input or file_inputs.first
    target_input.set_input_files(image_paths)
    print(f"[上传] 已按顺序提交 {len(image_paths)} 张图片，等待上传完成……", flush=True)

    deadline = time.time() + UPLOAD_WAIT_SECONDS
    stable_hits = 0
    while time.time() < deadline:
        preview_count = page.locator(BLOB_PREVIEW_SELECTOR).count()
        if preview_count >= EXPECTED_IMAGE_COUNT:
            stable_hits += 1
            if stable_hits >= 2:  # 连续两次（间隔 0.5s）数量达标，认为预览稳定
                shot(page, work_dir, "03_after_upload")
                print(f"[上传] 完成：稳定观测到 {preview_count} 个图片预览。", flush=True)
                write_stage(work_dir, "uploaded", preview_count=preview_count)
                return
        else:
            stable_hits = 0
        time.sleep(POLL_FAST_SECONDS)

    shot(page, work_dir, "03_upload_timeout")
    raise StepError(
        "upload",
        f"在 {UPLOAD_WAIT_SECONDS}s 内未稳定观测到 {EXPECTED_IMAGE_COUNT} 个图片预览"
        "（网络慢或上传失败；可重跑本命令，素材不会重新生成）",
        "03_upload_timeout",
    )


def _read_field_text(loc, tag: str) -> str:
    if tag in ("input", "textarea"):
        return loc.input_value()
    return loc.inner_text()


def fill_field(page, selectors, text: str, label: str, work_dir: Path, shot_name: str) -> str:
    """在多候选选择器中找到可见输入区填入文本，并轮询回读校验；返回命中的选择器。"""
    target = normalize(text)
    last_err = None
    for sel in selectors:
        loc = page.locator(sel).first
        try:
            loc.wait_for(state="visible", timeout=CONTROL_TIMEOUT_MS)
        except Exception as e:
            last_err = e
            continue
        try:
            tag = loc.evaluate("el => el.tagName.toLowerCase()")
            if tag in ("input", "textarea"):
                loc.fill("")
                loc.fill(text)
            else:
                loc.click()
                page.keyboard.press("Control+A")
                page.keyboard.press("Delete")
                page.keyboard.insert_text(text)

            # 轮询回读（取代固定 sleep）：目标全文去空白后应出现在回读内容中
            matched = False
            read_deadline = time.time() + FIELD_READBACK_WAIT
            actual = ""
            while time.time() < read_deadline:
                try:
                    actual = _read_field_text(loc, tag)
                except Exception:
                    actual = ""
                compact = normalize(actual)
                if compact and (target in compact or target[:10] in compact):
                    matched = True
                    break
                time.sleep(POLL_FAST_SECONDS)

            if matched:
                shot(page, work_dir, shot_name)
                print(f"[填写] {label} 完成（命中 {sel}，回读字符数 {len(normalize(actual))}）", flush=True)
                return sel
            last_err = RuntimeError(f"填入后回读不匹配，回读前 10 字：{normalize(actual)[:10]!r}")
        except Exception as e:
            last_err = e
    shot(page, work_dir, shot_name + "_FAILED")
    raise StepError("fill_field", f"{label} 填写失败：{last_err}", shot_name + "_FAILED")


def fill_content(page, title: str, content: str, work_dir: Path):
    """上传完成后填写标题与正文；填写前再检一次登录态。"""
    if "/login" in page.url:
        shot(page, work_dir, "05_login_expired")
        raise StepError("login", "填写阶段登录态已失效，请重新扫码登录后再跑", "05_login_expired")
    dump_buttons(page, work_dir)
    title_sel = fill_field(page, TITLE_SELECTORS, title, "标题", work_dir, "04_title")
    body_sel = fill_field(page, BODY_SELECTORS, content, "正文", work_dir, "05_body")
    shot(page, work_dir, "06_filled")
    write_stage(work_dir, "filled", title_selector=title_sel, body_selector=body_sel)
    return title_sel, body_sel


def dump_buttons(page, work_dir: Path) -> None:
    """导出页面可见按钮清单，便于发布按钮找不到时排查（平台改版定位用）。"""
    try:
        btns = page.evaluate(
            """() => Array.from(document.querySelectorAll('button,[role=button]')).map(e => ({
                text: (e.innerText||'').trim().slice(0,20),
                cls: (e.className||'').toString().slice(0,80),
                disabled: !!e.disabled,
                visible: !!(e.offsetWidth || e.offsetHeight)
            }))"""
        )
        write_json(work_dir / "buttons.json", {"buttons": btns, "url": page.url})
    except Exception:
        pass


# ───────────────────────── 发布点击与结果判定 ─────────────────────────

def find_publish_button(page):
    """找可见、可用、文本恰为「发布」的主按钮（多个时取最后一个，即底部主操作）。"""
    candidates = page.locator(
        '.publishBtn, [class*="publish"] button, '
        'button:has-text("发布"), [role="button"]:has-text("发布")'
    )
    matches = []
    for i in range(candidates.count()):
        loc = candidates.nth(i)
        try:
            if not loc.is_visible():
                continue
            text = " ".join((loc.inner_text() or "").split())
            if text in ("发布", "发 布") and loc.is_enabled():
                matches.append(loc)
        except Exception:
            continue
    return matches[-1] if matches else None


def click_second_confirm_if_any(page) -> bool:
    """点击发布后若出现二次确认弹窗，在弹窗内点「发布/确定」。轮询观察，不用固定 sleep。"""
    deadline = time.time() + DIALOG_WAIT_SECONDS
    while time.time() < deadline:
        dialog = page.locator(CONFIRM_DIALOG_SELECTOR).first
        try:
            if dialog.count() and dialog.is_visible():
                btn = dialog.locator(
                    'button:has-text("发布"), button:has-text("确定"), '
                    '[role="button"]:has-text("发布"), [role="button"]:has-text("确定")'
                ).first
                if btn.is_visible():
                    btn.click()
                    print("[发布] 已在二次确认弹窗中点击确认。", flush=True)
                    return True
        except Exception:
            pass
        time.sleep(POLL_FAST_SECONDS)
    return False


def observe_result(page, work_dir: Path) -> dict:
    """强成功信号观察窗口：有明确证据才判成功/失败；否则 unknown 保留现场转人工裁定。"""
    deadline = time.time() + RESULT_WAIT_SECONDS
    while time.time() < deadline:
        url = page.url
        success_url = ("/publish/publish" not in url) and any(m in url for m in SUCCESS_URL_MARKERS)
        toast_success = toast_fail = False
        try:
            toast_success = page.get_by_text(SUCCESS_TEXT).first.is_visible()
        except Exception:
            pass
        try:
            toast_fail = page.get_by_text(FAILURE_TEXT).first.is_visible()
        except Exception:
            pass
        if success_url or toast_success:
            shot(page, work_dir, "07_published")
            return {"verdict": "published", "final_url": url,
                    "signal": "auto:url_changed" if success_url else "auto:toast_text"}
        if toast_fail:
            shot(page, work_dir, "07_publish_failed")
            return {"verdict": "failed", "final_url": url, "signal": "auto:failure_toast"}
        time.sleep(1)
    shot(page, work_dir, "07_result_unknown")
    return {"verdict": "unknown", "final_url": page.url, "signal": "no_strong_signal"}


def click_publish_and_observe(page, work_dir: Path) -> dict:
    btn = find_publish_button(page)
    if btn is None:
        shot(page, work_dir, "07_no_publish_button")
        raise StepError("click_publish", "未找到可点击的「发布」按钮（见 buttons.json 排查页面结构变化）",
                        "07_no_publish_button")
    btn.scroll_into_view_if_needed()
    btn.click()
    print("[发布] 已点击「发布」按钮。", flush=True)
    write_stage(work_dir, "publish_clicked")
    click_second_confirm_if_any(page)
    result = observe_result(page, work_dir)
    write_stage(work_dir, "observed", verdict=result["verdict"], signal=result["signal"])
    return result


# ───────────────────────── 成功/失败收尾 ─────────────────────────

def finalize_success(run_dir: Path, data: dict, page, result: dict, signal_kind: str) -> None:
    """只有确认成功才修改 publish_data.json；同步写 publish_result.json。"""
    published_at = now_cn_iso()
    final_url = page.url
    data["status"] = "published"
    data["published_at"] = published_at
    data["publish_result"] = {"platform": "xiaohongshu_creator", "final_url": final_url, "signal": signal_kind}
    write_json(run_dir / "publish_data.json", data)
    write_result(
        run_dir, "published", published_at=published_at, platform="xiaohongshu_creator",
        final_url=final_url, title=data["title"], images_count=EXPECTED_IMAGE_COUNT,
        signal=signal_kind, screenshot=str(run_dir / ".publish" / "07_published.png"),
    )
    print(f"[结果] 发布成功（信号：{signal_kind}）。publish_data.json 已更新 status=published。", flush=True)
    print(f"[结果] 结果页 URL：{final_url}", flush=True)


def finalize_failure(run_dir: Path, result: dict, work_dir: Path) -> None:
    write_result(
        run_dir, "failed", final_url=result.get("final_url"), signal=result.get("signal"),
        stage="observe_result", screenshot=str(work_dir / "07_publish_failed.png"),
        note="自动判定发布失败/未证实；请人工核查，必要时可用 mark 子命令补录裁定结果",
    )


# ───────────────────────── 子命令 ─────────────────────────

def cmd_login(run_dir: Path) -> None:
    work_dir = run_dir / ".publish"
    profile_dir = work_dir / "browser-profile"
    with sync_playwright() as p:
        context = launch_persistent_context(p, profile_dir)
        try:
            page = wait_manual_login(context, work_dir, profile_dir)
            print("[登录] 完成，3 秒后关闭浏览器（登录态已保存，下次无需再扫码）。", flush=True)
            page.wait_for_timeout(3000)
        finally:
            context.close()


def cmd_publish(run_dir: Path) -> None:
    data = load_publish_data(run_dir)
    if data.get("status") == "published":
        sys.exit("publish_data.json 状态已是 published，为防重复发布，终止。")

    work_dir = run_dir / ".publish"
    work_dir.mkdir(parents=True, exist_ok=True)
    profile_dir = work_dir / "browser-profile"
    for f in ("confirm", "abort", "mark_published", "mark_failed"):
        (work_dir / f).unlink(missing_ok=True)

    title, content = data["title"], data["content"]
    image_paths = [img["path"] for img in data["images"]]
    print(f"[启动] run={run_dir.name}  标题={title!r}  图片={len(image_paths)} 张", flush=True)
    write_stage(work_dir, "started")

    with sync_playwright() as p:
        context = launch_persistent_context(p, profile_dir)
        page = context.pages[0] if context.pages else context.new_page()
        try:
            page = ensure_login_and_open_editor(context, work_dir, profile_dir, page)
            upload_images(page, image_paths, work_dir)
            title_sel, body_sel = fill_content(page, title, content, work_dir)

            ok = wait_for_signal(
                work_dir, "confirm", "abort", CONFIRM_WAIT_SECONDS,
                {
                    "message": "图片/标题/正文已自动填充。请在浏览器中目检，确认无误后放行发布。",
                    "at": now_cn_iso(), "title": title,
                    "images_in_order": [Path(x).name for x in image_paths],
                    "title_selector": title_sel, "body_selector": body_sel,
                    "screenshot": str(work_dir / "06_filled.png"),
                },
            )
            if not ok:
                shot(page, work_dir, "08_aborted")
                write_result(run_dir, "aborted", reason="manual_abort_before_publish",
                             screenshot=str(work_dir / "08_aborted.png"))
                write_stage(work_dir, "aborted")
                print("[结束] 已按人工指示中止，未发布；publish_data.json 未改动。", flush=True)
                return

            result = click_publish_and_observe(page, work_dir)
            verdict = result["verdict"]
            signal_kind = result.get("signal", "")

            if verdict == "unknown":
                # 证据不足不武断下结论：保留浏览器，等待人工目检后给信号
                ok2 = wait_for_signal(
                    work_dir, "mark_published", "mark_failed", CONFIRM_WAIT_SECONDS,
                    {"message": f"{RESULT_WAIT_SECONDS} 秒内未捕获强成功信号。"
                                "请目检浏览器/作品管理页：确认已发布则放行标记，否则标记失败。",
                     "at": now_cn_iso(), "final_url": result["final_url"],
                     "screenshot": str(work_dir / "07_result_unknown.png")},
                )
                if ok2:
                    verdict, signal_kind = "published", "manual:verdict_after_unknown"
                else:
                    verdict, signal_kind = "failed", "manual:failed_after_unknown"

            if verdict == "published":
                finalize_success(run_dir, data, page, result, signal_kind)
                write_stage(work_dir, "done", status="published")
                page.wait_for_timeout(3000)
            else:
                result["signal"] = signal_kind
                finalize_failure(run_dir, result, work_dir)
                write_stage(work_dir, "failed", signal=signal_kind)
                print("[结果] 判定发布失败/未证实。现场已截图，浏览器保留 30 秒供核查。", flush=True)
                page.wait_for_timeout(30000)

        except StepError as e:
            # 业务步骤失败：截图 + 明确 stage/reason；绝不修改 publish_data.json
            shot_name = e.shot_name or f"error_{e.stage}"
            shot_path = shot(page, work_dir, shot_name) if page else ""
            write_result(run_dir, "failed", stage=e.stage, reason=e.reason, screenshot=shot_path)
            write_stage(work_dir, "failed", stage=e.stage, reason=e.reason)
            print(f"[失败·阶段={e.stage}] {e.reason}", flush=True)
            print(f"[失败] 截图：{shot_path}；结果记录：{run_dir / 'publish_result.json'}", flush=True)
            print("[失败] publish_data.json 未改动；排除问题后重跑本命令即可（素材不重新生成）。", flush=True)
            page.wait_for_timeout(15000)
            sys.exit(2)
        finally:
            context.close()


def cmd_mark(run_dir: Path, status: str, note: str) -> None:
    """浏览器关闭后对 unknown 结果做人工裁定（不重开浏览器、不触碰平台）。"""
    data = load_publish_data(run_dir)
    if status == "published":
        if data.get("status") == "published":
            sys.exit("当前已是 published，无需重复标记。")
        data["status"] = "published"
        data["published_at"] = now_cn_iso()
        data["publish_result"] = {"platform": "xiaohongshu_creator",
                                  "signal": "manual:mark_without_browser", "note": note}
        write_json(run_dir / "publish_data.json", data)
        write_result(run_dir, "published", platform="xiaohongshu_creator",
                     signal="manual:mark_without_browser", title=data["title"],
                     images_count=EXPECTED_IMAGE_COUNT, note=note)
        print("[mark] 已人工裁定为 published，publish_data.json / publish_result.json 已更新。", flush=True)
    else:
        write_result(run_dir, "failed", signal="manual:mark_without_browser", note=note)
        print("[mark] 已人工裁定为 failed，仅写 publish_result.json；publish_data.json 未改动。", flush=True)


def cmd_doctor(run_dir: Path) -> int:
    """纯本地发布前体检：不开浏览器、不发布、不联网。返回进程退出码。"""
    problems, oks = [], []

    # 1) 依赖
    try:
        import playwright  # noqa: F401
        oks.append("playwright 依赖可导入")
    except ImportError:
        problems.append("缺少 playwright：python -m pip install playwright")

    # 2) 本机浏览器
    browsers = [x for x in _CHROME_PATHS + _EDGE_PATHS if Path(x).exists()]
    if browsers:
        oks.append(f"找到本机浏览器：{browsers[0]}")
    else:
        problems.append("未找到本机 Chrome/Edge")

    # 3) 发布数据包契约
    pd_path = run_dir / "publish_data.json"
    if not pd_path.exists():
        problems.append(f"缺少 {pd_path}")
        data = None
    else:
        try:
            data = json.loads(pd_path.read_text(encoding="utf-8"))
            imgs = data.get("images") or []
            if len(imgs) == EXPECTED_IMAGE_COUNT and data.get("title") and data.get("content"):
                oks.append(f"publish_data.json 契约正常（title {len(data['title'])} 字，图片 {len(imgs)} 张，"
                           f"status={data.get('status')}）")
            else:
                problems.append("publish_data.json 契约不完整（images 应为 4 张且 title/content 非空）")
                data = None
            if data and data.get("status") == "published":
                oks.append("当前 status=published（doctor 仅体检；如需重新发布请显式重置状态）")
        except json.JSONDecodeError as e:
            problems.append(f"publish_data.json 解析失败：{e}")
            data = None

    # 4) 四张图片存在 + PNG 签名 + 严格尺寸
    if data:
        for img in data["images"]:
            ip = Path(img["path"])
            if not ip.exists():
                problems.append(f"图片不存在：{ip}")
                continue
            size = read_png_size(ip)
            if size is None:
                problems.append(f"非 PNG 文件：{ip}")
            elif size != (CANVAS_W, CANVAS_H):
                problems.append(f"图片尺寸 {size[0]}x{size[1]} != {CANVAS_W}x{CANVAS_H}：{ip.name}")
            else:
                oks.append(f"{ip.name} {CANVAS_W}x{CANVAS_H}")

    # 5) 登录态位置提示
    profile_dir = run_dir / ".publish" / "browser-profile"
    if profile_dir.exists() and any(profile_dir.iterdir()):
        oks.append(f"存在已保存登录态：{profile_dir}（通常无需再扫码）")
    else:
        oks.append(f"未发现登录态，首次运行需扫码：{profile_dir}")

    # 6) .publish 忽略规则（.gitignore 文本检查；不依赖 git 可执行文件）
    candidates = [run_dir.parents[1] / ".gitignore", Path.cwd() / ".gitignore"]
    gi = next((c for c in candidates if c.exists()), None)
    if gi and ".publish" in gi.read_text(encoding="utf-8"):
        oks.append(f".gitignore 含 .publish 规则：{gi}")
    else:
        problems.append("未在 .gitignore 中发现 .publish 规则，登录态/截图有误提交风险")

    print("=" * 60)
    print(f"doctor 体检报告 — {run_dir}")
    print("=" * 60)
    for o in oks:
        print(f"  [OK] {o}")
    for prob in problems:
        print(f"  [!!] {prob}")
    print("=" * 60)
    if problems:
        print(f"结论：{len(problems)} 个问题需先处理。")
        return 1
    print("结论：全部通过，可执行 publish。")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="小红书浏览器发布闭环（登录/体检/发布/人工裁定）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name in ("login", "publish", "doctor"):
        s = sub.add_parser(name)
        s.add_argument("--run", default="output/run-004", help="run 目录（默认 output/run-004）")

    sm = sub.add_parser("mark")
    sm.add_argument("--run", default="output/run-004")
    sm.add_argument("--status", choices=("published", "failed"), required=True)
    sm.add_argument("--note", default="")

    args = ap.parse_args()
    run_dir = Path(args.run).resolve()
    if not run_dir.is_dir():
        sys.exit(f"run 目录不存在：{run_dir}")

    if args.cmd == "login":
        cmd_login(run_dir)
    elif args.cmd == "doctor":
        sys.exit(cmd_doctor(run_dir))
    elif args.cmd == "mark":
        cmd_mark(run_dir, args.status, args.note)
    else:
        cmd_publish(run_dir)


if __name__ == "__main__":
    main()
