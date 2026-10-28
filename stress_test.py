#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI-ImageRator-APP-2api 压测

覆盖：
  - /health 并发吞吐
  - /v1/models, /stats
  - 错误路径（空 prompt / 非法 size / n 越界 / 未知路由 / 404 任务）
  - 真实生图 1 次（可选，--real）
"""

import argparse
import json
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8931"


def req(method, path, body=None, timeout=200):
    url = BASE + path
    data = None
    headers = {"Content-Type": "application/json", "User-Agent": "stress/1.0"}
    if body is not None:
        data = json.dumps(body).encode()
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    t0 = time.time()
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, raw, time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, e.read(), time.time() - t0


def bench_parallel(label, method, path, body, n, expect, timeout=200):
    codes, times = [], []
    lock = threading.Lock()

    def worker():
        code, _, el = req(method, path, body, timeout)
        with lock:
            codes.append(code)
            times.append(el)

    ts = [threading.Thread(target=worker) for _ in range(n)]
    t0 = time.time()
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    wall = time.time() - t0

    ok = sum(1 for c in codes if c == expect)
    med = statistics.median(times) * 1000 if times else 0
    p95 = sorted(times)[max(0, int(len(times) * 0.95) - 1)] * 1000 if times else 0
    passed = ok == n
    print("%-42s %s  %d/%d  median %.1fms  p95 %.1fms  wall %.2fs"
          % (label, "PASS" if passed else "FAIL", ok, n, med, p95, wall))
    return passed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--real", action="store_true", help="包含真实生图用例（慢，约 25s/张）")
    args = ap.parse_args()

    print("=" * 84)
    print("AI-ImageRator-APP-2api 压测  →  " + BASE)
    print("=" * 84)

    results = []

    # 1. 基础端点
    results.append(bench_parallel("health x20 并发", "GET", "/health", None, 20, 200))
    results.append(bench_parallel("v1/models x10 并发", "GET", "/v1/models", None, 10, 200))
    results.append(bench_parallel("stats x10 并发", "GET", "/stats", None, 10, 200))

    # 2. 错误路径
    results.append(bench_parallel("空 prompt → 400", "POST", "/v1/images/generations", {"prompt": ""}, 1, 400))
    results.append(bench_parallel("缺 prompt → 400", "POST", "/v1/images/generations", {}, 1, 400))
    results.append(bench_parallel("非法 size → 400", "POST", "/v1/images/generations",
                                  {"prompt": "x", "size": "abc"}, 1, 400))
    results.append(bench_parallel("size 越界 → 400", "POST", "/v1/images/generations",
                                  {"prompt": "x", "size": "9999x9999"}, 1, 400))
    results.append(bench_parallel("n=9 越界 → 400", "POST", "/v1/images/generations",
                                  {"prompt": "x", "n": 9}, 1, 400))
    results.append(bench_parallel("未知路由 → 404", "GET", "/nope", None, 1, 404))
    results.append(bench_parallel("未知任务 → 404", "GET", "/v1/images/async/deadbeef", None, 1, 404))

    # 3. 真实生图
    if args.real:
        print("-" * 84)
        code, raw, el = req("POST", "/v1/images/generations", {
            "prompt": "a red vintage sports car on a mountain road at sunset",
            "size": "768x768", "model": "flux", "n": 1,
        }, timeout=240)
        ok = code == 200
        detail = ""
        if ok:
            d = json.loads(raw)
            item = d["data"][0]
            detail = "b64 %d chars, model=%s, attempts=%d" % (
                len(item["b64_json"]), item["_meta"]["model"], item["_meta"]["attempts"])
        else:
            detail = raw[:120].decode("utf-8", "ignore")
        print("%-42s %s  %d  耗时 %.1fs  %s" % ("真实生图 768x768 flux", "PASS" if ok else "FAIL", code, el, detail))
        results.append(ok)

        # 异步任务
        code, raw, el = req("POST", "/v1/images/async", {
            "prompt": "a cozy cabin in a snowy forest", "size": "512x512", "model": "turbo",
        })
        created = code == 200
        tid = json.loads(raw)["id"] if created else None
        print("%-42s %s  %d" % ("异步任务创建", "PASS" if created else "FAIL", code))
        results.append(created)

        if tid:
            final = None
            for _ in range(30):
                time.sleep(5)
                c, raw2, _ = req("GET", "/v1/images/async/" + tid)
                st = json.loads(raw2).get("status")
                if st in ("succeeded", "failed"):
                    final = st
                    break
            ok = final == "succeeded"
            print("%-42s %s  最终状态=%s" % ("异步任务完成", "PASS" if ok else "FAIL", final))
            results.append(ok)

    print("=" * 84)
    print("总计: %d/%d PASS" % (sum(results), len(results)))
    print("=" * 84)
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
