# new-api 对接指南

本仓库提供一个 **OpenAI 兼容**的 pollinations 中转服务。

但在对接前，请先看下面这条——**new-api 里已经有一个更强的原生渠道**。

---

## 零、优先方案：new-api 原生 Imagerator 渠道（type 66）

> 结论：**如果你要无水印、1024×1024 出图，直接用原生渠道 `Imagerator`（渠道类型 66），不要用本仓库的中转。**

### 为什么

本仓库逆向的 APK 是 `com.ai.artgenerator.imagegenerator`，它的生图通道是 pollinations（带水印、20s/IP 限流）。

而 new-api 里已有一个 `relay/channel/imagerator` 渠道，逆向自**同厂商另一个 App**
`com.techinfortainment.imagerator`，走的是完全不同的上游 `techinfortainment.com/ai-generation/`。

两条链路实测对比：

| | pollinations（本仓库中转） | **原生 ai-generation（渠道 66）** |
|---|---|---|
| 水印 | ❌ 服务端强制烙入 | ✅ **无** |
| 分辨率 | 768 / 1024（JPEG） | ✅ **1024×1024 PNG**（1.99 MB 实测） |
| 鉴权 | 无（匿名） | `device_id`（32 hex，可伪造，无签名无加密） |
| 额度 | 约 1 次 / 20s / IP | ✅ **20 credits / 新设备**，无按 IP 限速 |
| 注册 | 无需 | `POST /ai-generation/users/register` 无任何验证 |
| 号池 | — | new-api 已内置自动注册与余额同步（`pool.go`） |

### 实测记录（2026-10-28，本仓库作者验证）

```bash
# 1. 注册新设备（任意 32 位 hex）
POST https://techinfortainment.com/ai-generation/users/register
{"device_id":"<32hex>","app_name":"imagerator"}
→ {"credits":20,"plan":"Ads","type":"Organic","blocked":false}

# 2. 提交生成
POST https://techinfortainment.com/ai-generation/generate/text2image
{"prompt":"a cozy wooden cabin in a snowy pine forest at dusk",
 "original_prompt":"<同上>","model":"Flux1schnell","width":768,"height":1024,
 "steps":4,"guidance":2.5,"negative_prompt":"","device_id":"<32hex>",
 "user_type":"Organic","version":"3","app_name":"imagerator"}
→ {"request_id":"749395ce-..."}

# 3. 轮询（约 12s 完成）
GET https://techinfortainment.com/ai-generation/result?request_id=<id>&app_name=imagerator
→ {"status":"completed","image_url":"https://techinfortainment.com/media/imagerator/Flux/safe/<uuid>.png",
   "credits_remaining":18}
```

实测结果：**1024×1024 PNG、1.99 MB、无水印**。证据见
[`real_tests/upstream_native/native_t2i.jpg`](../real_tests/upstream_native/native_t2i.jpg)。

### 如何在 new-api 里启用

| 字段 | 值 |
|---|---|
| 类型 | `Imagerator`（渠道类型 **66**） |
| 名称 | 随意 |
| 基础 URL | 留空（默认 `https://techinfortainment.com`）或显式填 |
| 密钥 | 留空（device_id 由内置号池自动注册） |
| 模型 | `imagerator-turbo` / `imagerator-flux` / `imagerator-nanobanana` / `imagerator-i2i` |

模型映射（`relay/channel/imagerator/adaptor.go`）：

| 渠道模型名 | 上游 model |
|---|---|
| `imagerator-turbo` | `ZImageTurbo_INT8` |
| `imagerator-flux` | `Flux1schnell` |
| `imagerator-nanobanana` | `flux`（上游 NanoBanana 已下移，适配器回落到 flux） |
| `imagerator-i2i` | `Flux_2_Klein_4B_BF16` |

该渠道同时支持 chat 协议（返回 markdown 图片链接）与 images 协议（返回 OpenAI ImageResponse）。

> ⚠️ 注意：`imagerator` 渠道对应的是**另一个 App**的上游，与本仓库逆向的
> `com.ai.artgenerator.imagegenerator` 不是同一条链路。若你手上只有后者这个 APK，
> 它唯一能纯协议复现的就是 pollinations（即本仓库内容）。

### 一个已知现象

新注册设备首次请求偶发返回 `{"status":"blocked","message":"Content not allowed"}`
（实测同 prompt 换用已有设备即正常）。号池遇到 blocked 建议换设备重试，不要直接判死。

---

## 以下为本仓库中转服务的对接说明

本项目提供 **OpenAI 兼容**图像生成接口，可接入 new-api 的 OpenAI 类型渠道。

服务地址示例：`http://127.0.0.1:8931`

> 本文结论均对照 `new-api` 源码核实（`relay/channel/openai/adaptor.go` 的 `GetRequestURL`、
> `relay/common/relay_utils.go` 的 `GetFullRequestURL`、`relaykit/dto/openai_image.go` 的 `ImageRequest`），
> 不是猜测。

---

## 一、渠道配置（本仓库中转方案）

new-api 后台 → **渠道** → **添加渠道**

