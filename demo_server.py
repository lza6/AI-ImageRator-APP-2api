#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI ImageRator 9.6 → 2API Demo Server

上游：image.pollinations.ai（ImageRator App 的免鉴权备用生图通道，纯协议还原）
协议来源：com.ai.artgenerator.imagegenerator v9.6 (classes2.dex → k6/g.a)

OpenAI 兼容端点：
  POST /v1/images/generations    同步生图（返回 b64_json 或 url）
  POST /v1/images/async          异步任务
  GET  /v1/images/async/{id}     任务查询
  GET  /v1/models                模型列表
  GET  /health                   健康检查
  GET  /stats                    统计
  GET  /                         内置 demo 页
"""

import base64
import hashlib
import json
import os
import threading
import time
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    import watermark as wm_mod
except Exception:
    wm_mod = None

PORT = int(os.environ.get("PORT", "8931"))
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", os.path.join(os.path.dirname(__file__), "outputs"))
os.makedirs(OUTPUT_DIR, exist_ok=True)

UPSTREAM = "https://image.pollinations.ai/prompt/"

# 水印处理默认策略：off（保真） | auto | cv2 | pillow
WM_METHOD = os.environ.get("WM_METHOD", "off")
WM_DEFAULT = os.environ.get("REMOVE_WATERMARK", "0") in ("1", "true", "yes")

# App 内 model 名 → pollinations model 参数
# App: i6.b.u='kontext', Flux1schnell / ZImageTurbo_INT8 / Turbo / flux (k6/g.a 内判定)
MODEL_MAP = {
    # OpenAI 常见别名
    "dall-e-3": "flux",
    "dall-e-2": "turbo",
    "flux": "flux",
    "flux-schnell": "flux",
    "flux1schnell": "flux",
    "flux1-schnell": "flux",
    "flux-realism": "flux-realism",
    "turbo": "turbo",
    "sana": "sana",
    "zimage": "zimage",
    "z-image": "zimage",
    "zimage-turbo": "zimage",
    "zimageturbo_int8": "zimage",
    "kontext": "kontext",
}

DEFAULT_MODEL = "flux"

# 匿名额度：约 1 次 / 20s / IP。全局串行闸 + 429/503/402 重试
RATE_LOCK = threading.Lock()
LAST_CALL = [0.0]
MIN_INTERVAL = float(os.environ.get("MIN_INTERVAL", "20"))
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "5"))

STATS = {"requests": 0, "success": 0, "failed": 0, "bytes": 0}
STATS_LOCK = threading.Lock()

TASKS = {}
TASKS_LOCK = threading.Lock()


def bump(key, n=1):
    with STATS_LOCK:
        STATS[key] = STATS.get(key, 0) + n


def build_url(prompt, width, height, model, seed, enhance=True, private=True):
    q = urllib.parse.quote(prompt, safe="")
    params = {
        "width": width,
        "height": height,
        "seed": seed,
        "model": model,
        "nologo": "true",
        "private": "true" if private else "false",
        "enhance": "true" if enhance else "false",
        "safe": "false",
    }
    return UPSTREAM + q + "?" + urllib.parse.urlencode(params)


def apply_watermark_policy(data, meta, remove_wm):
    """按策略处理水印，返回 (bytes, meta)"""
    if not remove_wm or wm_mod is None:
        meta["watermark_removed"] = False
        return data, meta
    out, info = wm_mod.remove(data, WM_METHOD if WM_METHOD != "off" else "auto")
    meta["watermark_removed"] = bool(info.get("removed"))
    meta["watermark_method"] = info.get("method") or info.get("reason")
    return out, meta


def generate(prompt, width=1024, height=1024, model="flux", seed=None, max_retries=None):
    """调用上游生图，返回 (jpeg_bytes, meta)。串行闸保证不触发限流。"""
    seed = seed if seed is not None else int(time.time() * 1000) % 2147483647
    m = MODEL_MAP.get(str(model).lower(), DEFAULT_MODEL)
    url = build_url(prompt, width, height, m, seed)
    attempts = max_retries or MAX_RETRIES

    last_err = None
    for attempt in range(attempts):
        # 全局串行闸
        with RATE_LOCK:
            wait = MIN_INTERVAL - (time.time() - LAST_CALL[0])
            if wait > 0:
                time.sleep(wait)
            LAST_CALL[0] = time.time()

        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "okhttp/4.12.0",
                "Accept": "image/jpeg",
            })
            with urllib.request.urlopen(req, timeout=180) as r:
                data = r.read()
            if len(data) < 2000 or data[:2] != b"\xff\xd8":
                raise RuntimeError("upstream returned non-JPEG (%d bytes)" % len(data))
            return data, {"model": m, "seed": seed, "url": url, "attempts": attempt + 1}
        except urllib.error.HTTPError as e:
            last_err = "HTTP %d" % e.code
            # 403 = 模型不支持该参数组合
            if e.code == 403:
                raise RuntimeError("upstream 403 (model '%s' unsupported for this request)" % m)
            # 503 = 瞬时限流；402 = 额度耗尽，需要更长冷却
            retry_after = int(e.headers.get("Retry-After", "10") or 10)
            base = max(retry_after, MIN_INTERVAL)
            penalty = base * (2 ** attempt) if e.code == 402 else base
            time.sleep(min(penalty, 120))
        except Exception as e:
            last_err = str(e)[:200]
            time.sleep(MIN_INTERVAL)

    raise RuntimeError("upstream failed after %d attempts: %s" % (attempts, last_err))


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass  # 静默，避免压测时刷屏

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _json_body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    # ---------------- GET ----------------
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path

        if path == "/health":
            return self._send(200, {
                "status": "ok",
                "ts": int(time.time()),
                "watermark": {
                    "default_remove": WM_DEFAULT,
                    "method": WM_METHOD,
                    "capabilities": wm_mod.capabilities() if wm_mod else None,
                },
            })

        if path == "/stats":
            with STATS_LOCK:
                return self._send(200, dict(STATS))

        if path == "/v1/models":
            return self._send(200, {
                "object": "list",
                "data": [
                    {"id": k, "object": "model", "owned_by": "pollinations", "upstream": v}
                    for k, v in sorted(MODEL_MAP.items())
                ],
            })

        if path.startswith("/v1/images/async/"):
            tid = path.rsplit("/", 1)[-1]
            with TASKS_LOCK:
                t = TASKS.get(tid)
            if not t:
                return self._send(404, {"error": {"message": "task not found", "code": "not_found"}})
            return self._send(200, t)

        if path.startswith("/outputs/"):
            fn = os.path.basename(path)
            fp = os.path.join(OUTPUT_DIR, fn)
            if os.path.isfile(fp):
                with open(fp, "rb") as f:
                    return self._send(200, f.read(), "image/jpeg")
            return self._send(404, {"error": {"message": "file not found"}})

        if path in ("/", "/index.html"):
            demo = os.path.join(os.path.dirname(__file__), "demo.html")
            if os.path.isfile(demo):
                with open(demo, encoding="utf-8") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8")
            return self._send(200, {"service": "AI-ImageRator-APP-2api", "port": PORT})

        return self._send(404, {"error": {"message": "not found", "code": "not_found"}})

    # ---------------- POST ----------------
    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        body = self._json_body()

        if path == "/v1/images/generations":
            return self._handle_generate(body)

        if path == "/v1/images/async":
            return self._handle_async_create(body)

        return self._send(404, {"error": {"message": "not found", "code": "not_found"}})

    def _validate(self, body):
        prompt = (body.get("prompt") or "").strip()
        if not prompt:
            return None, {"error": {"message": "prompt is required", "type": "invalid_request_error"}}
        if len(prompt) > 4000:
            return None, {"error": {"message": "prompt too long (max 4000)", "type": "invalid_request_error"}}

        try:
            n = int(body.get("n", 1))
        except Exception:
            return None, {"error": {"message": "n must be an integer", "type": "invalid_request_error"}}
        if n < 1 or n > 4:
            return None, {"error": {"message": "n must be 1..4", "type": "invalid_request_error"}}

        size = str(body.get("size", "1024x1024"))
        try:
            w, h = [int(x) for x in size.lower().split("x")]
        except Exception:
            return None, {"error": {"message": "size must be WxH", "type": "invalid_request_error"}}
        if not (128 <= w <= 1536 and 128 <= h <= 1536):
            return None, {"error": {"message": "size out of range (128..1536)", "type": "invalid_request_error"}}

        model = body.get("model") or DEFAULT_MODEL
        seed = body.get("seed")
        if seed is not None:
            try:
                seed = int(seed)
            except Exception:
                return None, {"error": {"message": "seed must be an integer", "type": "invalid_request_error"}}

        # 水印处理：默认取环境变量，请求可用 remove_watermark 覆盖
        rw = body.get("remove_watermark")
        if rw is None:
            remove_wm = WM_DEFAULT
        elif isinstance(rw, bool):
            remove_wm = rw
        else:
            remove_wm = str(rw).lower() in ("1", "true", "yes", "on")

        return {"prompt": prompt, "n": n, "w": w, "h": h, "model": model,
                "seed": seed, "remove_wm": remove_wm}, None

    def _handle_generate(self, body):
        args, err = self._validate(body)
        if err:
            return self._send(400, err)

        bump("requests")
        t0 = time.time()
        items = []
        try:
            for i in range(args["n"]):
                seed = args["seed"] + i if args["seed"] is not None else None
                data, meta = generate(args["prompt"], args["w"], args["h"], args["model"], seed)
                data, meta = apply_watermark_policy(data, meta, args["remove_wm"])
                fn = "%s.jpg" % hashlib.md5(data).hexdigest()[:16]
                with open(os.path.join(OUTPUT_DIR, fn), "wb") as f:
                    f.write(data)
                bump("success")
                bump("bytes", len(data))
                b64 = base64.b64encode(data).decode()
                items.append({
                    "b64_json": b64,
                    "url": "http://%s/outputs/%s" % (self.headers.get("Host", "127.0.0.1:%d" % PORT), fn),
                    "revised_prompt": args["prompt"],
                    "_meta": meta,
                })
        except Exception as e:
            bump("failed")
            return self._send(502, {"error": {"message": str(e), "type": "upstream_error"}})

        return self._send(200, {
            "created": int(t0),
            "data": items,
            "elapsed": round(time.time() - t0, 2),
        })

    def _handle_async_create(self, body):
        args, err = self._validate(body)
        if err:
            return self._send(400, err)

        tid = uuid.uuid4().hex
        with TASKS_LOCK:
            TASKS[tid] = {"id": tid, "status": "queued", "created": int(time.time())}

        def run():
            with TASKS_LOCK:
                TASKS[tid]["status"] = "running"
            try:
                data, meta = generate(args["prompt"], args["w"], args["h"], args["model"], args["seed"])
                data, meta = apply_watermark_policy(data, meta, args["remove_wm"])
                fn = "%s.jpg" % hashlib.md5(data).hexdigest()[:16]
                with open(os.path.join(OUTPUT_DIR, fn), "wb") as f:
                    f.write(data)
                with TASKS_LOCK:
                    TASKS[tid].update({
                        "status": "succeeded",
                        "finished": int(time.time()),
                        "b64_json": base64.b64encode(data).decode(),
                        "url_path": "/outputs/%s" % fn,
                        "_meta": meta,
                    })
                bump("success")
                bump("bytes", len(data))
            except Exception as e:
                with TASKS_LOCK:
                    TASKS[tid].update({"status": "failed", "error": str(e)[:300], "finished": int(time.time())})
                bump("failed")

        bump("requests")
        threading.Thread(target=run, daemon=True).start()
        return self._send(200, {"id": tid, "status": "queued"})


def main():
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    srv.daemon_threads = True
    print("AI-ImageRator-APP-2api demo server")
    print("  http://127.0.0.1:%d/            demo page" % PORT)
    print("  http://127.0.0.1:%d/health      health" % PORT)
    print("  http://127.0.0.1:%d/v1/models   models" % PORT)
    print("  POST /v1/images/generations     OpenAI compatible")
    print("  POST /v1/images/async           async task")
    print("  upstream: %s  (anon ~1 req/20s/IP)" % UPSTREAM)
    srv.serve_forever()


if __name__ == "__main__":
    main()
