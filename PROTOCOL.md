# 逆向分析报告 · AI ImageRator 9.6

> 目标 APK：`AI ImageRator_ Teks ke Gambar_9.6_Premium.apk`
> 包名：`com.ai.artgenerator.imagegenerator`　版本：9.6 (versionCode 96)
> 开发者：TechInforTainment　安装包：36.9 MB
> 分析日期：2026-10-28

---

## 1. 样本概览

| 项 | 值 |
|---|---|
| 包名 | `com.ai.artgenerator.imagegenerator` |
| 版本 | 9.6 (96) |
| 入口 Activity | `com.tit.imagegenerator.presentation.boardingscreen.SplashActivity` |
| Application | `com.tit.imagegenerator.presentation.App` |
| 加固 | **np.dcc.protect（Dex2C + RollingHunters 壳）** |
| 技术栈 | Kotlin + Retrofit + OkHttp3 + Firebase + RxJava + Glide |
| 分发的 APK 变体 | `ElaMods` / `DSMods` / `RollingHunters` 等多层 mod 版 |

### 加固结构

- `lib/{arm64-v8a,armeabi-v7a}/libstub.so`（851 KB / 563 KB 起）为 DCC 壳核心
- 27 处 `<clinit>` 内调用 `Lnp/dcc/protect/EntryPoint;->stub(I)V` 做完整性校验
- 部分方法体被抽为 `public native`（例：`LA5/f;->k(LK3/q;)Ljava/lang/Object;`），实现落在 `libstub.so`
- dex 主体未加密，`baksmali` / `androguard` 可直接反编译

---

## 2. 上游通道总览

App 内共存在 3 条生图相关通道：

| # | 通道 | 鉴权 | 状态 | 可用性 |
|---|---|---|---|---|
| 1 | `api.deapi.ai/api/v1/client/*` | `Authorization: Bearer <token>` | token 由 Firebase Remote Config / native 层注入 | ❌ 纯协议不可得 |
| 2 | `image.pollinations.ai/prompt/{prompt}` | 无 | 免鉴权直连 | ✅ **真实出图已验证** |
| 3 | `enter.pollinations.ai/api/generate/image/` | 无 | 线上已 404 下线 | ❌ 已废弃 |

本仓库实现的是 **通道 2**（唯一纯协议可复现通道）。

---

## 3. 通道 1：api.deapi.ai（已被放弃，记录完整结构）

### 3.1 端点与请求体

来源：`classes2.dex → k6/n`（静态确认）

```java
// k6/n.c — 文生图
POST https://api.deapi.ai/api/v1/client/txt2img
Header: Authorization: Bearer {i6.b.p}
Header: Accept: application/json
Content-Type: application/json; charset=utf-8

{
  "model":  "Flux1schnell" | "ZImageTurbo_INT8" | ...,
  "prompt": "...",
  "steps":  4 | 10,        // ZImageTurbo_INT8 → 10，其余 → 4
  "width":  512,
  "height": 512,
  "seed":   <随机 int>
}
```

```java
// k6/n.d — 图生图（multipart）
POST https://api.deapi.ai/api/v1/client/img2img
Authorization: Bearer {i6.b.p}
multipart/form-data:
  model, prompt, steps="20", width, height, seed, image=<jpeg file>
```

```java
// k6/n.a — 轮询
GET https://api.deapi.ai/api/v1/client/request-status/{id}
Authorization: Bearer {i6.b.p}
Accept: application/json
```

另有 `img2video` / `txt2video` 端点（同为 `POST` + Bearer）。

### 3.2 实测响应

```bash
# 无 Authorization
POST /api/v1/client/txt2img → 401 {"message":"Unauthenticated.","code":"missing_key"}
# 任意 Authorization
POST /api/v1/client/txt2img → 401 {"message":"Unauthenticated.","code":"invalid_key"}
GET  /api/v1/client/txt2img → 405 Method Not Allowed（Symfony 错误页）
```

参数结构已完全确认（返回 `invalid_key` 而非 `invalid_payload`）。

### 3.3 为什么 token 拿不到

