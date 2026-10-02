# -*- coding: utf-8 -*-
"""gpt-image-2 生图服务（OpenAI 兼容的异步任务接口）。

经 2026-10-02 实测确认（APIMart 中转 aiuxu.com）：
1. POST {base}/images/generations -> {code:200, data:[{task_id}]}
2. 轮询 GET {base}/tasks/{task_id} -> submitted/processing -> completed/failed
3. completed -> result.images[0].url[0] 下载图片字节

透明背景（模型能力为 preview，中转已验证可透传）：
- background="transparent" + output_format="png"（webp 也可，jpeg 不支持 alpha）
- quality 必须为 "medium" 或 "high"
- prompt 必须显式要求 isolated subject / fully transparent background，
  否则 prompt 中描述的场景会盖过透明参数。

仅依赖标准库；Cloudflare 会拦截 python-urllib 默认 UA，故使用常规客户端 UA。
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

DEFAULT_BASE = "https://aiuxu.com/v1"
_UA = "python-requests/2.32.3"


class ImageServiceError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _http(method: str, url: str, api_key: str, body: dict | None = None,
          timeout: int = 60) -> tuple[int, bytes]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Accept-Encoding": "identity",
            "User-Agent": _UA,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _retry_status(status: int) -> bool:
    return status in (429, 500, 502, 503)


def generate_image(
    prompt: str,
    *,
    size: str = "1024x1024",
    quality: str = "auto",
    background: str | None = None,
    output_format: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    poll_interval: int = 3,
    poll_max: int = 60,
) -> dict:
    """提交 -> 轮询 -> 下载。

    成功返回 {"image_bytes": bytes, "task_id": str}。
    失败抛 ImageServiceError（带 .status）。
    """
    api_key = api_key or os.environ.get("APIMART_API_KEY")
    if not api_key:
        raise ImageServiceError(
            "缺少 APIMART_API_KEY：请在环境变量或仓库根 .env 中配置（参考 .env.example）"
        )
    base_url = base_url or os.environ.get("APIMART_BASE", DEFAULT_BASE)

    payload: dict = {
        "model": "gpt-image-2",
        "prompt": prompt,
        "size": size,
        "quality": quality,
        "n": 1,
    }
    if background:
        payload["background"] = background
    if output_format:
        payload["output_format"] = output_format

    # 提交（429/5xx 指数退避重试 3 次）
    status, raw = 200, b""
    task_id = None
    for attempt in range(4):
        status, raw = _http("POST", f"{base_url}/images/generations", api_key, payload)
        if status == 200:
            data = (json.loads(raw).get("data") or [{}])[0]
            task_id = data.get("task_id")
            if task_id:
                break
            raise ImageServiceError(f"上游未返回 task_id: {raw[:300]!r}", status)
        if _retry_status(status) and attempt < 3:
            time.sleep(min(2 ** attempt, 16))
            continue
        raise ImageServiceError(f"提交生图任务失败 HTTP {status}: {raw[:300]!r}", status)

    # 轮询
    time.sleep(8)
    for _ in range(poll_max):
        status, raw = _http("GET", f"{base_url}/tasks/{task_id}", api_key, timeout=30)
        if status != 200:
            time.sleep(poll_interval)
            continue
        d = (json.loads(raw).get("data")) or {}
        st = d.get("status")
        if st == "completed":
            images = (d.get("result") or {}).get("images") or []
            urls = images[0].get("url") if images else None
            if not urls:
                raise ImageServiceError("任务完成但无图片 URL", 502)
            dl_status, data = _http("GET", urls[0], api_key, timeout=120)
            if dl_status != 200:
                raise ImageServiceError(f"下载图片失败 HTTP {dl_status}", dl_status)
            return {"image_bytes": data, "task_id": task_id}
        if st == "failed":
            msg = d.get("error") or d.get("error_message") or "图片生成失败"
            raise ImageServiceError(str(msg), 500)
        time.sleep(poll_interval)

    raise ImageServiceError("生成超时（轮询上限）", 504)
