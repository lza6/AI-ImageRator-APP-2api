# -*- coding: utf-8 -*-
"""
pollinations 水印去除模块

背景：image.pollinations.ai 免费层在出图后由**服务端**在右下角绘制 pollinations.ai 水印，
`nologo=true` 参数会被受理但不再执行（EXIF 元数据回显 "nologo":true 但水印仍在）。
因此无法通过请求参数去除，只能本地处理。

两种策略：
  - inpaint（需 opencv）：质量最好，纹理可还原
  - clone（纯 Pillow）：从水印上方采样克隆覆盖，零依赖
"""

import io

try:
    from PIL import Image, ImageFilter
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

try:
    import numpy as np
    import cv2
    _HAS_CV2 = True
except ImportError:
    _HAS_CV2 = False

# 水印所在区域（相对坐标）：右下角
RX0, RY0 = 0.70, 0.93


def _region(img_w, img_h):
    return int(img_w * RX0), int(img_h * RY0), img_w, img_h


def has_watermark(jpeg_bytes):
    """粗判：右下角高亮像素显著多于左下角 → 判定有水印"""
    if not _HAS_PIL:
        return None
    try:
        im = Image.open(io.BytesIO(jpeg_bytes)).convert("RGB")
    except Exception:
        return None
    w, h = im.size
    bh = max(int(h * 0.07), 8)
    bw = max(int(w * 0.28), 40)

    def bright(box):
        patch = im.crop(box)
        return sum(1 for r, g, b in patch.get_flattened_data() if r > 195 and g > 195 and b > 195)

    rb = bright((w - bw, h - bh, w, h))
    lb = bright((0, h - bh, bw, h))
    return (rb - lb) > 150


def _mask_cv2(img):
    """在右下角区域内检测水印（白字 + 暗描边）生成 mask"""
    h, w = img.shape[:2]
    x0, y0, x1, y1 = _region(w, h)
    roi = img[y0:y1, x0:x1]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

    _, bright = cv2.threshold(gray, 190, 255, cv2.THRESH_BINARY)
    _, dark = cv2.threshold(gray, 95, 255, cv2.THRESH_BINARY_INV)

    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    bright_d = cv2.dilate(bright, k, iterations=2)
    # 白字附近有暗描边 → 更可能是水印文字
    near_dark = cv2.dilate(dark, k, iterations=2)
    text = cv2.bitwise_and(bright_d, near_dark)
    mask = cv2.bitwise_or(bright_d, text)
    mask = cv2.dilate(mask, k, iterations=2)

    full = np.zeros((h, w), np.uint8)
    full[y0:y1, x0:x1] = mask
    return full


def _remove_cv2(im):
    arr = cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)
    mask = _mask_cv2(arr)
    if int(mask.sum()) == 0:
        return im, "no-watermark-detected"
    out = cv2.inpaint(arr, mask, 7, cv2.INPAINT_TELEA)
    return Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB)), "inpaint"


def _remove_pillow(im):
    """纯 Pillow：从水印上方同宽区域克隆覆盖 + 边缘羽化"""
    w, h = im.size
    x0, y0, x1, y1 = _region(w, h)
    bh = y1 - y0
    # 来源带：水印正上方同样高度
    sy0 = max(0, y0 - int(bh * 1.4))
    sy1 = sy0 + bh
    src = im.crop((x0, sy0, x1, sy1))
    # 轻微模糊，避免纹理不连续过于突兀
    src = src.filter(ImageFilter.GaussianBlur(radius=max(1, bh // 22)))
    im.paste(src, (x0, y0))

    # 与上方区域做柔化过渡，避免接缝
    blend_h = max(2, bh // 3)
    if y0 - blend_h >= 0:
        band_src = im.crop((x0, y0 - blend_h, x1, y0))
        band_dst = im.crop((x0, y0, x1, y0 + blend_h))
        im.paste(Image.blend(band_dst, band_src, 0.35), (x0, y0))
    return im, "clone"


def remove(jpeg_bytes, method="auto"):
    """
    去除水印，返回 (jpeg_bytes, info)

    method: auto | cv2 | pillow | off
    """
    if method == "off":
        return jpeg_bytes, {"removed": False, "reason": "disabled"}
    if not _HAS_PIL:
        return jpeg_bytes, {"removed": False, "reason": "pillow-missing"}

    try:
        im = Image.open(io.BytesIO(jpeg_bytes)).convert("RGB")
    except Exception as e:
        return jpeg_bytes, {"removed": False, "reason": "decode-failed: %s" % e}

    if not has_watermark(jpeg_bytes):
        return jpeg_bytes, {"removed": False, "reason": "no-watermark-detected"}

    used = None
    if method in ("auto", "cv2") and _HAS_CV2:
        im, used = _remove_cv2(im)
    elif method in ("auto", "pillow") or not _HAS_CV2:
        im, used = _remove_pillow(im)

    if used == "no-watermark-detected":
        return jpeg_bytes, {"removed": False, "reason": "no-watermark-detected"}

    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=95, subsampling=0)
    return buf.getvalue(), {"removed": True, "method": used}


def capabilities():
    return {"pillow": _HAS_PIL, "opencv": _HAS_CV2, "default": "auto"}
