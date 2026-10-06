"""У каждой русской строки интерфейса есть английский перевод.

e2e_english.py смотрит на то, что видно на экране; этот тест — на исходники: каждый tr("…"), каждая причина
Skip("…") / OSError(…, "…") (их показывают через tr(why)) и названия из таблиц, которые идут в tr() переменной.
"""

import ast
import glob
import os
import re
import sys
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
import i18n  # noqa: E402

CYR = re.compile("[А-Яа-яЁё]")


def literals():
    """(файл, строка, текст) для русских строк в tr(), Skip() и OSError() во всех модулях программы."""
    out = []
    for path in glob.glob(os.path.join(ROOT, "*.py")):
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
            if name not in ("tr", "Skip", "OSError"):
                continue
            for arg in node.args[:2]:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and CYR.search(arg.value):
                    out.append((os.path.basename(path), node.lineno, arg.value))
    return out


def tables():
    """Названия из таблиц: они попадают в tr() переменной, и разбор исходника их не видит."""
    import compcore
    import meta_page
    import metacore
    out = list(metacore.GROUPS.values()) + list(meta_page.PRESETS.values()) + list(meta_page.SHORT.values())
    out += list(meta_page.OUTPUTS.values()) + [n for _g, n in metacore.EXIF_TAGS.values()]
    out += [n for _g, n in metacore.IPTC.values() if n] + [n for _g, n in metacore.UDTA.values() if n]
    out += list(compcore.MODES.values()) + list(compcore.KINDS.values())
    return out


class Translations(unittest.TestCase):
    def test_every_literal_has_english(self):
        missing = sorted({f"{f}:{n}  {t!r}" for f, n, t in literals() if t not in i18n.EN})
        self.assertEqual(missing, [], "\n" + "\n".join(missing))

    def test_every_table_name_has_english(self):
        missing = sorted({t for t in tables() if CYR.search(t) and t not in i18n.EN})
        self.assertEqual(missing, [], "\n" + "\n".join(missing))

    def test_no_key_twice(self):
        """Ключ дважды — Python молча берёт последний перевод, и первый правят зря."""
        with open(os.path.join(ROOT, "i18n.py"), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        en = next(n.value for n in ast.walk(tree)
                  if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "EN")
        keys = [k.value for k in en.keys]
        self.assertEqual(sorted({k for k in keys if keys.count(k) > 1}), [])

    def test_placeholders_match(self):
        bad = [k for k, v in i18n.EN.items()
               if sorted(re.findall(r"{(\w+)}", k)) != sorted(re.findall(r"{(\w+)}", v))]
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
