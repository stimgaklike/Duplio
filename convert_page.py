"""Вкладка «Конвертация»: видео и звук в другой формат — «Подобрать для каждого» (группы), наборы или свой выбор.

«Подобрать для каждого»: выбрал папку — программа смотрит заголовки файлов (convcore.survey) и показывает
группы с понятным действием на каждую; «Подготовить» — convcore.prepare_groups.

Устроена как «Сжатие» (CompressPage): подготовка копий, список «было → станет» с превью кадра, сравнение
крупно, замена оригиналов (в Корзину) или «положить рядом» (оригинал остаётся). Отличаются карточка
(наборы, «Свой» — выпадающие списки, результат), тексты и строки списка. Логика — в convcore.py.
"""

import os
import threading
from dataclasses import replace

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

import compcore
import convcore
import dupcore
import ui_util as U
from compress_page import CompressPage, WrapLabel, score_text
from i18n import num, plural, tr
from logs import log

GROUPS = "groups"           # «Подобрать для каждого» — не набор convcore.PRESETS, а группы


def kind_of(path):
    return os.path.splitext(path)[1].lstrip(".").upper()


class SurveyBridge(QObject):
    progress = Signal(int, int)
    done = Signal(object)


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
        self.prepared = None                       # с какими настройками подготовлено (_settings)
        self.survey, self.survey_root, self.surveying = None, None, False    # группы (convcore.survey)
        grid.addWidget(U.label(tr("Во что"), "strong"), 1, 0)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.preset_group = QButtonGroup(self)
        self.preset_btns = {}
        chips = [(GROUPS, tr("Подобрать для каждого"))] + [(k, tr(v[0])) for k, v in convcore.PRESETS.items()]
        for key, name in chips:
            b = QPushButton(name, objectName="chip", checkable=True)
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
        preset = self.cfg.get("convert_preset", GROUPS)
        self.preset_btns[preset if preset in self.preset_btns else GROUPS].setChecked(True)
        self.keep_box.setChecked(bool(self.cfg.get("convert_beside")))
        self._restoring = False
        self._update_hint()

    def preset(self):
        return next((k for k, b in self.preset_btns.items() if b.isChecked()), GROUPS)

    def beside(self):
        return self.keep_box.isChecked()

    def target(self):
        """Что получить: настройка набора или «Свой» из списков."""
        key = self.preset()
        if key == "custom":
            return convcore.Target.from_dict({k: b.currentData() for k, b in self.combos.items()})
        return replace(convcore.PRESETS[key][2])

    def _preset_picked(self, key):
        self.preset_text.setText(tr(convcore.PRESETS[key][1]) if key != GROUPS else
                                 tr("Программа посмотрит на твои видео, разложит их по группам и для каждой "
                                    "предложит, что сделать. Ты сможешь выбрать другое."))
        self.preset_text.setVisible(key != "custom")       # у «Своего» вместо пояснения — сами списки
        self.custom.setVisible(key == "custom")
        if key == "audio" and not self._restoring:
            self.keep_box.setChecked(True)                  # звук из видео — само видео не выбрасываем
        self.cfg["convert_preset"] = key
        self.settings_changed.emit()
        self._show_groups(key == GROUPS and self.survey is not None and not self.ready)
        self._update_start()
        self._update_hint()

    def _keep_toggled(self, on):
        self.cfg["convert_beside"] = on
        self.settings_changed.emit()
        if getattr(self, "survey_bridge", None) is not None:
            self._plan_text()
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
        if not hint and self.ready and self.prepared and self.prepared != self._settings():
            hint = tr("Настройки изменились — нажми «Подготовить файлы», чтобы применить их. Кнопка внизу "
                      "сделает то, что подготовлено.")
        self.hint.setText(hint)
        self.hint.setVisible(bool(hint))

    def _not_ready(self):
        missing = convcore.missing_tools()
        if missing:
            return tr("Не хватает программ: {names}. Запусти tools/fetch_tools.py.", names=", ".join(missing))
        if self.preset() == GROUPS and self._surveyed() and not self._to_do():
            return tr("Сейчас у всех групп выбрано «Не трогать» — выбери, что сделать, хотя бы для одной.")
        return None

    def _settings(self):
        """С какими настройками готовим — чтобы заметить, что их поменяли после подготовки."""
        if self.preset() == GROUPS:
            return GROUPS, tuple((g.kind, g.action) for g in (self.survey.groups if self.survey else [])), \
                self.beside()
        return self.target(), self.beside()

    # ---------- «Подобрать для каждого»: группы

    def _build_rest(self, root, card, cl):
        super()._build_rest(root, card, cl)
        self.survey_bridge = SurveyBridge()
        self.survey_bridge.progress.connect(self._survey_progress)
        self.survey_bridge.done.connect(self._survey_done)
        page, lay = U.card(margins=(16, 14, 16, 14), spacing=10)
        self.groups_scroll = QScrollArea(widgetResizable=True)
        self.groups_scroll.setFrameShape(QFrame.NoFrame)
        self.groups_body = QWidget()
        self.groups_lay = QVBoxLayout(self.groups_body)
        self.groups_lay.setContentsMargins(0, 0, 0, 0)
        self.groups_lay.setSpacing(14)
        self.groups_scroll.setWidget(self.groups_body)
        lay.addWidget(self.groups_scroll, 1)
        self.stack.addWidget(page)                  # 2 — группы (0 — заглушка, 1 — готовые файлы)
        self.groups_page = page
        self.btn_groups = QPushButton(tr("Показать группы"), objectName="link")
        self.btn_groups.setToolTip(tr("Вернуться к группам и поменять, что с ними сделать"))
        self.btn_groups.clicked.connect(lambda: self._show_groups(True))
        self.btn_groups.hide()
        self.step_row.insertWidget(1, self.btn_groups)      # рядом с «Готово за …» — вернуться к группам
        self._update_start()

    def _root(self):
        if self.drop_files:
            return tuple(p for p in self.drop_files if os.path.exists(p))
        return self.folder.text().strip().strip('"')

    def _surveyed(self):
        return self.survey is not None and self.survey_root == self._root()

    def _to_do(self):
        return [g for g in self.survey.groups if g.action in convcore.ACTION_TARGETS] if self.survey else []

    def _update_start(self):
        look = self.preset() == GROUPS and not self._surveyed()
        self.btn_start.setText(tr("Посмотреть файлы") if look else self.T["start"])

    def use_folder(self, path):
        super().use_folder(path)
        self._forget_survey()
        if self.preset() == GROUPS and not self.busy:
            self.look()                             # папку выбрали — сразу смотрим, что там (только чтение)

    def use_files(self, paths):
        super().use_files(paths)
        if getattr(self, "survey_bridge", None) is None:
            return                                  # ещё строится окно
        self._forget_survey()
        if paths and self.preset() == GROUPS and not self.busy:
            self.look()

    def _forget_survey(self):
        self.survey, self.survey_root = None, None
        if not self.ready:
            self.stack.setCurrentIndex(0)
        self.btn_groups.hide()
        self._show_groups(False)
        self._update_start()

    def start(self):
        if self.preset() == GROUPS and not self._surveyed():
            self.look()
            return
        super().start()

    def look(self):
        """Посмотреть файлы в папке (или перетащенные) и разложить по группам — в фоне, только заголовки."""
        if self.busy or self.surveying:
            return
        root = self._root()
        if not root or (isinstance(root, str) and not os.path.isdir(root)):
            U.warn(self, tr("Такой папки нет. Нажми «Выбрать…» и укажи папку."))
            return
        self.surveying = True
        self.btn_start.setEnabled(False)
        U.why(self.btn_start, tr("Подожди: смотрю, какие тут файлы."))
        self.step_text.setText(tr("Смотрю, какие тут видео…"))
        self.status.setText("")
        self.bar.setRange(0, 0)
        log.info("Конвертация: смотрю %s", root)
        threading.Thread(target=lambda: self.survey_bridge.done.emit(
            convcore.survey(list(root) if isinstance(root, tuple) else root,
                            lambda d, t: self.survey_bridge.progress.emit(d, t))), daemon=True).start()
        self._looking_root = root

    def _survey_progress(self, done, total):
        if total:
            self.bar.setRange(0, total)
            self.bar.setValue(done)
            self.step_text.setText(tr("Смотрю видео: {done} из {total}", done=num(done), total=num(total)))

    def _survey_done(self, res):
        self.surveying = False
        self.btn_start.setEnabled(True)
        U.why(self.btn_start, "")
        self.bar.setRange(0, 1000)
        self.bar.setValue(0)
        self.survey, self.survey_root = res, self._looking_root
        n = sum(len(g.files) for g in res.groups)
        log.info("Конвертация: групп %d, видео %d, не прочитались %d", len(res.groups), n, len(res.unreadable))
        if not n:
            self.step_text.setText(tr("Видео тут нет."))
            self.empty.setText(self.T["none_found"])
            self.stack.setCurrentIndex(0)
        else:
            self.step_text.setText(tr("Нашёл {n} {videos}. Проверь, что сделать с каждой группой, и нажми "
                                      "«Подготовить файлы».", n=num(n),
                                      videos=plural(n, "видео|видео|видео", "video|videos")))
            self._fill_groups()
            self._show_groups(True)
        extra = []
        if res.unreadable:
            extra.append(tr("Не открылись: {n}.", n=num(len(res.unreadable))))
        if res.cloud_skipped:
            extra.append(tr("Лежат только в облаке или на телефоне — пропущены: {n}.", n=num(res.cloud_skipped)))
        self.status.setText(" ".join(extra))
        self._update_start()

    def _fill_groups(self):
        while self.groups_lay.count():
            item = self.groups_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.group_boxes = {}
        for g in self.survey.groups:
            _order, name, why_text, _default, actions = convcore.KINDS[g.kind]
            box = QWidget()
            v = QVBoxLayout(box)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(4)
            top = QHBoxLayout()
            title = U.label(tr(name), "strong")
            title.setToolTip("\n".join(os.path.basename(f.path) for f in g.files[:30]) +
                             ("\n…" if len(g.files) > 30 else ""))
            top.addWidget(title)
            count = U.label(tr("{n} {videos} · {size}", n=num(len(g.files)),
                               videos=plural(len(g.files), "видео|видео|видео", "video|videos"),
                               size=dupcore.human_size(g.size)), "muted")
            top.addWidget(count)
            top.addStretch()
            choose = QComboBox(sizeAdjustPolicy=QComboBox.AdjustToContents)
            for a in actions:
                choose.addItem(tr(convcore.ACTIONS[a][0]), a)
            choose.setCurrentIndex(choose.findData(g.action))
            choose.currentIndexChanged.connect(lambda _i, g=g, c=choose: self._group_action(g, c.currentData()))
            if len(actions) == 1:
                choose.setEnabled(False)
                U.why(choose, tr("Эти файлы лучше не трогать — выбрать другое нельзя."))
            top.addWidget(choose)
            v.addLayout(top)
            v.addWidget(WrapLabel(tr(why_text), "muted"))
            result = WrapLabel("", "strong")
            v.addWidget(result)
            self.group_boxes[g.kind] = (choose, result)
            self.groups_lay.addWidget(box)
            self._group_action(g, g.action)
        self.groups_lay.addStretch()

    def _group_action(self, g, action):
        g.action = action
        _choose, result = self.group_boxes[g.kind]
        result.setText("→ " + tr(convcore.ACTIONS[action][1]))
        self._update_hint()
        self._plan_text()

    def _plan_text(self):
        """Справа, пока видны группы: что будет со всеми файлами — коротко и до нажатия."""
        if self.stack.currentIndex() != 2 or not self.survey:
            return
        by = {}
        for g in self.survey.groups:
            n, size = by.get(g.action, (0, 0))
            by[g.action] = (n + len(g.files), size + g.size)
        lines = []
        for action in convcore.ACTIONS:
            if action in by:
                n, size = by[action]
                lines.append(tr("• {what}: {n} {videos} ({size})", what=tr(convcore.ACTIONS[action][0]), n=num(n),
                                videos=plural(n, "видео|видео|видео", "video|videos"), size=dupcore.human_size(size)))
        lines.append("")
        if not self._to_do():
            lines.append(tr("Сейчас у всех групп выбрано «Не трогать» — выбери, что сделать, хотя бы для одной."))
        else:
            lines.append(tr("Сначала программа всё подготовит и покажет тебе — с файлами ничего не случится, пока "
                            "ты не нажмёшь кнопку внизу."))
            if self.beside():
                lines.append(tr("Новые файлы лягут рядом, оригиналы останутся."))
            else:
                lines.append(tr("Новые файлы встанут на место оригиналов, а оригиналы уйдут в Корзину — вернуть "
                                "можно оттуда. Звук (MP3) всегда кладётся рядом с видео."))
        self.cmp_hint.setText("\n".join(lines))

    def _show_groups(self, on):
        if on and self.survey is not None and self.survey.groups:
            self.stack.setCurrentIndex(2)
            self.btn_groups.hide()
            self.show_job(None)
        elif self.ready:
            self.stack.setCurrentIndex(1)
            self.btn_groups.setVisible(self.preset() == GROUPS and self.survey is not None and not self.busy)
        groups = self.stack.currentIndex() == 2
        # на шаге групп отмечать и заменять ещё нечего — эти кнопки только путают
        for b in (self.btn_mark_all, self.btn_unmark, self.btn_replace):
            b.setVisible(not groups)
        self.cmp_title.setText(tr("Что будет") if groups else tr("Было → стало"))
        if groups:
            self._plan_text()
        else:
            self.cmp_hint.setText(self.T["cmp_hint"])

    def _job_runner(self, root, load):
        if self.preset() == GROUPS and self._surveyed():
            groups, beside = list(self.survey.groups), self.beside()
            self._show_groups(False)                # готовим — внизу снова кнопки отметок и замены
            self.prepared = self._settings()
            self._update_hint()
            log.info("Конвертация по группам: %s · %s", ", ".join(f"{g.kind}:{len(g.files)}→{g.action}"
                                                                  for g in groups), "рядом" if beside else "замена")
            return lambda progress, cancel, on_job: convcore.prepare_groups(groups, beside, progress, cancel, load,
                                                                            on_job=on_job)
        t, beside = self.target(), self.beside()
        self.prepared = self._settings()
        self._update_hint()
        log.info("Конвертация: %s · %s · %s · нагрузка %s", root, t.as_dict(), "рядом" if beside else "замена",
                 load)
        return lambda progress, cancel, on_job: convcore.prepare(root, t, progress, cancel, load, on_job=on_job,
                                                                 beside=beside)

    def _finish(self, res):
        super()._finish(res)
        self._show_groups(False)
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
        jobs = self._marked_jobs() or self.ready
        return bool(jobs) and all(j.keep for j in jobs)

    def replacing_text(self, done, total):
        if self._prepared_beside():
            return tr("Кладу файлы рядом: {done} из {total}", done=num(done), total=num(total))
        return super().replacing_text(done, total)

    def replace_label(self, n, saved):
        if not n:
            return tr("Положить рядом") if self._prepared_beside() else tr("Заменить оригиналы")
        files = plural(n, "файл|файла|файлов", "file|files")
        keep = [j.keep for j in self._marked_jobs()]
        if all(keep):
            return tr("Положить рядом {n} {files}", n=num(n), files=files)
        if any(keep):
            return tr("Готово: применить к {n} {files}", n=num(n), files=plural(n, "файлу|файлам|файлам",
                                                                                 "file|files"))
        return tr("Заменить {n} {files}", n=num(n), files=files)

    def ask_text(self, ok):
        near, swap = [j for j in ok if j.keep], [j for j in ok if not j.keep]
        if near and swap:
            text = tr("Что будет:\n• {swap} {swap_files} встанут на место оригиналов — оригиналы уйдут в Корзину, "
                      "вернуть можно оттуда;\n• {near} {near_files} лягут рядом с оригиналами — оригиналы "
                      "останутся.", swap=num(len(swap)), swap_files=plural(len(swap), "новый файл|новых файла|новых "
                                                                            "файлов", "new file|new files"),
                      near=num(len(near)), near_files=plural(len(near), "новый файл|новых файла|новых файлов",
                                                             "new file|new files"))
            return text + self._resize_warning(swap)
        files = plural(len(ok), "файл|файла|файлов", "file|files")
        exts = ", ".join(sorted({os.path.splitext(compcore._final(j))[1].lower() for j in ok}))
        if not swap:
            return tr("Положить {n} {files} рядом с оригиналами? Оригиналы останутся на месте.\n\n"
                      "Новые файлы: то же имя, расширение — {exts}, даты файлов — как у оригиналов.",
                      n=num(len(ok)), files=files, exts=exts)
        text = tr("Заменить {n} {files} новыми? Оригиналы уйдут в Корзину — вернуть можно оттуда.\n\n"
                  "Новые файлы встанут на их место: то же имя, расширение — {exts}, даты файлов — прежние.",
                  n=num(len(ok)), files=files, exts=exts)
        return text + self._resize_warning(ok)

    def _resize_warning(self, swap):
        small = sum(j.resized for j in swap)
        text = ""
        if small:
            text += tr("\n\n⚠ У {n} {files} кадр уменьшен (например, 4K → 1080p): оригиналы в полном размере уйдут "
                       "в Корзину. Чтобы их сохранить, отметь «Оставить оригиналы» и подготовь заново.",
                       n=num(small), files=plural(small, "ролика|роликов|роликов", "video|videos"))
        return text

    def done_texts(self, done):
        if done and all(j.keep for j in done):
            text = tr("Готово файлов: {n}. Они лежат рядом с оригиналами.", n=num(len(done)))
        else:
            text = tr("Заменено файлов: {n}. Оригиналы — в Корзине.", n=num(len(done)))
        return text, text
