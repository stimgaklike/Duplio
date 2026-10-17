"""Импорт в начале каждого e2e: рабочие папки всех вкладок («Сжатие», «Конвертация», «Метаданные») — временные.

Окно при выходе чистит рабочие папки всех трёх вкладок. Тест, подменивший только свою, при закрытии стирал
настоящие %LOCALAPPDATA%\\Duplio\\work, convert и meta — и копии, которые владелец в это время готовил
в установленном Duplio. Тест может после этого поставить свою папку — эта подмена её не трогает.
"""

import atexit
import shutil
import tempfile

import compcore
import convcore
import metacore

REAL = {m: m.WORK for m in (compcore, convcore, metacore)}
for _mod in REAL:
    _mod.WORK = tempfile.mkdtemp(prefix=f"dup_e2e_{_mod.__name__}_")
    atexit.register(shutil.rmtree, _mod.WORK, True)
