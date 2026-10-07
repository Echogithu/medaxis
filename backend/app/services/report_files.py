"""报告原件校验及平台内取字；重型解析在可终止的子进程中执行。"""

import asyncio
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_REPORT_FILES = 5
MAX_REPORT_PAGES = 20
MAX_IMAGE_PIXELS = 20_000_000
MAX_TEXT_CHARACTERS = 60_000
WORKER_TIMEOUT_SECONDS = 90
MAX_WORKER_OUTPUT = 512 * 1024
EXTENSION_MIME = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".webp": "image/webp", ".pdf": "application/pdf",
}


@dataclass
class ReportFileError(Exception):
    code: str
    message: str

    def __str__(self):
        return self.message


def detect_report_type(content: bytes, filename: str, declared_mime: str | None) -> str:
    """同时核对格式签名、扩展名和声明，不把扩展名当真实内容。"""
    if not content:
        raise ReportFileError("empty_file", "文件为空，请选择可读的报告原件")
    if len(content) > MAX_FILE_BYTES:
        raise ReportFileError("file_too_large", "每个文件不能超过10MiB")
    expected = EXTENSION_MIME.get(Path(filename).suffix.lower())
    detected = None
    if content.startswith(b"\xff\xd8\xff"):
        detected = "image/jpeg"
    elif content.startswith(b"\x89PNG\r\n\x1a\n"):
        detected = "image/png"
    elif content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        detected = "image/webp"
    elif content.startswith(b"%PDF-"):
        detected = "application/pdf"
    if not expected or detected != expected:
        raise ReportFileError("invalid_type", "仅支持内容完整、扩展名正确的JPEG、PNG、WEBP或PDF")
    if declared_mime and declared_mime.split(";", 1)[0].strip().lower() not in {
        detected, "application/octet-stream",
    }:
        raise ReportFileError("mime_mismatch", "文件声明格式与实际内容不一致")
    return detected


async def _worker(content: bytes, mime: str, *, extract: bool) -> dict:
    # 不继承平台凭证/模型配置；本地子进程无需访问数据库或外部服务。
    env = {key: value for key, value in os.environ.items() if key.upper() in {
        "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LD_LIBRARY_PATH",
    }}
    env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", OMP_NUM_THREADS="2")
    backend = Path(__file__).resolve().parents[2]
    args = [sys.executable, "-m", "app.services.report_text_worker", "extract" if extract else "inspect", mime]
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    try:
        process = await asyncio.create_subprocess_exec(
            *args, cwd=backend, env=env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, **options,
        )
    except OSError as exc:
        raise ReportFileError("local_unavailable", "本地识别不可用，请保留原件并人工录入") from exc
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(content), WORKER_TIMEOUT_SECONDS)
    except (TimeoutError, asyncio.CancelledError) as exc:
        if process.returncode is None:
            process.kill()
        # 继续收走管道，避免stdout缓冲区满时只wait导致清理悬挂。
        await process.communicate()
        if isinstance(exc, asyncio.CancelledError):
            raise
        raise ReportFileError("local_timeout", "本地识别超时，原件可保留并人工录入") from exc
    if process.returncode != 0 or len(stdout) > MAX_WORKER_OUTPUT:
        raise ReportFileError("local_unavailable", "本地识别不可用，请保留原件并人工录入")
    try:
        result = json.loads(stdout)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ReportFileError("local_unavailable", "本地识别不可用，请保留原件并人工录入") from exc
    if not isinstance(result, dict):
        raise ReportFileError("local_unavailable", "本地识别不可用，请保留原件并人工录入")
    if "error" in result:
        raise ReportFileError(result["error"], result["message"])
    return result


async def inspect_report_file(content: bytes, filename: str, declared_mime: str | None = None) -> dict:
    """上传前深度校验原件，返回真实页数；不进行OCR或外部调用。"""
    mime = detect_report_type(content, filename, declared_mime)
    return await _worker(content, mime, extract=False)


async def extract_report_file(content: bytes, filename: str, declared_mime: str | None = None) -> dict:
    """只返回平台内识别的逐页文字；是否外发由上层独立同意流程控制。"""
    mime = detect_report_type(content, filename, declared_mime)
    return await _worker(content, mime, extract=True)
