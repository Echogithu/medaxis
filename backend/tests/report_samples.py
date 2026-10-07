"""检查报告合成原件，不包含真人数据；供OCR及后续浏览器门禁复用。"""

import io
from pathlib import Path


def sample_image(format_name="PNG", *, chinese=False):
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new("RGB", (1200, 700), "white")
    draw = ImageDraw.Draw(image)
    fonts = [Path("C:/Windows/Fonts/msyh.ttc"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]
    font_path = next((path for path in fonts if path.is_file()), None)
    font = ImageFont.truetype(str(font_path), 38) if font_path else ImageFont.load_default(size=38)
    lines = ["血常规检查报告（合成样本）", "白细胞 WBC 6.2 10^9/L", "血红蛋白 HGB 132 g/L", "检查日期 2026-10-03"] if chinese else [
        "SYNTHETIC LAB REPORT", "WBC 6.2 10^9/L", "HGB 132 g/L", "Report date 2026-10-03",
    ]
    for index, text in enumerate(lines):
        draw.text((65, 70 + index * 120), text, font=font, fill="black")
    output = io.BytesIO()
    image.save(output, format=format_name)
    return output.getvalue()


def scanned_pdf(*, count=2, chinese=False):
    from PIL import Image
    pages = [Image.open(io.BytesIO(sample_image(chinese=chinese))).convert("RGB") for _ in range(count)]
    result = io.BytesIO()
    pages[0].save(result, format="PDF", save_all=True, append_images=pages[1:], resolution=150)
    return result.getvalue()


def text_pdf(*, count=1, encrypted=False):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer = PdfWriter()
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    for index in range(count):
        page = writer.add_blank_page(width=600, height=700)
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 20 Tf 50 600 Td (SYNTHETIC LAB PAGE {index+1} WBC 6.2 HGB 132) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypted:
        writer.encrypt("synthetic-password")
    result = io.BytesIO()
    writer.write(result)
    return result.getvalue()
