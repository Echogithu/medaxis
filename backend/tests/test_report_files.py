"""真实文件解码与平台内取字边界；不使用业务数据库或外部模型。"""

import asyncio
import io
import socket
from unittest.mock import AsyncMock

import pytest

from app.services import report_files, report_text_worker
from app.services.report_files import (
    MAX_FILE_BYTES, ReportFileError, detect_report_type, extract_report_file, inspect_report_file,
)
from tests.report_samples import sample_image, text_pdf


@pytest.mark.parametrize("format_name,extension,mime", [
    ("JPEG", "jpg", "image/jpeg"), ("PNG", "png", "image/png"), ("WEBP", "webp", "image/webp"),
])
async def test_real_image_decoding_and_declared_type(format_name, extension, mime):
    result = await inspect_report_file(sample_image(format_name), f"sample.{extension}", mime)
    assert mime == result["mime_type"]
    assert 1 == result["page_count"]
    assert [] == result["pages"]


@pytest.mark.parametrize("content,name,mime,code", [
    (b"", "report.png", "image/png", "empty_file"),
    (b"a" * (MAX_FILE_BYTES + 1), "report.png", "image/png", "file_too_large"),
    (b"%PDF-malicious", "fake.png", "image/png", "invalid_type"),
    (b"\x89PNG\r\n\x1a\n", "report.png", "image/jpeg", "mime_mismatch"),
    (b"<svg></svg>", "report.svg", "image/svg+xml", "invalid_type"),
], ids=["empty", "oversized", "fake-extension", "mime-mismatch", "unsupported-svg"])
def test_untrusted_file_rejected_before_spawning(content, name, mime, code):
    with pytest.raises(ReportFileError) as caught:
        detect_report_type(content, name, mime)
    assert code == caught.value.code


@pytest.mark.parametrize("content,name,mime", [
    (b"\x89PNG\r\n\x1a\n", "broken.png", "image/png"),
    (b"%PDF-1.7\nbroken", "broken.pdf", "application/pdf"),
])
async def test_corrupt_file_gets_safe_error_without_raw_data(content, name, mime):
    with pytest.raises(ReportFileError) as caught:
        await inspect_report_file(content, name, mime)
    assert "invalid_file" == caught.value.code
    assert "broken" not in caught.value.message


@pytest.mark.parametrize("count,encrypted,code", [(21, False, "too_many_pages"), (1, True, "encrypted_pdf")])
async def test_pdf_page_and_password_limits(count, encrypted, code):
    with pytest.raises(ReportFileError) as caught:
        await inspect_report_file(text_pdf(count=count, encrypted=encrypted), "report.pdf", "application/pdf")
    assert code == caught.value.code


async def test_real_pdf_text_and_page_order_without_ocr(monkeypatch):
    result = await extract_report_file(text_pdf(count=2), "report.pdf", "application/pdf")
    assert 2 == result["page_count"]
    assert [1, 2] == [p["page"] for p in result["pages"]]
    assert all(p["method"] == "pdf_text" for p in result["pages"])
    assert "PAGE 1 WBC 6.2 HGB 132" in result["pages"][0]["text"]
    assert "PAGE 2 WBC 6.2 HGB 132" in result["pages"][1]["text"]


def test_network_entrypoints_are_denied(monkeypatch):
    for name in ["create_connection", "getaddrinfo"]:
        monkeypatch.setattr(socket, name, getattr(socket, name))
    for name in ["connect", "connect_ex"]:
        monkeypatch.setattr(socket.socket, name, getattr(socket.socket, name))
    report_text_worker.disable_network()
    with pytest.raises(RuntimeError, match="不允许网络"):
        socket.getaddrinfo("example.invalid", 443)
    with pytest.raises(RuntimeError, match="不允许网络"):
        socket.create_connection(("127.0.0.1", 9))
    with socket.socket() as connection:
        with pytest.raises(RuntimeError, match="不允许网络"):
            connection.connect(("127.0.0.1", 9))
        with pytest.raises(RuntimeError, match="不允许网络"):
            connection.connect_ex(("127.0.0.1", 9))


def test_network_monkeypatch_is_restored_after_context():
    originals = [socket.create_connection, socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex]
    with pytest.MonkeyPatch.context() as patch:
        for name in ["create_connection", "getaddrinfo"]:
            patch.setattr(socket, name, getattr(socket, name))
        for name in ["connect", "connect_ex"]:
            patch.setattr(socket.socket, name, getattr(socket.socket, name))
        report_text_worker.disable_network()
    assert originals == [socket.create_connection, socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex]