| 字段 | 值 |
|---|---|
| 类型 | `OpenAI` |
| 名称 | `AI-ImageRator-2API` |
| 分组 | 按需（如 `default`） |
| 模型 | 见「二、模型填写」 |
| **自定义接口地址** | `http://127.0.0.1:8931` |
| 密钥 | 任意非空（如 `sk-imageRator`）—— 本服务不校验密钥 |
| 代理 / 代理地址 | 留空（除非你要给每个渠道配独立出口 IP） |

### ⚠️ 地址不要带 `/v1`

new-api 对 OpenAI 渠道的 URL 拼接是：

```go
// relay/channel/openai/adaptor.go → GetRequestURL，default 分支
return relaycommon.GetFullRequestURL(info.ChannelBaseUrl, info.RequestURLPath, info.ChannelType)

// relay/common/relay_utils.go
fullRequestURL := fmt.Sprintf("%s%s", baseURL, requestURL)
```

`RequestURLPath` 就是客户端请求的原始路径 `/v1/images/generations`。

所以：

| 你填的接口地址 | new-api 实际请求 | 结果 |
|---|---|---|
| `http://127.0.0.1:8931` | `http://127.0.0.1:8931/v1/images/generations` | ✅ 正确 |
| `http://127.0.0.1:8931/v1` | `http://127.0.0.1:8931/v1/v1/images/generations` | ❌ 404 |

---

## 二、模型填写

「模型」输入框逐行或逗号分隔：

```
flux
turbo
sana
zimage
flux-realism
dall-e-3
dall-e-2
```

OpenAI 别名可直接用（`dall-e-3` → `flux`，`dall-e-2` → `turbo`），方便已有客户端不改代码。

| 模型 | 上游 | 状态 |
|---|---|---|
| `flux` / `flux-schnell` / `flux1schnell` / `dall-e-3` | `flux` | ✅ |
| `turbo` / `dall-e-2` | `turbo` | ✅ |
| `sana` | `sana` | ✅ |
| `zimage` / `z-image` / `zimage-turbo` | `zimage` | ✅ |
| `flux-realism` | `flux-realism` | ✅ |
| `kontext` | `kontext` | ⚠️ 403（需 `image` 参数，纯文生图不支持） |

---

## 三、验证

渠道保存后**不要用「测试」按钮**——该按钮发的是 `/v1/chat/completions`，本服务没有聊天端点，必然报错，属正常现象。

用真实生图请求验证：

```bash
curl -X POST http://<new-api>:3000/v1/images/generations \
  -H 'Authorization: Bearer sk-<你的 new-api 令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"model":"flux","prompt":"a golden retriever puppy on green grass","n":1,"size":"1024x1024"}'
```

预期响应（约 5–30 秒，受串行闸影响）：

```json
{
  "created": 1793181900,
  "data": [{
    "b64_json": "/9j/4AAQSkZJRg...",
    "url": "http://127.0.0.1:8931/outputs/a1b2c3d4e5f6a7b8.jpg",
    "revised_prompt": "a golden retriever puppy on green grass",
    "_meta": {
      "model": "flux",
      "seed": 1234567,
      "attempts": 1,
      "watermark_removed": false
    }
  }],
  "elapsed": 5.7
}
```

**拿到 `data[0].b64_json` 即说明全链路通。**

> `_meta` 是本服务的附加字段，new-api 透传时通常忽略；不影响 OpenAI 兼容性。

---

## 四、水印处理（重要）

出图右下角的 pollinations.ai 水印是**上游服务端烙进 JPEG 的**，`nologo` 参数已被服务端忽略
（EXIF 元数据回显 `"nologo":true` 但水印依旧），参数侧无法去除。

要交付无水印图，**在请求里传 `watermark: false`**：

```bash
curl -X POST http://<new-api>:3000/v1/images/generations \
  -H 'Authorization: Bearer sk-<令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"model":"sana","prompt":"a cat","n":1,"size":"1024x1024","watermark":false}'
```

### 为什么用 `watermark` 而不是 `remove_watermark`

对照 `relaykit/dto/openai_image.go`：

- `Watermark *bool \`json:"watermark,omitempty"\`` —— **已定义字段，会正常转发到上游**
- 未知字段被收进 `Extra`，但 `MarshalJSON` 里合并逻辑**被刻意注释掉**
  （源码注释：`// 不能合并ExtraFields！！！！！！！！`）

所以经 new-api 时：

| 字段 | 是否透传到本服务 |
|---|---|
| `watermark: false` | ✅ 透传（触发去水印） |
| `remove_watermark: true` | ❌ 被 new-api 丢弃 |

> 直连本服务（不经过 new-api）时两种写法都支持。

### 备选：服务端全局默认去水印

不想改请求体，可让服务默认去水印：

```bash
REMOVE_WATERMARK=1 WM_METHOD=auto python demo_server.py
```

之后 new-api 侧无需任何改动。

### 质量说明

