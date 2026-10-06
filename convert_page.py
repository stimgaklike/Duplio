"""Вкладка «Конвертация»: файл в другой формат — сейчас MOV → MP4 без пересжатия.

Устроена как «Сжатие» (CompressPage): подготовка копий, список «было → стало» с превью кадра, сравнение
крупно, замена оригиналов (в Корзину); отличаются тексты, строки списка и то, что новый файл получает
новое расширение. Логика — в convcore.py.
"""

import os

import convcore
import dupcore
import ui_util as U
from compress_page import CompressPage, WrapLabel
from i18n import num, plural, tr
from logs import log


def kind_of(path):
    return os.path.splitext(path)[1].lstrip(".").upper()


class ConvertPage(CompressPage):
    FOLDER_KEY = "convert_folder"
    WHAT = "Конвертация"
    SAVES = False               # размер почти тот же — «освободится» не пишем
    GOOD = 5                    # «Как» — зелёным: «без пересжатия»
    RIGHT = (3, 4)              # «Было», «Стало»
    WIDTHS = (84, 126, 126, 76, 76, 112)    # вместе с «Где лежит» — без прокрутки вбок
    SPLIT = [780, 440]                      # столбцов больше; кадру видео хватает и узкой панели

    def texts(self):
        return {
            "title": tr("Конвертация в другой формат"),
            "start": tr("Подготовить MP4"),
            "idle": tr("Выбери папку и нажми «Подготовить MP4»."),
            "empty": tr("Здесь появятся новые файлы: было → станет.\n\nСначала программа готовит и проверяет их "
                        "в своей папке — оригиналы не трогает, пока ты не нажмёшь «Заменить»."),
            "preparing": tr("Готовлю… Новые файлы появятся здесь сразу, по одному."),
            "step": lambda done, total: tr("Готовлю MP4 · {done} из {total}", done=done, total=total),
            "window": lambda pct: tr("{app} — конвертация, {pct}%", app=U.APP_TITLE, pct=pct),
            "nothing": lambda t: tr("Готово за {t}. Конвертировать нечего.", t=t),
            "nothing_why": tr("Ни один файл не удалось переложить в MP4 — причины по кнопке «Не конвертированы»."),
            "none_found": tr("Видео MOV в папке нет."),
            "other_type": lambda n: tr(" Перетащенных файлов другого типа: {n} — их программа пока не "
                                       "конвертирует.", n=n),
            "skipped": lambda n: tr("Не конвертированы: {n}", n=n),
            "columns": [tr("Заменить"), tr("Файл"), tr("Станет"), tr("Было"), tr("Стало"), tr("Как"),
                        tr("Где лежит")],
            "mark_tip": tr("Отметка — оригинал уйдёт в Корзину, рядом встанет новый файл"),
            "cmp_hint": tr("Выбери файл в списке — здесь будут кадр оригинала и нового файла рядом. "
                           "Двойной щелчок или пробел — сравнить крупно, с увеличением."),
            "open_new": tr("Открыть новый"),
            "all_done": tr("Все отмеченные файлы заменены новыми."),
        }

    # ---------- карточка

    def _build_options(self, grid):
        self.mode_btns = {}
        grid.addWidget(U.label(tr("Что"), "strong"), 1, 0)
        self.what = WrapLabel(tr("Видео MOV (iPhone, фотоаппараты) → MP4 без пересжатия: картинка и звук — те же "
                                 "байт в байт, дата съёмки, геометка и камера переносятся, даты файла остаются "
                                 "прежними. Имя то же, расширение — .mp4."), "muted")
        grid.addWidget(self.what, 1, 1)
        self.hint = WrapLabel("", "warn")
        grid.addWidget(self.hint, 2, 1)

    def _finish_build(self):
        missing = convcore.missing_tools()
        hint = tr("Не хватает программ: {names}. Запусти tools/fetch_tools.py.",
                  names=", ".join(missing)) if missing else ""
        self.hint.setText(hint)
        self.hint.setVisible(bool(hint))

    def _not_ready(self):
        missing = convcore.missing_tools()
        if missing:
            return tr("Не хватает программ: {names}. Запусти tools/fetch_tools.py.", names=", ".join(missing))
        return None

    def _job_runner(self, root, load):
        log.info("Конвертация: %s · нагрузка %s", root, load)
        return lambda progress, cancel, on_job: convcore.prepare(root, progress, cancel, load, on_job=on_job)

    # ---------- список и сравнение

    def row(self, j):
        return [os.path.basename(j.path), os.path.basename(j.target), dupcore.human_size(j.size),
                dupcore.human_size(j.new_size), j.how, self.short_dir(j.path)]

    def _make_item(self, j):
        it = super()._make_item(j)
        it.setToolTip(2, j.target)              # длинное имя в столбце сокращается — целиком в подсказке
        return it

    def sizes_text(self, job):
        return tr("{old} {size_old} → {new} {size_new}", old=kind_of(job.path), new=kind_of(job.target),
                  size_old=dupcore.human_size(job.size), size_new=dupcore.human_size(job.new_size))

    def how_text(self, job):
        how = job.how
        if job.check == "streams":
            how += " · " + tr("видео и звук — те же байт в байт, метаданные перенесены")
        if job.note:
            how += " · " + job.note
        return how

    def big_line(self, j):
        return tr("{old} → {new}", old=os.path.basename(j.path), new=os.path.basename(j.target)) + \
            "  ·  " + self.sizes_text(j) + "  ·  " + self.how_text(j)

    # ---------- замена

    def ask_text(self, ok):
        return tr("Заменить {n} {files} новыми? Оригиналы уйдут в Корзину — вернуть можно оттуда.\n\n"
                  "Новые файлы встанут рядом: имя то же, расширение другое (.mp4), даты файлов — прежние.",
                  n=num(len(ok)), files=plural(len(ok), "файл|файла|файлов", "file|files"))

    def done_texts(self, done):
        text = tr("Заменено файлов: {n}. Оригиналы — в Корзине.", n=num(len(done)))
        return text, text
