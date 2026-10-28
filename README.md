# AI-ImageRator-APP-2api

> 逆向 **AI ImageRator 9.6**（`com.ai.artgenerator.imagegenerator`）的生图协议，封装为 OpenAI 兼容 API。

**纯协议 · 免鉴权 · 无需账号 · 开箱即用**

---

## 这是什么

AI ImageRator 是一个 Android AI 绘图 App，内置多条生图上游。本项目把其中**唯一免鉴权的通道**还原为可直接调用的 HTTP API：

```
GET https://image.pollinations.ai/prompt/{prompt}?width=&height=&seed=&model=&nologo=true&private=true&enhance=true&safe=false
```

并用 Python 标准库封装成 OpenAI `/v1/images/generations` 兼容服务。

详细逆向过程见 **[PROTOCOL.md](PROTOCOL.md)**。

---

## 快速开始

```bash
# 无第三方依赖，Python 3.9+
python demo_server.py
```

打开 http://127.0.0.1:8931/ 即为中文 demo 页面。

环境变量：

| 变量 | 默认 | 说明 |
|---|---|---|
| `PORT` | `8931` | 监听端口 |
| `MIN_INTERVAL` | `20` | 全局串行闸间隔（秒）。匿名额度约 1 次/20 秒/IP，**不要调小** |
| `OUTPUT_DIR` | `./outputs` | 图片落盘目录 |

---

## API

### `POST /v1/images/generations`

OpenAI 兼容同步生图。

```bash
curl -X POST http://127.0.0.1:8931/v1/images/generations \
  -H 'Content-Type: application/json' \
  -d '{
    "prompt": "a golden retriever puppy on green grass",
    "model": "flux",
    "size": "1024x1024",
    "n": 1
  }'
```

响应：

```json
{
  "created": 1793181900,
  "data": [{
    "b64_json": "/9j/4AAQ...",
    "url": "http://127.0.0.1:8931/outputs/a1b2c3d4e5f6.jpg",
    "revised_prompt": "a golden retriever puppy on green grass",
    "_meta": { "model": "flux", "seed": 1234567, "attempts": 1 }
  }],
  "elapsed": 5.7
}
```

参数：

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `prompt` | string | 必填 | 最长 4000 字符 |
| `model` | string | `flux` | 见下方模型表 |
| `size` | string | `1024x1024` | `WxH`，各边 128–1536 |
| `n` | int | `1` | 1–4（串行生成，约 20s/张） |
| `seed` | int | 随机 | 相同 seed + prompt 结果确定性 |

### `POST /v1/images/async` · `GET /v1/images/async/{id}`

异步任务，避免长连接超时。

```bash
curl -X POST http://127.0.0.1:8931/v1/images/async \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"a cozy cabin","size":"512x512","model":"turbo"}'
# → {"id":"a1b2...","status":"queued"}

curl http://127.0.0.1:8931/v1/images/async/a1b2...
# → {"id":"...","status":"succeeded","b64_json":"...","url_path":"/outputs/xxx.jpg"}
```

`status`：`queued` → `running` → `succeeded` / `failed`

### 其它

| 端点 | 说明 |
|---|---|
| `GET /health` | 健康检查 |
| `GET /stats` | 统计（requests / success / failed / bytes） |
| `GET /v1/models` | 模型列表（含 OpenAI 别名映射） |
| `GET /outputs/{file}` | 图片下载 |

---

## 模型

| 请求 `model` | 上游 | 实测 |
|---|---|---|
| `flux` / `flux-schnell` / `flux1schnell` / `dall-e-3` | `flux` | ✅ |
| `turbo` / `dall-e-2` | `turbo` | ✅ |
| `sana` | `sana` | ✅ |
| `zimage` / `z-image` / `zimage-turbo` / `zimageturbo_int8` | `zimage` | ✅ |
| `flux-realism` | `flux-realism` | ✅ |
| `kontext` | `kontext` | ⚠️ 403（需 `image=` 参数，纯文生图不支持） |

> 同一 `prompt` + `seed` 跨模型返回字节完全相同，说明免费层后端共享同一推理队列。模型名主要影响路由，不改变实际出图模型。

---

## 限流（重要）

匿名额度约 **1 次 / 20 秒 / IP**。

| 场景 | 上游返回 |
|---|---|
| 空闲后首次 | 200，2–6 秒 |
| 间隔 < 10s 连发 | `503` + `Retry-After: 10` |
| 持续施压 | `402 Payment Required` |
| 冷却 45–60 秒 | 恢复 200 |

服务内置**全局串行闸**（`MIN_INTERVAL`，默认 20s）+ 自动重试，单实例不会触发限流。

**扩容方式**：多实例 + 多出口 IP。同一 IP 起多个实例没有意义。

---

## 压测结果

```
health x20 并发            PASS  20/20  median 138.0ms  p95 530.5ms
v1/models x10 并发         PASS  10/10  median 1.9ms
stats x10 并发             PASS  10/10  median 1.4ms
空 prompt → 400            PASS
缺 prompt → 400            PASS
非法 size → 400            PASS
size 越界 → 400            PASS
n=9 越界 → 400             PASS
未知路由 → 404             PASS
未知任务 → 404             PASS
真实生图 768x768 flux      PASS  200  耗时 5.7s  b64 85608 chars
异步任务创建                PASS  200
异步任务完成                PASS  succeeded
────────────────────────────────────────────
总计: 13/13 PASS
```

真实出图证据见 [`real_tests/`](real_tests/)（`sana.jpg` / `flux-realism.jpg` / `turbo_768.jpg`，均为上游原始 JPEG）。

```bash
python stress_test.py          # 基础用例
python stress_test.py --real   # 含真实生图（约 30s）
```

---

## 已知限制

- **水印**：免费层 `nologo=true` 不生效，出图右下角固定带 `pollinations.ai` 水印
- **速度**：受匿名额度限制，约 20 秒/张，不适合高并发实时场景
- **deapi 通道未实现**：App 的另一条主通道 `api.deapi.ai` 需要 Bearer token，该 token 在 **native 层（DCC/libstub.so）** 注入，Java hook 与系统代理均无法捕获，需真机 Frida native hook — 详见 [PROTOCOL.md](PROTOCOL.md) 第 3 节

---

## new-api 对接

见 **[docs/new-api对接指南.md](docs/new-api对接指南.md)**。最小配置：

| 字段 | 值 |
|---|---|
| 类型 | `OpenAI` |
| 自定义接口地址 | `http://127.0.0.1:8931` |
| 密钥 | 任意非空（本服务不校验） |
| 模型 | `flux,turbo,sana,zimage,flux-realism,dall-e-3,dall-e-2` |

---

## 目录

```
demo_server.py          OpenAI 兼容服务（零依赖）
demo.html               中文 Web UI
stress_test.py          压测脚本
PROTOCOL.md             完整逆向报告
docs/
  new-api对接指南.md    new-api 渠道配置说明
analysis/
  DEX2C_UNPATCH.md      DCC 壳 patch 方法与局限
  frida/                Frida 抓包脚本（TLS bypass / SP+URL hook）
  apk/rc_imgerator.json ImageRator 的 Firebase Remote Config 全量响应
real_tests/             真实出图证据
outputs/                运行时生成的图片
```

---

## 法律

仅供协议研究与学习。上游服务条款、内容版权与合规责任由使用者自行承担。