1. **静态空值**：`i6.b.p`（Bearer token 字段）在 `<clinit>` 中初始化为 `""`，全部 dex 中**没有任何运行时写入点**（`sput-object Li6/b;->p` 仅出现在 `<clinit>`）。
2. **Remote Config 不含此项**：完整 dump ImageRator 的 RC 响应（Firebase project `618549213407`，62 个 key），无任何生图 key。
3. **native 层承载**：Frida 全量 hook `okhttp3.Request$Builder.url/addHeader`、`java.net.URL.<init>`、`retrofit2.RequestFactory.create`、`com.android.volley.Request.getUrl`，**均未捕获到 deapi 请求**；同时系统代理（mitmproxy）也完全无记录 → 请求在 **native 层（DCC）直接 `syscall connect` 发出**，绕过 Java 网络栈与系统代理。
4. **凭证在 mod 层**：RC 中 `auth_pre_re_to` 为 448 hex 字符的 RSA blob，解密逻辑位于 mod/native 层。

结论：deapi 通道需要真机 + Frida native hook（`connect`/`SSL_write`）才能提取，属于下一轮工作，**不在本仓库范围内**。

---

## 4. 通道 2：image.pollinations.ai（本仓库实现）

### 4.1 客户端代码（原文还原）

来源：`classes2.dex → k6/g;->a`

```java
// 伪代码还原
String url = i6.b.D                       // base URL（运行时注入）
    + URLEncoder.encode(prompt, "UTF-8")
    + "?width="  + width
    + "&height=" + height
    + "&seed="   + seed
    + "&model="  + model
    + "&nologo=true&private=true&enhance=true&safe=false";

Request req = new Request.Builder().url(url).get().build();
k6.g.a.newCall(req).enqueue(...)
```

`i6.b.u`（默认模型）= `"kontext"`；`k6/g.a` 内判定 `flux` / `Turbo` / `ZImageTurbo_INT8` / `Flux1schnell` 等分支。

### 4.2 还原后的 URL 模板

```
GET https://image.pollinations.ai/prompt/{urlencoded_prompt}
    ?width=W
    &height=H
    &seed=S
    &model=M
    &nologo=true
    &private=true
    &enhance=true
    &safe=false
```

响应：`Content-Type: image/jpeg` 的二进制图片流（无 JSON 包封）。

### 4.3 模型映射

| App 内名称 | pollinations `model` | 实测 |
|---|---|---|
| `Flux1schnell` / `flux` | `flux` | ✅ 200 |
| `Turbo` | `turbo` | ✅ 200 |
| — | `sana` | ✅ 200 |
| `ZImageTurbo_INT8` | `zimage` | ✅ 200 |
| — | `flux-realism` | ✅ 200 |
| `kontext` | `kontext` | ⚠️ 403（需 `image=` 参数，纯文生图不支持） |

同一 `prompt` + `seed` 跨模型返回**完全相同的字节**（md5 一致），说明免费层后端模型实际共享同一推理队列。

### 4.4 限流特征（实测）

| 场景 | 表现 |
|---|---|
| 首次请求（空闲 IP） | 200，2–6s |
| 连续快速请求（间隔 < 10s） | `503 Service Unavailable` + `Retry-After: 10` |
| 持续施压 | `402 Payment Required` |
| 冷却 45–60s 后 | 恢复 200 |
| 匿名额度 | **约 1 次 / 20 秒 / IP** |

响应头摘录（503）：

```
HTTP/1.1 503
Retry-After: 10
access-control-allow-headers: Content-Type, X-PAYMENT, Payment-Signature
Server: cloudflare
```

`X-PAYMENT` / `Payment-Signature` 头说明 pollinations 已接入 x402 付费协议，付费可绕过限速——免费层无此凭证。

### 4.5 水印归因（已定论：服务端烙入）

App 请求本身带 `nologo=true`，但出图仍有水印。做了完整对照实验（同 prompt + 同 seed 777，768×768，model=flux）：

| 变体 | 请求参数 | 右下角白像素 | 左下角白像素 | 判定 |
|---|---|---|---|---|
| `nologo=true` | `&nologo=true` | 673 | 0 | 有水印 |
| `nologo=false` | `&nologo=false` | — | — | 有水印 |
| 不带 nologo | 无该参数 | 673 | 0 | 有水印 |
| `referrer=imageRator` | `&nologo=true&referrer=imageRator` | 673 | 0 | 有水印 |
| `referrer=pollinations` | 同上 | 673 | 0 | 有水印 |
| `token=free` | `&nologo=true&token=free` | 673 | 0 | 有水印 |
| `no_logo=true` | `&nologo=true&no_logo=true` | 673 | 0 | 有水印 |

**决定性证据**：JPEG 的 EXIF `UserComment`（tag 37510）回显了服务端解析后的请求元数据：

