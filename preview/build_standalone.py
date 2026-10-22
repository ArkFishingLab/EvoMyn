"""Package the local preview as one HTML file, without network dependencies."""
from pathlib import Path
import re

root = Path(__file__).resolve().parent
modules = []
for name in ("round-layout.mjs", "settings-model.mjs", "app.mjs"):
    source = (root / name).read_text(encoding="utf-8")
    source = re.sub(r"^import .*?;\s*", "", source, flags=re.MULTILINE)
    modules.append(source.replace("export ", ""))
html = (root / "index.html").read_text(encoding="utf-8")
html = html.replace('<script type="module" src="./app.mjs"></script>',
                    '<script type="module">\n' + '\n'.join(modules) + '\n</script>')
target = root / "中文圆屏预览.html"
target.write_text(html, encoding="utf-8")
print(f"Created {target.name}: {target.stat().st_size} bytes")
