# DCC(Dex2C) 壳 patch 记录

目标：让 `np.dcc.protect` 加固的 APK 能在无 ARM 翻译的 x86_64 模拟器上启动。

## 原理

壳在 27 个类的 `<clinit>` 中插入完整性校验调用：

```smali
const v0, 0x16
invoke-static {v0}, Lnp/dcc/protect/EntryPoint;->stub(I)V
```

`stub()` 是 native 方法（`libstub.so`），缺失时抛 `UnsatisfiedLinkError`。

## 字节码级 patch（无需 smali 汇编器）

`invoke-static` 为 format 35c，编码：`0x71 | (A<<4|G) | BBBB(lo) | BBBB(hi) | FEDC(lo) | FEDC(hi)`，
其中 A = 寄存器个数。

把 `0x71` 起始的 4 字节直接改成 `0x00 0x00 0x00 0x00`（两个 nop）：

```python
import struct, json
idxs = json.load(open('stub_idx.json'))   # 通过解析 method_ids 得到 stub 的 method index

def patch(data, midx):
    n = 0; i = 0
    while i < len(data) - 4:
        if data[i] == 0x71 and (data[i+1] & 0x0f) == 0x00 and 1 <= (data[i+1] >> 4) <= 5:
            if struct.unpack_from('<H', data, i+2)[0] == midx:
                data[i:i+4] = b'\x00\x00\x00\x00'
                n += 1; i += 4; continue
        i += 1
    return n
```

## 关键：必须重算 dex 头

否则安装后报 `Bad checksum (..., expected ...)` → `ClassNotFoundException`：

```python
import hashlib, zlib, struct
sig = hashlib.sha1(d[32:]).digest()
d[12:32] = sig
struct.pack_into('<I', d, 8, zlib.adler32(bytes(d[12:])) & 0xffffffff)
```

## 结果与局限

- ✅ 可在 `x86_64` 纯 ABI 模拟器启动到 OnBoardingActivity
- ❌ DCC 抽走的 `public native` 方法体（如 `LA5/f;->k(LK3/q;)`）仍缺失 → `UnsatisfiedLinkError`
- 结论：**完整功能必须运行在带 ARM 翻译的模拟器**（如 `abilist` 含 `arm64-v8a` 的 AVD）

## 另一条路：跳过重打包

`apktool` 全量重打会改变 zip 结构，触发壳的完整性校验直接 `SIGABRT`。
即使 dex 内容完全一致也不行。故 gadget 注入方案不可行。