```json
{
  "prompt": "a red apple on a wooden table",
  "width": 768, "height": 768, "seed": 777,
  "model": "sana",
  "enhance": true,
  "nologo": true,          // ← 服务端收到并回显了 true
  "nofeed": true, "safe": false, "quality": "medium",
  "isMature": false, "isChild": false,
  "trackingData": { "actualModel": "sana", "usage": { "completionImageTokens": 1 } }
}
```

即：**服务端受理了 `nologo=true`，但水印仍然绘制** → 水印是后端后处理阶段无条件烙入的，参数侧无解。

补充观察：
- `model=flux` 请求，元数据 `actualModel=sana` → 免费层实际路由到可用模型，印证 §4.3「跨模型返回相同字节」
- 所有变体返回字节数完全一致（55231B）→ 参数不影响出图内容，只影响元数据记录

### 4.6 App 侧是否有自己的水印

排查结论：**没有**。

| 检查项 | 结果 |
|---|---|
| dex 中 `watermark` 相关字符串 | 仅 AdMob/广告 SDK 的（`gads:video:force_watermark`、`watermark_overlay_png_base64` 等） |
| `com.tit.imagegenerator.*` 内 `Canvas.drawText` 合成水印 | 未发现 |
| `waterMarkIV`（`g6/f` 布局中的 ImageView） | 仅为 BottomSheet **UI 上的图片控件**（预览标记），不写像素 |
| RC 配置 `is_max_size_watermark = true` | 控制"最大尺寸是否加标记"的开关，属 UI 展示逻辑 |

所以 App 拿到的就是 pollinations 已带水印的图，2API 直接取上游字节，水印来源单一。

### 4.7 去水印方案（本仓库 `watermark.py`）

水印位置固定锚定右下角（相对坐标 x≈0.78–0.99、y≈0.957–0.983，随图幅等比缩放）。

| 方案 | 做法 | 质量 | 依赖 |
|---|---|---|---|
| `cv2` | 区域检测白字+暗描边生成 mask → `cv2.inpaint(TELEA, r=7)` | 纯色/虚化背景几乎无痕；高频纹理有轻微涂抹 | opencv |
| `pillow` | 从水印正上方同尺寸带克隆覆盖 + 高斯柔化 + 30% 羽化过渡 | 保留纹理，可能有水平接缝 | 无 |

实测（768×768）：两种方法去除后 `has_watermark()` 复检均为 `False`。

**检测判据的坑**：最初用「右下角 vs 左下角白像素数对比」，在白底图上失效
（例：白杯白桌面，左下角白像素 5005 >> 右下角 429 → 漏判）。
改用**「白色像素且 7px 内有暗描边」**的像素计数（pollinations 水印是白字+黑描边的固定图章）：

| 样本 | 得分 | 判定 |
|---|---|---|
| 带印 768×768（3 个不同 prompt） | 2470–2523 | 有 |
| 带印 512×512 | 1793 | 有 |
| 去印后（768×768） | 0–54 | 无 |

阈值取 `max(250, 面积 × 0.0012)`，信噪比 >30×，6/6 样本判定正确。

不可行方案记录：
- `gen.pollinations.ai`（新版 API）匿名 401，需 `sk_`/`pk_` key（付费 x402 USDC）
- 旧端点 `/p/{prompt}` → 402
- 参数侧（`referrer`/`token`/`no_logo`）→ 全部无效

## 5. 辅助接口（明文 HTTP）

```
GET http://157.173.117.135/suggestions/all       → 200，10 KB JSON（推荐提示词库）
GET http://157.173.117.135/storage/safest-images → 200，31 B
```

`/suggestions/all` 返回结构（节选）：

```json
[{
  "thumbnailLink": "https://techinfortainment.com/media/suggestions/...",
  "orignalLink":   "https://techinfortainment.com/media/suggestions/...",
  "prompt": "Transform Make that girl bear",
  "tag": 0,
  "category": "image_result",
  "model": "SDXL",
  "allowed_apps": ["imagerator5","ai_imagerator","imagerator","imagerator4","downloader"]
}]
```

图片 CDN：`techinfortainment.com/media/suggestions/image_only/result/*.jpeg`

---

## 6. Firebase / Remote Config

| 项 | 值 |
|---|---|
| Firebase project number | `618549213407` |
| App ID | `1:618549213407:android:65a38ee1fbe8820118116a` |
| API key (arsc) | `AIzaSyA5IMoujgjFYSEqne3oCeTGjCW51D6NwlE` |
| FIS REST 注册 | ❌ `API_KEY_INVALID`（key 受限） |
| RC 键数量 | 62（无生图 key） |

