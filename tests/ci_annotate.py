"""Упавшие тесты — в аннотации GitHub Actions: их видно на странице прогона без входа (журналы — только со входом).

python tests/ci_annotate.py <журнал unittest -v>
"""

import re
import sys

text = open(sys.argv[1], encoding="utf-8", errors="replace").read()
blocks = re.split(r"^={50,}$", text, flags=re.M)[1:]
for block in blocks[:10]:                       # GitHub показывает не больше 10 аннотаций на шаг
    lines = [line for line in block.strip().splitlines() if not re.fullmatch(r"-{50,}", line)]
    if not lines:
        continue
    title = lines[0]
    body = "\n".join(lines[1:])[-1500:]
    print(f"::error title={title}::" + body.replace("%", "%25").replace("\r", "").replace("\n", "%0A"))
if not blocks:
    tail = "\n".join(text.strip().splitlines()[-30:])
    print("::error title=Тесты упали без отчёта unittest::" + tail.replace("%", "%25").replace("\n", "%0A"))
