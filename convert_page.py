"""Вкладка «Конвертация»: видео и звук в другой формат — готовые наборы или свой выбор.

Устроена как «Сжатие» (CompressPage): подготовка копий, список «было → станет» с превью кадра, сравнение
крупно, замена оригиналов (в Корзину) или «положить рядом» (оригинал остаётся). Отличаются карточка
(наборы, «Свой» — выпадающие списки, результат), тексты и строки списка. Логика — в convcore.py.
"""

import os
from dataclasses import replace

from PySide6.QtGui import QColor

from PySide6.QtWidgets import QButtonGroup, QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QPushButton, QWidget

import compcore
import convcore
import dupcore
import ui_util as U
from compress_page import CompressPage, WrapLabel, score_text
from i18n import num, plural, tr
from logs import log

def kind_of(path):
    return os.path.splitext(path)[1].lstrip(".").upper()


class ConvertPage(CompressPage):
    FOLDER_KEY = "convert_folder"
    WHAT = "Конвертация"
    SAVES = False               # размер может и вырасти — «освободится» не пишем
    GOOD = 5                    # «Как» — зелёным
    RIGHT = (3, 4)              # «Было», «Стало»
    WIDTHS = (84, 126, 126, 76, 76, 112)    # вместе с «Где лежит» — без прокрутки вбок
    SPLIT = [780, 440]                      # столбцов больше; кадру видео хватает и узкой панели

    def texts(self):
        return {
            "title": tr("Конвертация в другой формат"),
            "start": tr("Подготовить файлы"),
            "idle": tr("Выбери папку и что получить, и нажми «Подготовить файлы»."),
            "empty": tr("Здесь появятся новые файлы: было → станет.\n\nСначала программа готовит и проверяет их "
                        "в своей папке — оригиналы не трогает, пока ты не нажмёшь кнопку внизу."),
            "preparing": tr("Готовлю… Новые файлы появятся здесь сразу, по одному."),
            "step": lambda done, total: tr("Готовлю файлы · {done} из {total}", done=done, total=total),
            "window": lambda pct: tr("{app} — конвертация, {pct}%", app=U.APP_TITLE, pct=pct),
            "nothing": lambda t: tr("Готово за {t}. Конвертировать нечего.", t=t),
            "nothing_why": tr("Ни один файл не удалось перевести — причины по кнопке «Не конвертированы»."),
            "none_found": tr("Подходящих видео в папке нет."),
            "other_type": lambda n: tr(" Перетащенных файлов другого типа: {n} — их программа пока не "
                                       "конвертирует.", n=n),
            "skipped": lambda n: tr("Не конвертированы: {n}", n=n),
            "columns": [tr("Взять"), tr("Файл"), tr("Станет"), tr("Было"), tr("Стало"), tr("Как"),
                        tr("Где лежит")],
            "mark_tip": tr("Отметка — новый файл встанет на место оригинала (или рядом с ним, если выбрано "
                           "«Оставить оригиналы»)"),
            "cmp_hint": tr("Выбери файл в списке — здесь будут кадр оригинала и нового файла рядом. "
                           "Двойной щелчок или пробел — сравнить крупно, с увеличением."),
            "open_new": tr("Открыть новый"),
            "all_done": tr("Все отмеченные файлы готовы."),
        }

    # ---------- карточка

    def _build_options(self, grid):
        self.mode_btns = {}
        self.prepared = None                       # (настройка, рядом ли) последней подготовки
        grid.addWidget(U.label(tr("Во что"), "strong"), 1, 0)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.preset_group = QButtonGroup(self)
        self.preset_btns = {}
        for key, (name, _text, _t) in convcore.PRESETS.items():
            b = QPushButton(tr(name), objectName="chip", checkable=True)
            self.preset_group.addButton(b)
            b.toggled.connect(lambda on, k=key: on and self._preset_picked(k))
            row.addWidget(b)
            self.preset_btns[key] = b
        row.addStretch()
        grid.addLayout(row, 1, 1)
        self.preset_text = WrapLabel("", "muted")
        grid.addWidget(self.preset_text, 2, 1)

        self.custom = QWidget()
        cg = QGridLayout(self.custom)
        cg.setContentsMargins(0, 2, 0, 2)
        cg.setHorizontalSpacing(10)
        cg.setVerticalSpacing(8)
        self.combos = {}
        layout = [("container", tr("Формат"), convcore.CONTAINERS, 0, 0),
                  ("video", tr("Видео"), convcore.VIDEO_CODECS, 0, 2),
                  ("quality", tr("Качество"), convcore.QUALITIES, 0, 4),
                  ("device", tr("Чем"), convcore.DEVICES, 0, 6),
                  ("size", tr("Размер кадра"), convcore.SIZES, 1, 0),
                  ("fps", tr("Кадры"), convcore.FPSES, 1, 2),
                  ("audio", tr("Звук"), convcore.AUDIO_CODECS, 1, 4)]
        for key, label, table, r, c in layout:
            cg.addWidget(U.label(label, "muted"), r, c)
            box = QComboBox(sizeAdjustPolicy=QComboBox.AdjustToContents)     # текст выбора виден целиком
            for value, name in table.items():
                box.addItem(tr(name[0] if isinstance(name, tuple) else name), value)
            box.currentIndexChanged.connect(lambda _i, k=key: self._custom_changed(k))
            cg.addWidget(box, r, c + 1)
            self.combos[key] = box
        cg.setColumnStretch(8, 1)
        self.combos["quality"].setToolTip(tr("«Само» — программа подбирает качество так, чтобы разницы не было "
                                             "видно, и проверяет каждый файл (VMAF). Остальное — без проверки."))
        self.combos["device"].setToolTip(tr("Видеокарта NVIDIA кодирует в разы быстрее; если её нет или "
                                            "кодек ей не по силам (VP9), кодирует процессор."))
        self.combos["audio"].setToolTip(tr("«Как есть» — звук копируется, если новый формат его хранит, "
                                           "иначе переводится в обычный для формата (AAC, в WebM — Opus)."))
        grid.addWidget(self.custom, 3, 1)

        self.hint = WrapLabel("", "warn")
        grid.addWidget(self.hint, 4, 1)

    def _build_action_extra(self, act):
        # Результат — галочкой в строке кнопок: отдельная строка карточки не влезала в окно минимального размера.
        self.keep_box = QCheckBox(tr("Оставить оригиналы"))
        self.keep_box.setToolTip(tr("Новые файлы лягут рядом с оригиналами, оригиналы останутся на месте. Без "
                                    "галочки оригинал уходит в Корзину, новый файл встаёт на его место."))
        self.keep_box.toggled.connect(self._keep_toggled)
        act.addWidget(self.keep_box)
        act.addSpacing(16)

    def _finish_build(self):
        self._loading = True
        custom = convcore.Target.from_dict(self.cfg.get("convert_custom"))
        for key, box in self.combos.items():
            box.setCurrentIndex(max(0, box.findData(getattr(custom, key))))
        self._loading = False
        self._fit_combos()
        self._restoring = True                     # выбор из настроек — как был, без «звук → рядом»
        preset = self.cfg.get("convert_preset", "keep")
        self.preset_btns[preset if preset in convcore.PRESETS else "keep"].setChecked(True)
        self.keep_box.setChecked(bool(self.cfg.get("convert_beside")))
        self._restoring = False
        self._update_hint()

    def preset(self):
        return next((k for k, b in self.preset_btns.items() if b.isChecked()), "keep")

    def beside(self):
        return self.keep_box.isChecked()

    def target(self):
        """Что получить: настройка набора или «Свой» из списков."""
        key = self.preset()
        if key == "custom":
            return convcore.Target.from_dict({k: b.currentData() for k, b in self.combos.items()})
        return replace(convcore.PRESETS[key][2])

    def _preset_picked(self, key):
        self.preset_text.setText(tr(convcore.PRESETS[key][1]))
        self.preset_text.setVisible(key != "custom")       # у «Своего» вместо пояснения — сами списки
        self.custom.setVisible(key == "custom")
        if key == "audio" and not self._restoring:
            self.keep_box.setChecked(True)                  # звук из видео — само видео не выбрасываем
        self.cfg["convert_preset"] = key
        self.settings_changed.emit()
        self._update_hint()

    def _keep_toggled(self, on):
        self.cfg["convert_beside"] = on
        self.settings_changed.emit()
        self._update_hint()
        self._update_hint()

    def _custom_changed(self, key):
        if getattr(self, "_loading", False):
            return
        self._fit_combos()
        self.cfg["convert_custom"] = convcore.Target.from_dict(
            {k: b.currentData() for k, b in self.combos.items()}).as_dict()
        self.settings_changed.emit()
        self._update_hint()

    def _fit_combos(self):
        """Списки — под выбранный формат: в WebM только VP9 и AV1 со звуком Opus, у «только звук» видео нет."""
        self._loading = True
        try:
            t = convcore.Target.from_dict({k: b.currentData() for k, b in self.combos.items()})
            name, _ext, vids, auds, _default = convcore.CONTAINERS[t.container]
            for key, allowed in (("video", ("copy",) + vids), ("audio", (("auto", "none") if not t.audio_only else ())
                                                                + tuple(a for a in convcore.AUDIO_CODECS
                                                                        if auds is None or a in auds))):
                box = self.combos[key]
                model = box.model()
                for i in range(box.count()):
                    model.item(i).setEnabled(box.itemData(i) in allowed)
                box.setCurrentIndex(box.findData(getattr(t, key)))
            video = not t.audio_only
            self.combos["video"].setEnabled(video)
            for key in ("quality", "size", "fps", "device"):
                self.combos[key].setEnabled(video and t.video != "copy")
        finally:
            self._loading = False

    def _update_hint(self):
        missing = convcore.missing_tools()
        hint = tr("Не хватает программ: {names}. Запусти tools/fetch_tools.py.",
                  names=", ".join(missing)) if missing else ""
        if not hint and self.ready and self.prepared and self.prepared != (self.target(), self.beside()):
            hint = tr("Настройки изменились — нажми «Подготовить файлы», чтобы применить их. Кнопка внизу "
                      "сделает то, что подготовлено.")
        self.hint.setText(hint)
        self.hint.setVisible(bool(hint))

    def _not_ready(self):
        missing = convcore.missing_tools()
        if missing:
            return tr("Не хватает программ: {names}. Запусти tools/fetch_tools.py.", names=", ".join(missing))
        return None

    def _job_runner(self, root, load):
        t, beside = self.target(), self.beside()
        self.prepared = (t, beside)
        self._update_hint()
        log.info("Конвертация: %s · %s · %s · нагрузка %s", root, t.as_dict(), "рядом" if beside else "замена",
                 load)
        return lambda progress, cancel, on_job: convcore.prepare(root, t, progress, cancel, load, on_job=on_job,
                                                                 beside=beside)

    def _finish(self, res):
        super()._finish(res)
        self._update_hint()

    # ---------- список и сравнение

    def row(self, j):
        return [os.path.basename(j.path), os.path.basename(compcore._final(j)), dupcore.human_size(j.size),
                dupcore.human_size(j.new_size), j.how, self.short_dir(j.path)]

    def _make_item(self, j):
        it = super()._make_item(j)
        it.setToolTip(2, compcore._final(j))       # длинное имя в столбце сокращается — целиком в подсказке
        it.setToolTip(5, j.detail or j.how)
        if j.warn:                                  # уже пересжимали — «Как» жёлтым, причина в подсказке
            it.setForeground(self.GOOD, QColor(self.colors["warn"]))
            it.setToolTip(5, (j.detail or j.how) + "\n" + j.note)
        return it

    def sizes_text(self, job):
        return tr("{old} {size_old} → {new} {size_new}", old=kind_of(job.path), new=kind_of(compcore._final(job)),
                  size_old=dupcore.human_size(job.size), size_new=dupcore.human_size(job.new_size))

    def how_text(self, job):
        how = job.detail or job.how
        if job.check == "streams":
            how += " · " + tr("видео и звук — те же байт в байт, метаданные перенесены")
        elif job.check == "vmaf":
            how += " · " + tr("VMAF {v}: на глаз разницы нет", v=score_text(job.score, 1))
        if job.note:
            how += " · " + job.note
        return how

    def big_line(self, j):
        return tr("{old} → {new}", old=os.path.basename(j.path), new=os.path.basename(compcore._final(j))) + \
            "  ·  " + self.sizes_text(j) + "  ·  " + self.how_text(j)

    # ---------- замена или «рядом»

    def _prepared_beside(self):
        return bool(self.prepared and self.prepared[1])

    def replace_args(self):
        return {"keep": self._prepared_beside()}

    def replacing_text(self, done, total):
        if self._prepared_beside():
            return tr("Кладу файлы рядом: {done} из {total}", done=num(done), total=num(total))
        return super().replacing_text(done, total)

    def replace_label(self, n, saved):
        if not n:
            return tr("Положить рядом") if self._prepared_beside() else tr("Заменить оригиналы")
        files = plural(n, "файл|файла|файлов", "file|files")
        if self._prepared_beside():
            return tr("Положить рядом {n} {files}", n=num(n), files=files)
        return tr("Заменить {n} {files}", n=num(n), files=files)

    def ask_text(self, ok):
        files = plural(len(ok), "файл|файла|файлов", "file|files")
        exts = ", ".join(sorted({os.path.splitext(compcore._final(j))[1].lower() for j in ok}))
        if self._prepared_beside():
            return tr("Положить {n} {files} рядом с оригиналами? Оригиналы останутся на месте.\n\n"
                      "Новые файлы: то же имя, расширение — {exts}, даты файлов — как у оригиналов.",
                      n=num(len(ok)), files=files, exts=exts)
        text = tr("Заменить {n} {files} новыми? Оригиналы уйдут в Корзину — вернуть можно оттуда.\n\n"
                  "Новые файлы встанут на их место: то же имя, расширение — {exts}, даты файлов — прежние.",
                  n=num(len(ok)), files=files, exts=exts)
        small = sum(j.resized for j in ok)
        if small:
            text += tr("\n\n⚠ У {n} {files} кадр уменьшен (например, 4K → 1080p): оригиналы в полном размере уйдут "
                       "в Корзину. Чтобы их сохранить, отметь «Оставить оригиналы» и подготовь заново.",
                       n=num(small), files=plural(small, "ролика|роликов|роликов", "video|videos"))
        return text

    def done_texts(self, done):
        if self._prepared_beside():
            text = tr("Готово файлов: {n}. Они лежат рядом с оригиналами.", n=num(len(done)))
        else:
            text = tr("Заменено файлов: {n}. Оригиналы — в Корзине.", n=num(len(done)))
        return text, text
