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
    from PIL import Image, ImageChops, ImageFilter
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


def _threshold(w, h):
    """水印像素数阈值（随面积缩放）：带印约 0.0045~0.007×面积，无印 <0.0002×面积"""
    return max(250, int(w * h * 0.0012))


def _outlined_text_score(gray_roi):
    """统计「白字 + 近邻暗描边」像素数 —— pollinations 水印的显著特征"""
    bright = (gray_roi > 190).astype(np.uint8)
    dark = (gray_roi < 95).astype(np.uint8)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    near_dark = cv2.dilate(dark, k, iterations=1)
    outlined = cv2.bitwise_and(bright, near_dark)
    return int(cv2.dilate(outlined, k, iterations=1).sum())


def _outlined_text_score_pil(gray_im):
    """纯 Pillow 版同样判据：白字 ∩ 膨胀后的暗像素"""
    bright = gray_im.point(lambda v: 255 if v > 190 else 0)
    dark = gray_im.point(lambda v: 255 if v < 95 else 0)
    near_dark = dark.filter(ImageFilter.MaxFilter(7))
    outlined = ImageChops.multiply(bright, near_dark)
    outlined = outlined.filter(ImageFilter.MaxFilter(7))
    return int(sum(1 for v in outlined.get_flattened_data() if v > 0))


def has_watermark(jpeg_bytes):
    """
    检测右下角是否存在 pollinations 水印。

    判据：右下角区域内「白色像素且 7px 内有暗像素」的数量（白字 + 暗描边的特征）。
    不能用「右下 vs 左下亮度对比」——白底图（如白杯白桌）会在左下产生大量白像素导致漏判。
    无 cv2 时走纯 Pillow 路径；连 Pillow 都没有才返回 None。
    """
    if not _HAS_PIL:
        return None
    try:
        im = Image.open(io.BytesIO(jpeg_bytes)).convert("RGB")
    except Exception:
        return None
    w, h = im.size
    x0, y0, _, _ = _region(w, h)
    gray_im = im.crop((x0, y0, w, h)).convert("L")
    if _HAS_CV2:
        score = _outlined_text_score(np.array(gray_im))
    else:
        score = _outlined_text_score_pil(gray_im)
    return score > _threshold(w, h)


def _mask_cv2(img):
    """在右下角区域内检测水印（白字 + 暗描边）生成 mask"""
    h, w = img.shape[:2]
    x0, y0, x1, y1 = _region(w, h)
    roi = img[y0:y1, x0:x1]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

    _, bright = cv2.threshold(gray, 190, 255, cv2.THRESH_BINARY)
    _, dark = cv2.threshold(gray, 95, 255, cv2.THRESH_BINARY_INV)

    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    # 只取「白字且近邻有暗描边」的像素，避免白底图整片被 mask 掉
    near_dark = cv2.dilate(dark, k, iterations=2)
    text = cv2.bitwise_and(bright, near_dark)
    mask = cv2.dilate(text, k, iterations=3)   # 膨胀覆盖描边

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
