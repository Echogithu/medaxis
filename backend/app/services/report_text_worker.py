"""无网络的报告解码/取字子进程，禁止云OCR回退及运行时下载模型。"""

import hashlib
import io
import json
import math
import socket
import sys
import unicodedata
import warnings
from contextlib import closing, redirect_stdout
from pathlib import Path

from app.services.report_files import MAX_FILE_BYTES, MAX_IMAGE_PIXELS, MAX_REPORT_PAGES, MAX_TEXT_CHARACTERS


class LocalFileProblem(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message


def _no_network(*_args, **_kwargs):
    raise RuntimeError("报告本地取字不允许网络连接")


def disable_network():
    # OCR引擎只接收已解码的内存图像，下载器和URL输入都不能绕过此边界。
    socket.socket.connect = _no_network
    socket.socket.connect_ex = _no_network
    socket.create_connection = _no_network
    socket.getaddrinfo = _no_network


def clean_text(value: str) -> str:
    return "".join(c for c in value if c in "\n\r\t" or not unicodedata.category(c).startswith("C")).strip()


def _image(data: bytes):
    from PIL import Image, ImageOps
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        try:
            image = Image.open(io.BytesIO(data))
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise LocalFileProblem("too_many_pixels", "图片超过2000万像素，请缩小后上传")
            if getattr(image, "n_frames", 1) != 1:
                raise LocalFileProblem("animated_image", "请上传单页静态图片，动画文件不支持")
            image.verify()
            image = Image.open(io.BytesIO(data))
            image.load()
            return ImageOps.exif_transpose(image).convert("RGB")
        except (Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
            raise LocalFileProblem("too_many_pixels", "图片像素过多，请缩小后上传") from exc


def _ocr_engine():
    from rapidocr import RapidOCR
    import rapidocr
    # 此锁定版本的wheel带模型。必须显式验证模型在本地，禁止默认缺失时自动下载。
    model_dir = Path(rapidocr.__file__).parent / "models"
    models = {
        "Det.model_path": model_dir / "PP-OCRv6_det_small.onnx",
        "Cls.model_path": model_dir / "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
        "Rec.model_path": model_dir / "PP-OCRv6_rec_small.onnx",
    }
    checksums = {
        "Det.model_path": "090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f",
        "Cls.model_path": "e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c",
        "Rec.model_path": "6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884",
    }
    if not all(path.is_file() for path in models.values()):
        raise LocalFileProblem("ocr_unavailable", "本地识字模型缺失，原件可保留并人工录入")
    if any(hashlib.sha256(path.read_bytes()).hexdigest() != checksums[key] for key, path in models.items()):
        raise LocalFileProblem("ocr_unavailable", "本地识字模型校验失败，原件可保留并人工录入")
    return RapidOCR(params={**{key: str(path) for key, path in models.items()},
        "Global.log_level": "error",
        "EngineConfig.onnxruntime.intra_op_num_threads": 2,
        "EngineConfig.onnxruntime.inter_op_num_threads": 1})


def _ocr(image, engine) -> str:
    import numpy as np
    image.thumbnail((2200, 2200))
    result = engine(np.asarray(image))
    return clean_text("\n".join(result.txts or []))


def process(data: bytes, mime: str, *, extract: bool) -> dict:
    if mime == "application/pdf":
        from pypdf import apply_configuration
        # 在解压前限制每条流的输出；字符数限制不能替代解压资源边界。
        with apply_configuration(zlib_maximum_output_length=4 * 1024 * 1024,
            lzw_maximum_output_length=4 * 1024 * 1024,
            run_length_maximum_output_length=4 * 1024 * 1024,
            array_based_stream_maximum_output_length=4 * 1024 * 1024,
            maximum_declared_stream_length=MAX_FILE_BYTES,
            page_tree_maximum_entries=1000, xform_maximum_invocations_per_extraction=500):
            return _process(data, mime, extract=extract)
    return _process(data, mime, extract=extract)


def _process(data: bytes, mime: str, *, extract: bool) -> dict:
    if not data or len(data) > MAX_FILE_BYTES:
        raise LocalFileProblem("invalid_size", "文件为空或超过10MiB")
    pages = []
    engine = None
    if mime != "application/pdf":
        image = _image(data)
        if extract:
            engine = _ocr_engine()
            pages.append({"page": 1, "text": _ocr(image, engine), "method": "local_ocr"})
        result = {"mime_type": mime, "page_count": 1, "pages": pages}
    else:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise LocalFileProblem("encrypted_pdf", "不支持加密PDF，请提供未加密的可读版本")
        count = len(reader.pages)
        if not 1 <= count <= MAX_REPORT_PAGES:
            raise LocalFileProblem("too_many_pages", "每份报告须为1至20页，请拆分后上传")
        decoded_bytes = 0
        for page in reader.pages:
            contents = page.get_contents()
            decoded_bytes += len(contents.get_data()) if contents else 0
            if decoded_bytes > 8 * 1024 * 1024:
                raise LocalFileProblem("too_much_content", "PDF解码内容过多，请拆分后上传")
        if extract:
            import pypdfium2 as pdfium
            # 渲染仅在缺少文字层的页上启用，OCR和PDF句柄均在此进程内。
            with pdfium.PdfDocument(data) as document:
                for index, page in enumerate(reader.pages):
                    text = clean_text(page.extract_text() or "")
                    method = "pdf_text"
                    if len(text) < 8:
                        if engine is None:
                            engine = _ocr_engine()
                        with closing(document[index]) as rendered_page:
                            width, height = rendered_page.get_size()
                            if not all(math.isfinite(v) and v > 0 for v in (width, height)):
                                raise LocalFileProblem("invalid_file", "PDF页尺寸无效，请提供可读版本")
                            scale = min(2.5, 2500 / max(width, height))
                            with closing(rendered_page.render(scale=scale)) as bitmap:
                                image = bitmap.to_pil().convert("RGB")
                                text = _ocr(image, engine)
                        method = "local_ocr"
                    pages.append({"page": index + 1, "text": text, "method": method})
                    if sum(len(p["text"]) for p in pages) > MAX_TEXT_CHARACTERS:
                        raise LocalFileProblem("too_much_text", "报告文字过多，请拆分后整理")
        result = {"mime_type": mime, "page_count": count, "pages": pages}
    if sum(len(p["text"]) for p in pages) > MAX_TEXT_CHARACTERS:
        raise LocalFileProblem("too_much_text", "报告文字过多，请拆分后整理")
    result["needs_manual_entry"] = extract and not any(p["text"] for p in pages)
    return result


def main():
    disable_network()
    try:
        mode, mime = sys.argv[1:]
        data = sys.stdin.buffer.read(MAX_FILE_BYTES + 1)
        with redirect_stdout(sys.stderr):
            result = process(data, mime, extract=mode == "extract")
    except LocalFileProblem as exc:
        result = {"error": exc.code, "message": exc.message}
    except (ImportError, ModuleNotFoundError):
        result = {"error": "ocr_unavailable", "message": "本地识别依赖不可用，原件可保留并人工录入"}
    except Exception:
        # 不把原件、身份、模型路径或底层异常写回用户/应用日志。
        result = {"error": "invalid_file", "message": "文件损坏或本地识别失败，请提供可读原件或人工录入"}
    sys.stdout.write(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