async def test_compressed_pdf_stream_bomb_is_rejected_before_full_decode():
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import NameObject, DecodedStreamObject
    writer = PdfWriter()
    writer.append(PdfReader(io.BytesIO(text_pdf())))
    stream = DecodedStreamObject()
    stream.set_data(b"%" + b"a" * (5 * 1024 * 1024))
    writer.pages[0][NameObject("/Contents")] = writer._add_object(stream.flate_encode())
    output = io.BytesIO()
    writer.write(output)
    assert len(output.getvalue()) < 10000
    with pytest.raises(ReportFileError) as caught:
        await inspect_report_file(output.getvalue(), "synthetic-bomb.pdf", "application/pdf")
    assert "invalid_file" == caught.value.code


def test_missing_local_model_is_not_downloaded(monkeypatch):
    monkeypatch.setattr(report_text_worker.Path, "is_file", lambda self: False)
    with pytest.raises(report_text_worker.LocalFileProblem) as caught:
        report_text_worker._ocr_engine()
    assert "ocr_unavailable" == caught.value.code


def test_corrupt_local_model_is_rejected_before_engine_creation(monkeypatch):
    monkeypatch.setattr(report_text_worker.Path, "read_bytes", lambda self: b"synthetic-corrupted-model")
    with pytest.raises(report_text_worker.LocalFileProblem) as caught:
        report_text_worker._ocr_engine()
    assert "ocr_unavailable" == caught.value.code


async def test_no_text_keeps_original_valid_and_requests_manual_entry():
    from PIL import Image
    output = io.BytesIO()
    Image.new("RGB", (100, 100), "white").save(output, format="PNG")
    result = await extract_report_file(output.getvalue(), "blank.png", "image/png")
    assert 1 == result["page_count"]
    assert result["needs_manual_entry"]
    assert "" == result["pages"][0]["text"]


async def test_worker_timeout_kills_owned_child_and_strips_credentials(monkeypatch):
    captured = {}
    class Child:
        returncode = None
        killed = False
        async def communicate(self, data=None):
            if self.killed:
                return b"", None
            await asyncio.sleep(1)
        def kill(self):
            self.killed = True
            self.returncode = -1
    child = Child()
    async def spawn(*args, **kwargs):
        captured.update(kwargs)
        return child
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-never-in-child")
    monkeypatch.setattr(report_files.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(report_files, "WORKER_TIMEOUT_SECONDS", .01)
    with pytest.raises(ReportFileError) as caught:
        await report_files._worker(b"synthetic", "image/png", extract=True)
    assert "local_timeout" == caught.value.code
    assert child.killed
    assert "OPENAI_API_KEY" not in captured["env"]


async def test_cancelling_local_work_kills_child(monkeypatch):
    child = AsyncMock()
    child.returncode = None
    child.communicate.side_effect = [asyncio.CancelledError(), (b"", None)]
    child.kill = lambda: setattr(child, "returncode", -1)
    monkeypatch.setattr(report_files.asyncio, "create_subprocess_exec", AsyncMock(return_value=child))
    with pytest.raises(asyncio.CancelledError):
        await report_files._worker(b"synthetic", "image/png", extract=True)
    assert -1 == child.returncode
    assert 2 == child.communicate.await_count


async def test_worker_start_failure_is_safe_and_not_a_success(monkeypatch):
    monkeypatch.setattr(report_files.asyncio, "create_subprocess_exec", AsyncMock(side_effect=OSError("synthetic-private-path")))
    with pytest.raises(ReportFileError) as caught:
        await report_files._worker(b"synthetic", "image/png", extract=True)
    assert "local_unavailable" == caught.value.code
    assert "synthetic-private-path" not in caught.value.message


def test_oversized_pixel_image_rejected_without_decoding_all_pixels(monkeypatch):
    monkeypatch.setattr(report_text_worker, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(report_text_worker.LocalFileProblem) as caught:
        report_text_worker._image(sample_image())
    assert "too_many_pixels" == caught.value.code


def test_animated_webp_rejected():
    from PIL import Image
    output = io.BytesIO()
    Image.new("RGB", (50, 50), "white").save(output, format="WEBP", save_all=True,
        append_images=[Image.new("RGB", (50, 50), "black")], duration=100, loop=0)
    with pytest.raises(report_text_worker.LocalFileProblem) as caught:
        report_text_worker._image(output.getvalue())
    assert "animated_image" == caught.value.code