| 方法 | 依赖 | 效果 |
|---|---|---|
| `cv2`（inpaint） | `opencv-python-headless` | 纯色/虚化背景几乎无痕；高频纹理（木纹/毛发）有轻微涂抹 |
| `pillow`（clone） | 无 | 保留纹理但可能有轻微水平接缝 |

去水印属对成品的二次修改，对保真度敏感的场景建议保留原图。

---

## 五、计费建议

new-api 侧建议按 **图片张数** 计费，不要按 token。

| 尺寸 | 建议倍率（相对 gpt-4o） |
|---|---|
| 512×512 | 1× |
| 768×768 | 2× |
| 1024×1024 | 3× |
| 1344×768 / 768×1344 | 3× |

原因：上游单张 5–30 秒，成本主要来自**串行等待**而非算力。

---

## 六、并发与扩容

**单实例吞吐 ≈ 1 张 / 20 秒**（`MIN_INTERVAL=20` 串行闸）。

```
总吞吐（张/秒） ≈ 实例数 × 可用出口 IP 数 ÷ 20
```

要点：

1. 每个实例必须配**独立出口 IP**（new-api 渠道的「代理」字段），同 IP 多实例无效
2. **不要**调小 `MIN_INTERVAL`，只会更早触发 `503`/`402`
3. 服务已内置 `503 Retry-After` 与 `402` 指数退避（`MAX_RETRIES` 默认 5），外层无需再包重试
4. 客户端超时紧张时用异步端点 `POST /v1/images/async` + 轮询

---

## 七、故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| 404 `not found` | 接口地址多写了 `/v1` | 改为 `http://127.0.0.1:8931` |
| 渠道「测试」失败 | 本服务无 chat 端点 | 正常，用生图请求验证 |
| `502` + `HTTP 503` | 匿名限流（连发） | 等 45–60s；调大 `MIN_INTERVAL` |
| `502` + `HTTP 402` | 该 IP 额度耗尽 | 换出口 IP，或调大 `MAX_RETRIES` |
| 连续多次 `502` | IP 进入长冷却（可达数十分钟） | 只能换 IP |
| `upstream 403 (model ... unsupported)` | 模型不支持纯文生图 | 改用 `flux`/`turbo`/`sana`/`zimage` |
| `400 prompt is required` | prompt 为空 | 检查请求体 |
| `400 size out of range` | 边长超 128–1536 | 调整尺寸 |
| `400 n must be 1..4` | n 越界 | 本服务上限 4（new-api 层是 128） |
| 图片带水印 | 水印由上游强制烙入 | 传 `watermark: false` |
| 响应 >20s | 串行闸排队 | 正常；用异步端点 |

---

## 八、健康检查与监控

```bash
curl http://127.0.0.1:8931/health
```

```json
{
  "status": "ok",
  "ts": 1793188333,
  "watermark": {
    "default_remove": false,
    "method": "off",
    "capabilities": { "pillow": true, "opencv": true, "default": "auto" }
  }
}
```

| 端点 | 用途 |
|---|---|
| `GET /health` | 存活 + 水印能力探测 |
| `GET /stats` | `requests` / `success` / `failed` / `bytes` |

监控建议：`stats.failed / stats.requests > 20%` 说明限流严重，需扩 IP。

---

## 九、备选接入方式

### 方案 B：自定义渠道（Custom）

`GetRequestURL` 的 `ChannelTypeCustom` 分支是**原样返回** `ChannelBaseUrl`（仅替换 `{model}`）：

```go
case constant.ChannelTypeCustom:
    url := info.ChannelBaseUrl
    url = strings.Replace(url, "{model}", info.UpstreamModelName, -1)
    return url, nil
```

因此自定义渠道必须填**完整路径**：

| 字段 | 值 |
|---|---|
| 类型 | 自定义渠道 |
| 基础 URL | `http://127.0.0.1:8931/v1/images/generations` |

不推荐——这样只能用于生图一个端点。

### 方案 C：Nginx 归一化（路径总对不上时）

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
}
```

（本服务设 `PORT=8932`，new-api 指向 `http://<nginx>:8931`）

---

## 十、对接检查清单

- [ ] 服务已启动：`curl http://127.0.0.1:8931/health` 返回 `"status":"ok"`
- [ ] 渠道类型 = `OpenAI`
- [ ] 自定义接口地址 = `http://127.0.0.1:8931`（**无** `/v1` 后缀）
- [ ] 密钥填了任意非空值
- [ ] 模型列表已填（至少 `flux`）
- [ ] 用生图 curl 打通，拿到 `data[0].b64_json`
- [ ] 如需无水印：确认请求带 `watermark: false`，或服务以 `REMOVE_WATERMARK=1` 启动
- [ ] 查看 `GET /stats`，`failed` 占比正常

---

## 十一、最小配置速查

```yaml
类型:         OpenAI
名称:         AI-ImageRator-2API
自定义接口:   http://127.0.0.1:8931      # 不要带 /v1
密钥:         sk-imageRator              # 任意非空
模型:         flux,turbo,sana,zimage,flux-realism,dall-e-3,dall-e-2
去水印:       请求体 watermark:false（或服务端 REMOVE_WATERMARK=1）
```
