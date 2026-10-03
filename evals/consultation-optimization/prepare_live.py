"""只打包 Python 源码与合成输入；生成 stdin 脚本，不包含环境、配置或凭证。"""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import zipfile


parser = argparse.ArgumentParser()
parser.add_argument("--source-root", type=Path, required=True)
parser.add_argument("--label", choices=["before", "after"], required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
here = Path(__file__).resolve().parent
buffer = io.BytesIO()
with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
    for path in sorted((args.source_root / "app").rglob("*.py")):
        archive.writestr(str(path.relative_to(args.source_root)).replace("\\", "/"), path.read_bytes())
encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
fixtures = json.loads((here / "live-fixtures.json").read_text(encoding="utf-8"))
script = f'''import base64, io, json, sys, tempfile, zipfile
from pathlib import Path
target = Path(tempfile.mkdtemp(prefix="medaxis-synthetic-probe-"))
zipfile.ZipFile(io.BytesIO(base64.b64decode({encoded!r}))).extractall(target)
sys.path.insert(0, str(target))
'''
script += (here / "live_probe.py").read_text(encoding="utf-8")
script += f'\nresult = asyncio.run(run_live({fixtures!r}))\nresult.update(label={args.label!r}, source_zip_sha256={hashlib.sha256(buffer.getvalue()).hexdigest()!r})\nprint(json.dumps(result, ensure_ascii=False))\n'
args.output.write_text(script, encoding="utf-8")
print(f"已准备 {args.label} 合成模型探测脚本；只包含 Python 源码与合成输入")
