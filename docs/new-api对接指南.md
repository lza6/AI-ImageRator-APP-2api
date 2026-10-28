# new-api 对接指南

本项目提供 **OpenAI 兼容**接口，可通过 new-api 的「自定义渠道 / OpenAI 类型渠道」直接接入。

服务地址示例：`http://127.0.0.1:8931`

---

## 方案 A：OpenAI 类型渠道（推荐）

new-api 后台 → **渠道** → **添加渠道**

| 字段 | 值 |
|---|---|
| 类型 | `OpenAI` |
| 名称 | `AI-ImageRator-2API` |
| 分组 | 按需（如 `default`） |
| 模型 | 见下方「模型填写」 |
| 代理 | 留空 |
| 密钥 | 任意非空值（如 `sk-imageRator`）—— 本服务不校验密钥 |
| 代理地址 | 留空 |
| **自定义接口地址** | `http://127.0.0.1:8931` |

> ⚠️ new-api 的 OpenAI 渠道默认会请求 `/v1/chat/completions`。本服务**只提供图像端点**，因此：
> - 用于**图像生成**时，请确认 new-api 版本支持 `/v1/images/generations` 转发（当前版本支持）
> - 该渠道**不要**用于对话场景（会 404）

### 模型填写

在「模型」输入框中逐行或逗号分隔填入：

```
flux
turbo
sana
zimage
flux-realism
dall-e-3
dall-e-2
```

也可填写 OpenAI 别名（`dall-e-3` → `flux`，`dall-e-2` → `turbo`），便于已有客户端复用。

### 验证

渠道保存后点「测试」。因本服务无 `/v1/chat/completions`，测试可能报错，属正常现象 —— 请改用实际生图请求验证：

```bash
curl -X POST http://<new-api>:3000/v1/images/generations \
  -H 'Authorization: Bearer sk-<你的new-api令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"model":"flux","prompt":"a cat","n":1,"size":"1024x1024"}'
```

---

## 方案 B：自定义渠道 + 模型重定向

若 new-api 版本对 OpenAI 渠道的图像端点支持不完整，可用自定义渠道：

| 字段 | 值 |
|---|---|
| 类型 | `自定义渠道`（Custom） |
| 基础 URL | `http://127.0.0.1:8931/v1` |
| 模型重定向 | 按需 |

> 视 new-api 版本不同，自定义渠道的路径拼接规则可能是 `{base_url}/v1/xxx` 或 `{base_url}/xxx`。若出现 404，请把基础 URL 调整为 `http://127.0.0.1:8931` 或 `http://127.0.0.1:8931/v1` 后重试。

---

## 方案 C：反向代理前置（最稳）

若渠道配置路径拼接始终不匹配，用 Nginx 做一层归一化，确保 `/v1/*` 原样透传：

```nginx
server {
    listen 8931;

    location /v1/ {
        proxy_pass http://127.0.0.1:8932/v1/;
        proxy_set_header Host $host;
        proxy_read_timeout 300s;
    }

    location /outputs/ {
        proxy_pass http://127.0.0.1:8932/outputs/;
    }

    location / {
        proxy_pass http://127.0.0.1:8932/;
    }
}
```

（把本服务监听端口设为 `8932`，即 `PORT=8932`）

---

## 水印处理

出图右下角的 pollinations.ai 水印是**上游服务端烙进 JPEG 的**，`nologo` 参数已被服务端忽略（EXIF 元数据回显 `"nologo":true` 但水印依旧），参数侧无法去除。

要交付无水印图片，二选一：

### 方式一：服务端默认去水印

```bash
REMOVE_WATERMARK=1 WM_METHOD=auto python demo_server.py
pip install pillow opencv-python-headless   # 启用 cv2 高质量 inpaint
```

此后所有请求都自动去水印，new-api 侧无需改动。

### 方式二：按请求开启

请求体加 `remove_watermark: true`。若 new-api 的渠道配置不能透传自定义字段，用方式一更省事。

> ⚠️ 去水印属于对成品的二次修改：纯色/虚化背景几乎无痕，高频纹理区域可能有轻微涂抹。对保真度敏感的场景建议保留原图。

---

## 计费与配额建议

new-api 侧建议按 **图片张数** 计费，而不是按 token。

参考倍率（相对 gpt-4o 计费模型）：

| 尺寸 | 建议倍率 |
|---|---|
| 512×512 | 1× |
| 768×768 | 2× |
| 1024×1024 | 3× |
| 1344×768 / 768×1344 | 3× |

原因：上游单张耗时约 5–20 秒，且受 1 次/20 秒/IP 的额度限制，成本主要来自**串行等待时间**而非算力。

---

## 并发与扩容

**单实例上限 ≈ 1 张 / 20 秒**（`MIN_INTERVAL=20`）。

扩容公式：

```
总吞吐（张/秒） ≈ 实例数 × 可用出口 IP 数 ÷ 20
```

要点：

1. 每实例必须配独立出口 IP（new-api 渠道侧配代理）
2. **不要**调小 `MIN_INTERVAL` —— 只会把 `503`/`402` 提前
3. 服务已内置 `503 Retry-After` 与 `402` 的自动退避重试，通常无需外层再包重试
4. 长任务建议客户端用 `POST /v1/images/async` + 轮询，避免 HTTP 超时

---

## 故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| `502 upstream_error` + `HTTP 503` | 触发匿名限流（连发） | 等待 45–60s；调大 `MIN_INTERVAL` |
| `502` + `HTTP 402` | 额度耗尽（该 IP 已长时间高频） | 换出口 IP；或调大 `MAX_RETRIES` 走指数退避 |
| 连续多次 502 | 该 IP 进入长冷却（可数十分钟） | 只能换 IP，重试无意义 |
| `upstream 403 (model ... unsupported)` | 该模型不支持纯文生图（如 `kontext`） | 改用 `flux` / `turbo` / `sana` / `zimage` |
| `400 prompt is required` | prompt 为空 | 检查请求体 |
| `400 size out of range` | 边长超 128–1536 | 调整尺寸 |
| new-api 渠道测试失败 | 本服务无 chat 端点 | 正常，用生图请求验证 |
| 图片右下角有水印 | 服务端强制烙入，`nologo` 已失效 | 用 `REMOVE_WATERMARK=1` 或请求 `remove_watermark:true` |
| 响应很慢（>20s） | 串行闸等待 | 正常行为，用异步端点 |

---

## 健康检查与监控

| 端点 | 用途 |
|---|---|
| `GET /health` | 存活检查，返回 `{"status":"ok","ts":...}` |
| `GET /stats` | 累计 requests / success / failed / bytes |

建议监控 `stats.failed / stats.requests` 比值，超过 20% 说明限流严重，需扩 IP。

---

## 最小可用配置速查

```yaml
类型:        OpenAI
名称:        AI-ImageRator-2API
自定义接口:  http://127.0.0.1:8931
密钥:        sk-imageRator          # 任意非空
模型:        flux,turbo,sana,zimage,flux-realism,dall-e-3,dall-e-2
```

**验证命令**（走 new-api）：

```bash
curl -X POST http://<new-api>:3000/v1/images/generations \
  -H 'Authorization: Bearer sk-<new-api令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"model":"flux","prompt":"a red apple on a wooden table","n":1,"size":"1024x1024"}'
```

预期：约 5–20 秒返回，`data[0].b64_json` 有值。
