# -*- coding: utf-8 -*-
"""最小可用的小红书浏览器发布闭环（v0.1「最后一公里」）。

职责边界（只做这些）：
  读取 <run>/publish_data.json
    → 复用本地登录态；无登录态时打开浏览器由【人工扫码登录】，登录成功后保存
    → 进入小红书创作服务平台「发布图文」页
    → 按 publish_data.json 的顺序上传 4 张图片
    → 填写标题与正文
    → 暂停在【人工确认闸口】（文件信号），由人工目检后放行
    → 点击发布，处理可能的二次确认弹窗
    → 只在捕获到【强成功信号】时判定成功，否则判定失败/未知并保留现场
    → 成功后回写 publish_data.json(status=published/published_at) 并写 publish_result.json

明确不做：验证码/滑块识别、登录失效自动重试、风控绕过、复杂异常恢复。
遇到这些情况脚本一律暂停，把浏览器留在现场交人工处理。

用法（在项目根目录 xhs-one-click-publish/ 下）：
  python -m pipeline.publish_xhs login   --run output/run-004    # 仅登录并保存登录态
  python -m pipeline.publish_xhs publish --run output/run-004    # 完整发布流程

人工确认闸口（后台运行时无法使用键盘输入，采用文件信号）：
  脚本填充完成后写  <run>/.publish/pending.json  并等待：
    <run>/.publish/confirm   → 放行，执行发布
    <run>/.publish/abort     → 中止，不发布
  结果存疑（未捕获强信号）时等待：
    <run>/.publish/mark_published / mark_failed
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:
    sys.exit("缺少依赖 playwright。请执行：python -m pip install playwright\n（浏览器复用本机 Chrome/Edge，无需 playwright install chromium）")

CREATOR_HOME = "https://creator.xiaohongshu.com/"
PUBLISH_URL = "https://creator.xiaohongshu.com/publish/publish?from=menu&target=image"

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


def launch_persistent_context(p, profile_dir: Path):
    """用独立用户数据目录启动本机 Chrome/Edge（持久化上下文）。
    登录态天然保存在 profile_dir 中，下次启动直接复用，无需再扫码。
    优先 channel，失败再用显式路径兜底。返回 context（自带浏览器）。"""
    profile_dir.mkdir(parents=True, exist_ok=True)
    common = dict(headless=False, locale="zh-CN",
                  viewport={"width": 1440, "height": 900})
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

LOGIN_WAIT_SECONDS = 480      # 人工扫码登录最多等 8 分钟
CONFIRM_WAIT_SECONDS = 900    # 人工确认闸口最多等 15 分钟
UPLOAD_WAIT_SECONDS = 90      # 图片上传完成最多等 90 秒
RESULT_WAIT_SECONDS = 25      # 点击发布后强成功信号观察窗口
POLL_SECONDS = 2

CN_TZ = timezone(timedelta(hours=8))

# 多候选选择器（平台页面结构可能调整，按顺序尝试，每步均截图留证）
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


def now_cn_iso() -> str:
    return datetime.now(CN_TZ).isoformat(timespec="seconds")


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_publish_data(run_dir: Path) -> dict:
    p = run_dir / "publish_data.json"
    if not p.exists():
        sys.exit(f"找不到 {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    images = data.get("images") or []
    if len(images) != 4:
        sys.exit(f"publish_data.json 中 images 数量为 {len(images)}，预期 4 张，终止。")
    for img in images:
        if not Path(img["path"]).exists():
            sys.exit(f"图片不存在：{img['path']}")
    if not (data.get("title") and data.get("content")):
        sys.exit("title 或 content 为空，终止。")
    return data


def shot(page, work_dir: Path, name: str) -> str:
    work_dir.mkdir(parents=True, exist_ok=True)
    p = work_dir / f"{name}.png"
    try:
        page.screenshot(path=str(p), full_page=False)
    except Exception as e:
        return f"截图失败: {e}"
    return str(p)


def _login_cookie_ok(context) -> bool:
    """cookie 层面的登录信号：web_session 或任意含 session/token 的非空 cookie。"""
    for c in context.cookies():
        n = c.get("name", "").lower()
        if not c.get("value"):
            continue
        if "web_session" in n or n == "web_session" or ("session" in n and "xs" in n) or n in ("a1", "webId"):
            return True
    return False


def is_logged_in(page, context) -> bool:
    """登录成功判据（多信号）：离开 /login 且（页面出现登录后特征 或 命中登录 cookie）。"""
    try:
        url = page.url
    except Exception:
        return False
    if "/login" in url or url.startswith("about:"):
        return False
    if _login_cookie_ok(context):
        return True
    for text in ("发布笔记", "笔记管理", "发布图文笔记"):
        try:
            if page.get_by_text(text, exact=False).first.is_visible():
                return True
        except Exception:
            pass
    return False


def find_logged_in_page(context):
    """在【所有标签页】中寻找已登录页面（扫码后平台可能在新标签打开创作中心）。"""
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


def wait_manual_login(context, work_dir: Path):
    """打开创作中心，轮询所有标签页等待人工登录；返回已登录的 page。"""
    page = context.pages[0] if context.pages else context.new_page()
    print("[登录] 正在打开小红书创作服务平台……", flush=True)
    page.goto(CREATOR_HOME, wait_until="commit", timeout=60000)
    deadline = time.time() + LOGIN_WAIT_SECONDS
    print(
        f"[登录] 请在弹出的浏览器中【人工扫码登录】（最多等待 {LOGIN_WAIT_SECONDS // 60} 分钟）。"
        "脚本不会接触账号密码；登录成功（无论在当前页还是新开标签页）后会自动接管。",
        flush=True,
    )
    last_debug = 0.0
    while time.time() < deadline:
        logged = find_logged_in_page(context)
        if logged is not None:
            shot(logged, work_dir, "01_logged_in")
            print(f"[登录] 检测到登录成功，登录态已持久化到本地配置目录。", flush=True)
            return logged
        now = time.time()
        if now - last_debug >= 10:
            print("[登录·等待中] " + debug_pages(context), flush=True)
            last_debug = now
        time.sleep(POLL_SECONDS)
    shot(context.pages[0] if context.pages else page, work_dir, "01_login_timeout")
    sys.exit("[登录] 等待登录超时。已保留现场，请重跑（登录态未保存）。")


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
    sys.exit("[人工闸口] 等待确认超时，终止（未做任何发布动作）。")


def fill_field(page, selectors: list[str], text: str, label: str, work_dir: Path, shot_name: str) -> str:
    """在多候选选择器中找到可见输入区并填入文本；返回实际命中的选择器。"""
    last_err = None
    for sel in selectors:
        loc = page.locator(sel).first
        try:
            loc.wait_for(state="visible", timeout=6000)
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
            page.wait_for_timeout(400)
            actual = ""
            try:
                if tag in ("input", "textarea"):
                    actual = loc.input_value()
                else:
                    actual = loc.inner_text()
            except Exception:
                pass
            compact = "".join(actual.split())
            if compact and "".join(text.split())[:10] in compact:
                shot(page, work_dir, shot_name)
                print(f"[填写] {label} 完成（命中选择器 {sel}，实际字符数 {len(compact)}）", flush=True)
                return sel
            last_err = RuntimeError(f"填入后回读不匹配，回读前10字：{compact[:10]!r}")
        except Exception as e:
            last_err = e
    shot(page, work_dir, shot_name + "_FAILED")
    raise RuntimeError(f"{label} 填写失败：{last_err}")


def dump_buttons(page, work_dir: Path) -> None:
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


def find_publish_button(page):
    """找可见、可用、文本恰为「发布」的主按钮（多个时取最后一个，即底部主操作）。"""
    candidates = page.locator(
        'button.publishBtn, .publishBtn, button[data-v-"发布"], [class*="publish"] button, '
        'button:has-text("发布"), [role="button"]:has-text("发布")'
    )
    n = candidates.count()
    matches = []
    for i in range(n):
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
    """点击发布后若出现二次确认弹窗，在弹窗内点「发布/确定」。返回是否处理了弹窗。"""
    page.wait_for_timeout(1200)
    dialog = page.locator(
        '.el-dialog__wrapper:visible, .el-dialog:visible, .modal-container:visible, '
        '[role="dialog"]:visible, [class*="dialog"]:visible, [class*="confirm"]:visible'
    ).first
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
    return False


def observe_result(page, work_dir: Path) -> dict:
    """强成功信号观察窗口：只在有明确证据时判成功；失败文本判失败；否则 unknown 保留现场。"""
    deadline = time.time() + RESULT_WAIT_SECONDS
    while time.time() < deadline:
        url = page.url
        success_url = ("/publish/publish" not in url) and ("/manage" in url or "/success" in url)
        toast_success = False
        toast_fail = False
        try:
            toast_success = page.get_by_text("发布成功").first.is_visible()
        except Exception:
            pass
        try:
            toast_fail = page.get_by_text("发布失败").first.is_visible()
        except Exception:
            pass
        if success_url or toast_success:
            shot(page, work_dir, "07_published")
            return {"verdict": "published", "final_url": url,
                    "signal": "url_changed" if success_url else "toast_text"}
        if toast_fail:
            shot(page, work_dir, "07_publish_failed")
            return {"verdict": "failed", "final_url": url, "signal": "failure_toast"}
        time.sleep(1)
    shot(page, work_dir, "07_result_unknown")
    return {"verdict": "unknown", "final_url": page.url,
            "signal": "no_strong_signal_within_25s"}


def cmd_login(run_dir: Path) -> None:
    work_dir = run_dir / ".publish"
    profile_dir = work_dir / "browser-profile"
    with sync_playwright() as p:
        context = launch_persistent_context(p, profile_dir)
        page = wait_manual_login(context, work_dir)
        print("[登录] 完成，3 秒后关闭浏览器（登录态已保存，下次无需再扫码）。", flush=True)
        page.wait_for_timeout(3000)
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

    title = data["title"]
    content = data["content"]
    image_paths = [img["path"] for img in data["images"]]
    print(f"[启动] run={run_dir.name}  标题={title!r}  图片={len(image_paths)} 张", flush=True)

    with sync_playwright() as p:
        context = launch_persistent_context(p, profile_dir)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(PUBLISH_URL, wait_until="commit", timeout=60000)

        # 1) 未登录 → 在本浏览器等待人工扫码；登录页可能在新标签完成，统一接管已登录标签
        logged = find_logged_in_page(context)
        if logged is None:
            page = wait_manual_login(context, work_dir)
        else:
            page = logged
        try:
            page.bring_to_front()
        except Exception:
            pass
        page.goto(PUBLISH_URL, wait_until="commit", timeout=60000)

        print("[发布页] 已进入发布图文页，等待上传控件……", flush=True)
        try:
            page.locator('input[type="file"]').first.wait_for(state="attached", timeout=30000)
        except PWTimeout:
            shot(page, work_dir, "02_no_file_input")
            sys.exit("[发布页] 未找到图片上传控件（可能未落在图文发布页）。已截图，终止。")
        shot(page, work_dir, "02_publish_page_ready")

        # 2) 上传 4 张图（优先 accept 含 image 的 file input）
        file_inputs = page.locator('input[type="file"]')
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
        thumb_ok = False
        while time.time() < deadline:
            blob_imgs = page.locator('img[src^="blob:"]').count()
            if blob_imgs >= 4:
                thumb_ok = True
                break
            time.sleep(2)
        page.wait_for_timeout(5000)  # 固定余量，等待服务端处理完成
        shot(page, work_dir, "03_after_upload")
        if not thumb_ok:
            print("[上传] 警告：未稳定观测到 4 个 blob 缩略图，请在人工确认时重点核对。", flush=True)
        else:
            print("[上传] 观测到 >=4 个图片预览。", flush=True)

        # 3) 填写标题与正文
        dump_buttons(page, work_dir)
        title_sel = fill_field(page, TITLE_SELECTORS, title, "标题", work_dir, "04_title")
        body_sel = fill_field(page, BODY_SELECTORS, content, "正文", work_dir, "05_body")
        shot(page, work_dir, "06_filled")

        # 4) 人工确认闸口
        ok = wait_for_signal(
            work_dir, "confirm", "abort", CONFIRM_WAIT_SECONDS,
            {
                "message": "图片/标题/正文已自动填充。请在浏览器中目检，确认无误后放行发布。",
                "at": now_cn_iso(),
                "title": title,
                "images_in_order": [Path(x).name for x in image_paths],
                "title_selector": title_sel,
                "body_selector": body_sel,
                "screenshot": str(work_dir / "06_filled.png"),
            },
        )
        if not ok:
            shot(page, work_dir, "08_aborted")
            write_json(run_dir / "publish_result.json",
                       {"status": "aborted", "at": now_cn_iso(), "reason": "manual_abort_before_publish"})
            context.close()
            return

        # 5) 点击发布（+ 可能的二次确认弹窗）
        btn = find_publish_button(page)
        if btn is None:
            shot(page, work_dir, "07_no_publish_button")
            write_json(run_dir / "publish_result.json",
                       {"status": "failed", "at": now_cn_iso(), "reason": "publish_button_not_found",
                        "screenshot": str(work_dir / "07_no_publish_button.png")})
            sys.exit("[发布] 未找到可点击的「发布」按钮，已保留现场，终止。")
        btn.scroll_into_view_if_needed()
        btn.click()
        print("[发布] 已点击「发布」按钮。", flush=True)
        click_second_confirm_if_any(page)

        # 6) 强成功信号判定
        result = observe_result(page, work_dir)
        verdict = result["verdict"]

        if verdict == "unknown":
            # 不武断下结论：保留浏览器，等待人工目检后给信号
            ok2 = wait_for_signal(
                work_dir, "mark_published", "mark_failed", CONFIRM_WAIT_SECONDS,
                {"message": "25 秒内未捕获到强成功信号。请目检浏览器：确认已发布则放行标记，否则标记失败。",
                 "at": now_cn_iso(), "final_url": result["final_url"],
                 "screenshot": str(work_dir / "07_result_unknown.png")},
            )
            verdict = "published" if ok2 else "failed"
            result["signal"] = "manual_verdict_after_unknown"

        if verdict == "published":
            published_at = now_cn_iso()
            final_url = page.url
            # 回写 publish_data.json（只追加/改状态字段，保留原始内容）
            data["status"] = "published"
            data["published_at"] = published_at
            data["publish_result"] = {"platform": "xiaohongshu_creator", "final_url": final_url,
                                      "signal": result.get("signal")}
            write_json(run_dir / "publish_data.json", data)
            write_json(run_dir / "publish_result.json", {
                "status": "published", "published_at": published_at, "run": run_dir.name,
                "platform": "xiaohongshu_creator", "final_url": final_url,
                "title": title, "images_count": 4,
                "signal": result.get("signal"),
                "screenshot": str(work_dir / "07_published.png"),
            })
            print("[结果] 发布成功（强信号：%s）。" % result.get("signal"), flush=True)
            print(f"[结果] publish_data.json 已更新 status=published；结果页 URL：{final_url}", flush=True)
            page.wait_for_timeout(3000)
        else:
            write_json(run_dir / "publish_result.json", {
                "status": "failed", "at": now_cn_iso(), "run": run_dir.name,
                "final_url": result.get("final_url"), "signal": result.get("signal"),
                "screenshot": str(work_dir / "07_publish_failed.png"),
            })
            print("[结果] 判定发布失败/未证实。现场已截图，请人工核查，浏览器保留 30 秒。", flush=True)
            page.wait_for_timeout(30000)

        context.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="小红书最小浏览器发布闭环")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("login", "publish"):
        s = sub.add_parser(name)
        s.add_argument("--run", default="output/run-004", help="run 目录（默认 output/run-004）")
    args = ap.parse_args()
    run_dir = Path(args.run).resolve()
    if not run_dir.is_dir():
        sys.exit(f"run 目录不存在：{run_dir}")
    if args.cmd == "login":
        cmd_login(run_dir)
    else:
        cmd_publish(run_dir)


if __name__ == "__main__":
    main()