RC 中的关键项：

- `internal_server_enabled` = `true`
- `auth_pre_re_to` = 448 hex 字符 RSA blob（会话凭证，native 层解密）
- `free_image_generation_limit_per_day` / `limit_image_generate` 等配额键
- `content_guidelines_url`、`discovery_data_url`、`ml_styles_data` 等配置 URL

同模拟器内另一 mod 包（`com.ai.art.aiimagegenerator...`，project `546583882737`）的 RC 含明文
`api_key = sk-PCZXtWBIJFnEj6D0yZLoaRKzdrjJmy6M74tOpynRZWHQpaRpPK`，
上游为 `faceswap/ghibli/api.imagix.dailymorningupdate.com`——**与本 App 无关**，仅作旁证记录。

---

## 7. 脱壳与动态分析记录

### 7.1 模拟器 ABI 关键坑

| AVD | abilist | 能否跑原版 APK |
|---|---|---|
| `remakeface` (API 33) | `x86_64, x86, arm64-v8a, armeabi-v7a, armeabi` | ✅ 带 ARM 翻译 |
| `openchat` (API 35) | `x86_64` | ❌ `INSTALL_FAILED_NO_MATCHING_ABIS` |
| `tfgy_e2e` | `x86_64` | ❌ 同上 |

`libstub.so` 只有 ARM 版本，必须靠 ndk_translation 运行。

### 7.2 脱壳尝试（产物在 `analysis/`）

成功做了**字节码级 nop**：

```
27 处 invoke-static {vX}, Lnp/dcc/protect/EntryPoint;->stub(I)V
  → 替换为 4 字节 nop（op=0x71，第 2 字节高 4 位=寄存器数）
  → 重算 dex checksum（adler32 @ offset 8）与 SHA1 signature（@ 12..32）
```

产物 `clean-signed.apk` 可在纯 x86_64 模拟器启动到 OnBoarding，
但 DCC 抽走的 `public native` 方法体缺失 → `UnsatisfiedLinkError`，功能不完整。

### 7.3 壳存活规律

- 仅「卸载 → 安装 → 第一次 `am start`」有几分钟可用窗口
- `front-door activity` 消失 = 壳已自毁，需重装
- `apktool` 全量重打（zip 结构变化）会触发壳完整性校验 → `SIGABRT`
- 🔑 **Mod 弹窗 `Join Now` 会发 `t.me` VIEW intent，模拟器无浏览器 handler → `ActivityNotFoundException` 崩主线程**，务必点 `Close`

### 7.4 Frida 脚本（`analysis/frida/`）

`ssl_final2.js` 已验证生效：

```javascript
// TLS 全放行（仅 SSLContext.setDefault 不够，必须 TrustManagerImpl.verifyChain）
var TMI = Java.use('com.android.org.conscrypt.TrustManagerImpl');
TMI.verifyChain.implementation = function(chain, authType, host, ...) { return chain; };

// OkHttp3 pinner 绕过
Java.use('okhttp3.CertificatePinner').check
    .overload('java.lang.String','java.util.List').implementation = function(h,p){};

// 崩溃压制（github 更新 404 / t.me intent）
Java.use('java.lang.Thread').setDefaultUncaughtExceptionHandler(...);
Java.use('java.lang.Runtime').exit.implementation = function(c){};   // 阻断自杀
```

日志确认 `[TM-OK] firebaseremoteconfig.googleapis.com` 等 TLS 已解密。

### 7.5 mitmproxy 读 dump 的正确姿势

```python
from mitmproxy import io as mio
with open('flow.dump', 'rb') as f:
    for fl in mio.FlowReader(f).stream():
        content = fl.request.get_content(strict=False)   # 自动处理 gzip
        body    = fl.response.get_content(strict=False)
```

比手工解析 tnetstring 可靠得多。

---

## 8. 结论

| 通道 | 结论 |
|---|---|
| deapi.ai | 协议 100% 还原，token 在 native 层 → 需真机 Frida native hook |
| **pollinations** | **纯协议打通，真实出图，已封装为 OpenAI 兼容 2API** |
| enter.pollinations | 上游已下线 |

本仓库交付 pollinations 通道的完整可用实现，含串行闸限速、错误重试、异步任务、demo 页面与压测脚本。
