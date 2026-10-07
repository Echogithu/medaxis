"""真实CPU本地OCR与PDF取字门禁，保存合成样本、逐页结果和耗时。"""

import asyncio
import importlib.metadata
import json
import platform
import time
from pathlib import Path

from app.services.report_files import extract_report_file, inspect_report_file
from tests.report_samples import sample_image, scanned_pdf, text_pdf

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = ROOT / ".ai/tasks/2026-10-03-patient-reports/artifacts/ocr"


async def main():
    ARTIFACT.mkdir(parents=True, exist_ok=True)
    cases = [
        ("synthetic-en.jpg", sample_image("JPEG"), "image/jpeg", 1, "local_ocr", ["6.2", "132"]),
        ("synthetic-zh.png", sample_image(chinese=True), "image/png", 1, "local_ocr", ["白细胞", "6.2", "132"]),
        ("synthetic-en.webp", sample_image("WEBP"), "image/webp", 1, "local_ocr", ["6.2", "132"]),
        ("text-2pages.pdf", text_pdf(count=2), "application/pdf", 2, "pdf_text", ["WBC 6.2", "HGB 132"]),
        ("scanned-zh-2pages.pdf", scanned_pdf(chinese=True), "application/pdf", 2, "local_ocr", ["白细胞", "6.2", "132"]),
        ("text-20pages.pdf", text_pdf(count=20), "application/pdf", 20, "pdf_text", ["WBC 6.2", "HGB 132"]),
        ("scanned-20pages.pdf", scanned_pdf(count=20), "application/pdf", 20, "local_ocr", ["6.2", "132"]),
    ]
    results = []
    for name, content, mime, count, method, expected in cases:
        (ARTIFACT / name).write_bytes(content)
        inspected = await inspect_report_file(content, name, mime)
        assert count == inspected["page_count"], name
        start = time.monotonic()
        result = await extract_report_file(content, name, mime)
        elapsed = time.monotonic() - start
        assert count == result["page_count"], name
        assert list(range(1, count + 1)) == [page["page"] for page in result["pages"]], name
        assert not result["needs_manual_entry"], name
        for page in result["pages"]:
            assert method == page["method"], name
            assert all(fragment in page["text"] for fragment in expected), f"{name}: key fragments missing"
        results.append({"sample": name, "bytes": len(content), "seconds": round(elapsed, 3), "result": result})
        (ARTIFACT / "results.partial.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"OCR_CASE_PASS {name}: pages={count}, seconds={elapsed:.3f}", flush=True)
    evidence = {"platform": platform.platform(), "python": platform.python_version(),
        "versions": {name: importlib.metadata.version(name) for name in ["rapidocr", "onnxruntime", "pypdfium2", "pillow", "pypdf"]},
        "network_boundary": "每次真实解析均运行禁止socket连接的本地子进程；网络入口拒绝另有单元测试",
        "cases": results}
    (ARTIFACT / "results.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print("REPORT_OCR_SMOKE_PASS: seven synthetic cases including Chinese and twenty-page scan", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
