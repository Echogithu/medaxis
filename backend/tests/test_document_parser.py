"""文档解析器的独立文件格式回归。"""

from io import BytesIO

import pytest
from starlette.datastructures import UploadFile

from app.services.document_parser import parse_uploaded_file


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        pytest.param("合成检查结果".encode("utf-8"), "合成检查结果", id="plain-utf8"),
        pytest.param("合成检查结果".encode("gbk"), "合成检查结果", id="gbk"),
        pytest.param(b"synthetic:\xff", "synthetic:ÿ", id="latin-1-fallback"),
    ],
)
@pytest.mark.asyncio
async def test_txt_decodes_supported_fallbacks(content: bytes, expected: str) -> None:
    upload = UploadFile(filename="synthetic-report.txt", file=BytesIO(content))

    text, file_type = await parse_uploaded_file(upload)

    assert text == expected
    assert file_type == "txt"


@pytest.mark.asyncio
async def test_utf8_bom_text_is_returned_without_a_leading_bom() -> None:
    upload = UploadFile(
        filename="synthetic-report.txt",
        file=BytesIO("合成检查结果".encode("utf-8-sig")),
    )

    text, file_type = await parse_uploaded_file(upload)

    assert text == "合成检查结果"
    assert file_type == "txt"
