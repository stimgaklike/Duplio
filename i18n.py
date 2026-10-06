"""Язык интерфейса: русский (исходные строки) и английский.

tr("Русский шаблон {n}", n=5) — строка на текущем языке. Ключ перевода — сам русский шаблон,
поэтому код читается по-русски, а английский лежит в словаре EN ниже (тест следит, чтобы ни одна
строка не осталась без перевода).
"""

LANGS = {"auto": "Как в Windows", "ru": "Русский", "en": "English"}
LANG = "ru"


def system_lang():
    try:
        import ctypes
        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF
        return "ru" if lang_id in (0x19, 0x22, 0x23, 0x3F) else "en"   # русский, украинский, белорусский, казахский
    except Exception:
        return "ru"


def set_lang(choice):
    global LANG
    LANG = system_lang() if choice in (None, "", "auto") else choice


def tr(text, **kw):
    t = EN.get(text, text) if LANG == "en" else text
    return t.format(**kw) if kw else t


def plural(n, ru, en):
    """plural(5, "файл|файла|файлов", "file|files") → «файлов» / «files»."""
    if LANG == "en":
        one, many = en.split("|")
        return one if n == 1 else many
    one, few, many = ru.split("|")
    n = abs(n) % 100
    if 11 <= n <= 14:
        return many
    return one if n % 10 == 1 else few if 2 <= n % 10 <= 4 else many


def num(n):
    return f"{n:,}".replace(",", " " if LANG == "ru" else ",")


def decimal(x):
    s = f"{x:.1f}"
    return s.replace(".", ",") if LANG == "ru" else s


def date_format():
    return "%d.%m.%Y %H:%M" if LANG == "ru" else "%Y-%m-%d %H:%M"


EN = {
    # ---- общее
    "Дубликаты": "Duplicates",
    "Сжатие": "Compression",
    "Настройки": "Settings",
    "Да": "Yes",
    "Отмена": "Cancel",
    "Понятно": "OK",
    "Открыть": "Open",
    "Показать в папке": "Show in folder",
    "Выход": "Exit",
    "Остановить поиск": "Stop scan",
    # ---- единицы
    "Б": "B", "КБ": "KB", "МБ": "MB", "ГБ": "GB", "ТБ": "TB",
    "{s} с": "{s} s",
    "{m} мин {s} с": "{m} min {s} s",
    "{m} мин": "{m} min",
    "{h} ч {m} мин": "{h} h {m} min",
    # ---- типы файлов и правила
    "Фото": "Photos",
    "Видео": "Videos",
    "Музыка": "Music",
    "Документы и книги": "Documents and books",
    "Архивы и образы": "Archives and disk images",
    "Остальные файлы": "Other files",
    "фото": "photos",
    "видео": "videos",
    "аудиофайлов": "audio files",
    "документов": "documents",
    "архивов": "archives",
    "файлов": "files",
    "самый старый файл": "the oldest file",
    "самый новый файл": "the newest file",
    "файл с самым коротким путём": "the file with the shortest path",
    # ---- шаги поиска
    "Ищу файлы": "Looking for files",
    "Сравниваю начала и концы файлов": "Comparing file beginnings and ends",
    "Сверяю содержимое целиком": "Comparing full contents",
    # ---- проверки перед удалением
    "в группе отмечены все копии — хоть одну надо оставить":
        "all copies in the group are marked — at least one must stay",
    "оставляемый файл пропал или изменился — группу пропускаю":
        "the file to keep is gone or changed — skipping the group",
    "файл пропал или изменился после поиска": "the file is gone or changed since the scan",
    # ---- вкладка «Дубликаты»
    "Поиск дубликатов": "Find duplicates",
    "Находит одинаковые файлы во всех вложенных папках и убирает лишние копии в Корзину.":
        "Finds identical files in all subfolders and moves the extra copies to the Recycle Bin.",
    "Папка": "Folder",
    "Например, E:\\ или C:\\Users\\Имя\\Pictures": "For example, E:\\ or C:\\Users\\Name\\Pictures",
    "Выбрать…": "Browse…",
    "Что искать": "Look for",
    "Изменить": "Change",
    "Остановить": "Stop",
    "Начать поиск": "Start scan",
    "Выбери папку и нажми «Начать поиск».": "Choose a folder and press “Start scan”.",
    "Здесь появятся найденные копии.": "Duplicates will appear here.",
    "Удалить": "Delete",
    "Файл": "File",
    "Размер": "Size",
    "Изменён": "Modified",
    "Где лежит": "Location",
    "Сравнение": "Comparison",
    "Выбери группу или файл в списке — здесь появятся все копии рядом. "
    "Двойной щелчок по превью или пробел — быстрый просмотр.":
        "Pick a group or a file in the list — all its copies will appear here side by side. "
        "Double-click a preview or press Space for a quick look.",
    "В каждой группе оставлять": "In each group keep",
    "Снять все отметки": "Clear all marks",
    "Удалить в Корзину": "Move to Recycle Bin",
    "Нагрузка на компьютер: {name}": "System load: {name}",
    "бережная": "gentle",
    "обычная": "normal",
    "быстрая (для SSD)": "fast (for SSD)",
    "Осторожно с «остальными файлами»: в папках программ и игр одинаковые файлы нужны на своих местах. "
    "Удаляй только то, что узнаёшь. Системные файлы Windows программа пропускает сама.":
        "Careful with “other files”: identical files inside program and game folders are needed where they are. "
        "Delete only what you recognize. Windows system files are skipped automatically.",
    "Отметь хотя бы один тип файлов.": "Select at least one file type.",
    "Где искать дубликаты": "Where to look for duplicates",
    "Такой папки нет. Нажми «Выбрать…» и укажи папку.": "This folder doesn't exist. Press “Browse…” and pick a folder.",
    "Отметь хотя бы один тип файлов: фото, видео, музыку…": "Select at least one file type: photos, videos, music…",
    "Ищу… Найденные копии появятся здесь сразу, не дожидаясь конца поиска.":
        "Scanning… Duplicates will show up here as soon as they're found.",
    "Начинаю…": "Starting…",
    "прошло {t}": "{t} elapsed",
    "Шаг {step} из {steps} · {title}": "Step {step} of {steps} · {title}",
    "{app} — шаг {step} из {steps}{pct}": "{app} — step {step} of {steps}{pct}",
    "Найдено файлов: {n}. Сколько осталось, станет ясно на следующих шагах.":
        "Files found: {n}. Time left will be known at the next steps.",
    "На этом шаге проверять нечего.": "Nothing to check at this step.",
    "{done} из {total}": "{done} of {total}",
    "{done} из {total} файлов": "{done} of {total} files",
    "{rate}/с": "{rate}/s",
    "осталось ≈ {t}": "≈ {t} left",
    "считаю, сколько осталось…": "estimating time left…",
    "потом ещё шаг {n}": "then step {n}",
    "Останавливаю…": "Stopping…",
    "Поиск прервался из-за ошибки:\n{text}": "The scan stopped because of an error:\n{text}",
    "Проверено файлов: {n} ({size}).": "Files checked: {n} ({size}).",
    " Пропущено файлов, которые лежат только в облаке или на телефоне: {n} — их пришлось бы скачивать.":
        " Skipped files that exist only in the cloud or on a phone: {n} — they would have to be downloaded.",
    "Поиск остановлен.": "Scan stopped.",
    " Показаны копии, найденные до остановки.": " Showing duplicates found before stopping.",
    "Прошло {t}.": "{t} elapsed.",
    "Поиск остановлен раньше, чем нашлись копии.": "The scan was stopped before any duplicates were found.",
    "Готово за {t}. Копий нет.": "Done in {t}. No duplicates.",
    "Точных копий не нашлось 🎉": "No exact duplicates found 🎉",
    "Готово за {t}. Лишние копии отмечены — проверь и удали.":
        "Done in {t}. Extra copies are marked — review and delete them.",
    "Не прочитались: {n}": "Couldn't read: {n}",
    "Это последняя оставляемая копия в группе — хоть одну надо оставить.":
        "This is the last copy kept in the group — at least one must stay.",
    "(в самой папке)": "(in the folder itself)",
    "Группа {n}  ·  {count} одинаковых {kind}  ·  {size} каждая":
        "Group {n}  ·  {count} identical {kind}  ·  {size} each",
    "Отметка — файл уйдёт в Корзину": "Checked — the file goes to the Recycle Bin",
    "Удалить {n} {files} в Корзину  ·  освободится {size}": "Move {n} {files} to Recycle Bin  ·  frees {size}",
    "  ·  поиск продолжается…": "  ·  scan in progress…",
    "Групп: {groups}  ·  лишних копий: {extra}  ·  отмечено: {marked}":
        "Groups: {groups}  ·  extra copies: {extra}  ·  marked: {marked}",
    "Быстрый просмотр  (пробел)": "Quick look  (Space)",
    "Оставить только этот, остальные удалить": "Keep only this one, delete the rest",
    "{n} {copies} · остаётся {kept}": "{n} {copies} · {kept} kept",
    "Эти файлы или папки не удалось прочитать, они не участвовали в поиске:\n\n":
        "These files or folders couldn't be read and were not scanned:\n\n",
    "\n…и ещё {n}": "\n…and {n} more",
    "…и ещё {n}": "…and {n} more",
    "Ничего не отмечено.": "Nothing is marked.",
    "Удалять нечего:\n\n": "Nothing to delete:\n\n",
    "Отправить в Корзину {n} {files}, {size}?\n\n"
    "В каждой группе останется хотя бы одна копия. Вернуть можно из Корзины.":
        "Move {n} {files} ({size}) to the Recycle Bin?\n\n"
        "At least one copy stays in every group. You can restore them from the Recycle Bin.",
    "\n\nПропущу:\n": "\n\nWill skip:\n",
    "Все отмеченные копии в Корзине.": "All marked copies are in the Recycle Bin.",
    "В Корзину отправлено: {n} ({size}).": "Moved to the Recycle Bin: {n} ({size}).",
    "\n\nНе удалось удалить {n}:\n": "\n\nCouldn't delete {n}:\n",
    "Отправлено в Корзину: {n} ({size}). Вернуть можно из Корзины.":
        "Moved to the Recycle Bin: {n} ({size}). You can restore them from there.",
    # карточка и быстрый просмотр
    "Двойной щелчок — быстрый просмотр": "Double-click for a quick look",
    "Оставить": "Keep",
    "Быстрый просмотр": "Quick look",
    "← Предыдущая": "← Previous",
    "Следующая →": "Next →",
    "Открыть в программе": "Open in app",
    "копия {i} из {n}": "copy {i} of {n}",
    "Будет удалена": "Will be deleted",
    "Остаётся": "Kept",
    "Оставить эту копию": "Keep this copy",
    "Удалить эту копию": "Delete this copy",
    "🎬\n\nВидео — «Открыть в программе»": "🎬\n\nVideo — “Open in app”",
    "Превью недоступно": "No preview",
    # ---- вкладка «Сжатие»
    "Сжатие фото и видео": "Photo and video compression",
    "Строго без потерь": "Strictly lossless",
    "Без видимых потерь": "Visually lossless",
    "Фото JPEG и PNG пересобираются без изменения пикселей — каждый файл сверяется байт в байт. "
    "Экономия: обычно 5–20 %.":
        "JPEG and PNG photos are rebuilt without changing a single pixel — every file is checked byte for byte. "
        "Savings: usually 5–20%.",
    "Фото JPEG — качество 85–90, видео — AV1, PNG — без потерь. На глаз разницы нет, и это "
    "проверяется числом. Экономия: обычно 30–70 %.":
        "JPEG photos at quality 85–90, videos in AV1, PNG losslessly. You can't see the difference, and that "
        "is checked with a number. Savings: usually 30–70%.",
    "Здесь появятся сжатые копии: было → стало.\n\nПрограмма уменьшает файлы, не меняя их тип. "
    "Сначала готовит и проверяет сжатые копии — оригиналы не трогает, пока ты не нажмёшь «Заменить».":
        "Compressed copies will appear here: before → after.\n\nThe app makes files smaller without changing their "
        "type. It first prepares and checks compressed copies — originals stay untouched until you press “Replace”.",
    "Режим": "Mode",
    "Что сжимать": "Compress",
    "Подготовить сжатые копии": "Prepare compressed copies",
    "Выбери папку и режим и нажми «Подготовить сжатые копии».":
        "Choose a folder and a mode, then press “Prepare compressed copies”.",
    "Фото: JPEG и PNG. Видео — только «без видимых потерь».": "Photos: JPEG and PNG. Videos — only “visually lossless”.",
    "Фото: JPEG и PNG; видео — в формат AV1 (MP4, MOV, MKV, WebM).":
        "Photos: JPEG and PNG; videos — to AV1 (MP4, MOV, MKV, WebM).",
    "Фото: JPEG и PNG.": "Photos: JPEG and PNG.",
    "AV1 Windows 11 показывает сразу, Windows 10 — после бесплатного расширения «AV1 Video Extension» из "
    "Microsoft Store.":
        "Windows 11 plays AV1 right away; Windows 10 needs the free “AV1 Video Extension” from the Microsoft Store.",
    "Видео строго без потерь не сжимается — только в режиме «Без видимых потерь»":
        "Videos can't be compressed strictly losslessly — only in “Visually lossless” mode",
    "Отметь, что сжимать.": "Choose what to compress.",
    "Отметь, что сжимать: фото или видео.": "Choose what to compress: photos or videos.",
    "Не хватает программ: {names}. Запусти tools/fetch_tools.py.": "Missing tools: {names}. Run tools/fetch_tools.py.",
    "Подготовленные копии ещё не заменили оригиналы. Начать заново? Они пропадут.":
        "The prepared copies haven't replaced the originals yet. Start over? They will be lost.",
    "Начать заново": "Start over",
    "Готовлю… Сжатые копии появятся здесь сразу, по одной.": "Preparing… Compressed copies will appear here one by one.",
    "Ищу фото и видео…": "Looking for photos and videos…",
    "Найдено файлов: {n}.": "Files found: {n}.",
    "Готовлю сжатые копии · {done} из {total}": "Preparing compressed copies · {done} of {total}",
    "{app} — сжатие, {pct}%": "{app} — compressing, {pct}%",
    "освободится уже {now}, по всей папке ≈ {all}": "{now} to free so far, ≈ {all} for the whole folder",
    "сейчас: {name}": "now: {name}",
    "Подготовка прервалась из-за ошибки:\n{text}": "Preparation stopped because of an error:\n{text}",
    "Место на диске кончается — подготовку остановил.": "The disk is running out of space — preparation stopped.",
    "Замени готовые файлы — место освободится, и можно продолжить.":
        "Replace the ready files — that frees space, and you can continue.",
    "Подготовка остановлена.": "Preparation stopped.",
    " Готовые копии — в списке.": " Ready copies are in the list.",
    "Готово за {t}. Сжимать нечего.": "Done in {t}. Nothing to compress.",
    "Ни один файл не уменьшился заметно — они уже сжаты хорошо.":
        "No file got noticeably smaller — they are already well compressed.",
    "Подходящих фото и видео в папке нет.": "There are no suitable photos or videos in the folder.",
    "Готово за {t}. Проверь «было → стало» и нажми «Заменить».": "Done in {t}. Check “before → after” and press “Replace”.",
    "Не сжаты: {n}": "Not compressed: {n}",
    "Заменить": "Replace",
    "Было": "Before",
    "Стало": "After",
    "Меньше на": "Saved",
    "Проверка": "Check",
    "байт в байт": "byte for byte",
    "SSIM {v}": "SSIM {v}",
    "Отметка — оригинал уйдёт в Корзину, на его место встанет сжатый файл":
        "Checked — the original goes to the Recycle Bin and the compressed file takes its place",
    "Было → стало": "Before → after",
    "Выбери файл в списке — здесь будут оригинал и сжатая копия рядом. Двойной щелчок или пробел — сравнить "
    "крупно, с увеличением.":
        "Pick a file in the list — the original and the compressed copy will appear here side by side. "
        "Double-click or press Space to compare up close, with zoom.",
    "Сравнить крупно": "Compare up close",
    "Сравнить крупно  (пробел)": "Compare up close  (Space)",
    "Открыть оригинал": "Open original",
    "Открыть сжатый": "Open compressed",
    "{old} → {new}, меньше на {pct} ({saved})": "{old} → {new}, {pct} smaller ({saved})",
    "пиксели совпадают байт в байт — изображение то же самое":
        "pixels match byte for byte — the image is exactly the same",
    "SSIM {v}: на глаз разницы нет": "SSIM {v}: no visible difference",
    "Загружаю…": "Loading…",
    "Отметить все": "Mark all",
    "Заменить оригиналы": "Replace originals",
    "Заменить {n} {files}  ·  освободится {size}": "Replace {n} {files}  ·  frees {size}",
    "Готово к замене: {ready}  ·  отмечено: {n}  ·  было {old} → станет {new}":
        "Ready to replace: {ready}  ·  marked: {n}  ·  {old} now → {new} after",
    "  ·  подготовка продолжается…": "  ·  still preparing…",
    "Эти файлы оставлены как есть:\n\n": "These files were left as they are:\n\n",
    "Эти файлы или папки не удалось прочитать:\n\n": "These files or folders could not be read:\n\n",
    "Заменяю файлы…": "Replacing files…",
    "Заменять нечего:\n\n": "Nothing to replace:\n\n",
    "Заменить {n} {files} сжатыми копиями? Освободится {size}.\n\nОригиналы уйдут в Корзину — вернуть можно "
    "оттуда. Имена и даты файлов останутся прежними.":
        "Replace {n} {files} with compressed copies? This frees {size}.\n\nThe originals go to the Recycle Bin — "
        "you can restore them from there. File names and dates stay the same.",
    "\n\n⚠ На дисках {drives} Корзины нет (флешка, карта памяти или сетевой диск): оригиналы оттуда удалятся "
    "НАВСЕГДА, вернуть их будет нельзя.":
        "\n\n⚠ Drives {drives} have no Recycle Bin (USB stick, memory card or network drive): the originals there "
        "will be deleted PERMANENTLY and can't be restored.",
    "Заменить, оригиналы навсегда": "Replace, delete originals permanently",
    "Все отмеченные файлы заменены сжатыми.": "All marked files were replaced with compressed ones.",
    "Заменено файлов: {n}. Освободилось {size}. Оригиналы — в Корзине.":
        "Files replaced: {n}. Freed {size}. The originals are in the Recycle Bin.",
    "\n\nНе заменены {n}:\n": "\n\nNot replaced {n}:\n",
    "Заменено файлов: {n}, освободилось {size}. Оригиналы — в Корзине.":
        "Files replaced: {n}, freed {size}. The originals are in the Recycle Bin.",
    "Сравнение «было / стало»": "Before / after",
    "Вписать": "Fit",
    "Колёсико — масштаб, мышью — двигать: обе половины двигаются вместе.":
        "Wheel — zoom, drag with the mouse to move: both halves move together.",
    "← Предыдущий": "← Previous",
    "Следующий →": "Next →",
    "{i} из {n}": "{i} of {n}",
    "Было {old} → стало {new}, меньше на {pct}": "Before {old} → after {new}, {pct} smaller",
    "Показан один кадр из видео. Посмотреть целиком — «Открыть сжатый».":
        "One frame of the video is shown. To watch all of it, use “Open compressed”.",
    # ---- что сделано и почему не сжат (compcore)
    "перепаковка": "repacked",
    "перепаковка (progressive)": "repacked (progressive)",
    "перепаковка PNG": "PNG repacked",
    "JPEG, качество {q}": "JPEG, quality {q}",
    "AV1, качество CRF {crf}": "AV1, quality CRF {crf}",
    "код {n}": "code {n}",
    "файл не похож на JPEG": "the file doesn't look like a JPEG",
    "испорченный JPEG": "damaged JPEG",
    "jpegtran не собрал файл": "jpegtran didn't produce a file",
    "в файле несколько снимков (HDR, глубина) — их бы потерять": "the file holds several images (HDR, depth) — they would be lost",
    "необычный JPEG — не трогаю": "unusual JPEG — left alone",
    "уже сжат сильно — дальше будут видны потери": "already strongly compressed — further loss would be visible",
    "без видимых потерь не сжимается": "can't be compressed without visible loss",
    "видео не открывается": "the video doesn't open",
    "в файле нет видео": "no video in the file",
    "уже в AV1": "already AV1",
    "HDR-видео — не трогаю, чтобы не испортить цвета": "HDR video — left alone to keep the colors right",
    "после сжатия видео не сходится с оригиналом (длина или звук)":
        "after compression the video doesn't match the original (length or sound)",
    "не удалось сравнить видео с оригиналом": "couldn't compare the video with the original",
    "файл изменился": "the file has changed",
    "файл только для чтения": "the file is read-only",
    "почти не уменьшился": "barely got smaller",
    "после пересборки пиксели не совпали — файл не трогаю": "pixels didn't match after rebuilding — file left alone",
    "файл пропал после подготовки": "the file is gone since preparation",
    "файл изменился после подготовки": "the file has changed since preparation",
    "сжатая копия пропала — подготовь заново": "the compressed copy is gone — prepare again",
    "оригинал не удалось убрать в Корзину — оставлен как был":
        "couldn't move the original to the Recycle Bin — left as it was",
    "оригинал в Корзине, а сжатый файл остался под именем {name}: {err}":
        "the original is in the Recycle Bin, but the compressed file stayed as {name}: {err}",
    "заменён, но даты не перенеслись: {err}": "replaced, but the dates were not copied: {err}",
    # ---- окно и трей при сжатии
    "Остановить сжатие": "Stop compression",
    "Сжатые копии готовы: {n}. Можно освободить {size}.": "Compressed copies are ready: {n}. You can free {size}.",
    "Сжимать нечего: файлы уже сжаты хорошо.": "Nothing to compress: the files are already well compressed.",
    "Сжатие подготовлено": "Compression prepared",
    "Сейчас идёт сжатие — если закрыть программу, оно остановится, а готовые копии пропадут.":
        "Compression is running — if you close the app, it stops and the ready copies are lost.",
    "Идёт сжатие. Закрыть программу и остановить его? Готовые копии пропадут.":
        "Compression is running. Close the app and stop it? The ready copies will be lost.",
    "Продолжить сжатие": "Keep compressing",
    "Сжатые копии ещё не заменили оригиналы — при закрытии они пропадут.":
        "The compressed copies haven't replaced the originals yet — closing loses them.",
    "Сжатые копии ещё не заменили оригиналы. Закрыть программу? Они пропадут.":
        "The compressed copies haven't replaced the originals yet. Close the app? They will be lost.",
    "Не закрывать": "Don't close",
    "Сжатие ещё идёт или сжатые копии не заменили оригиналы. Обновиться сейчас? Готовые копии пропадут.":
        "Compression is still running or the compressed copies haven't replaced the originals. Update now? "
        "The ready copies will be lost.",
    "В трее программа продолжает работать: значок у часов, поиск и сжатие не прерываются.":
        "In the tray the app keeps working: the icon is next to the clock, scanning and compression continue.",
    # ---- вкладка «Настройки»
    "Нагрузка на компьютер": "System load",
    "Как сильно поиск дубликатов занимает диск и процессор.": "How much the scan uses the disk and processor.",
    "Бережно": "Gentle",
    "Поиск уступает другим программам диск и процессор: компьютер не тормозит, даже если ты работаешь "
    "или играешь. Когда компьютер свободен, скорость почти та же; когда занят — поиск идёт медленнее.":
        "The scan gives way to other programs: the computer stays responsive even while you work or play. "
        "When the computer is idle the speed is almost the same; when it's busy the scan slows down.",
    "Обычно": "Normal",
    "Обычный приоритет, файлы читаются по одному. Лучший выбор для обычных жёстких дисков (HDD), "
    "например внешнего WD: им вредно читать несколько файлов сразу.":
        "Normal priority, files are read one at a time. Best for regular hard drives (HDD), "
        "such as an external WD: reading several files at once slows them down.",
    "Быстро — для SSD": "Fast — for SSD",
    "Читает четыре файла одновременно. На SSD и NVMe это заметно быстрее. На обычном жёстком диске "
    "может оказаться даже медленнее: головка диска прыгает между файлами.":
        "Reads four files at once. Noticeably faster on SSD and NVMe. On a regular hard drive it can even be "
        "slower: the disk head has to jump between files.",
    "Оформление": "Appearance",
    "Как в Windows": "Same as Windows",
    "Светлое": "Light",
    "Тёмное": "Dark",
    "Язык": "Language",
    "Язык сменится после перезапуска программы.": "The language will change after the app restarts.",
    "Перезапустить сейчас": "Restart now",
    "Когда закрываешь окно": "When you close the window",
    "Сворачивать в трей — значок у часов, поиск продолжается":
        "Minimize to tray — icon next to the clock, the scan keeps running",
    "Закрывать программу": "Exit the app",
    "Спрашивать каждый раз": "Ask every time",
    "Свернуть Duplio в трей или закрыть?": "Minimize Duplio to the tray or exit?",
    "Сейчас идёт поиск — если закрыть программу, он остановится.": "A scan is running — exiting will stop it.",
    "Больше не спрашивать (можно поменять в «Настройках»)": "Don't ask again (you can change this in Settings)",
    "Закрыть программу": "Exit",
    "Свернуть в трей": "Minimize to tray",
    "Идёт поиск. Закрыть программу и остановить его? Найденное будет потеряно.":
        "A scan is running. Exit and stop it? The results will be lost.",
    "Продолжить поиск": "Keep scanning",
    "Что программа хранит на компьютере": "What the app stores on your computer",
    "Только один маленький файл с этими настройками (меньше 1 КБ):":
        "Only one small file with these settings (under 1 KB):",
    "Файл настроек (меньше 1 КБ):": "Settings file (under 1 KB):",
    "Журнал работы — что программа делала и какие ошибки случились. Он нужен, чтобы разобраться, если что-то "
    "пошло не так; никуда не отправляется. Размер ограничен: не больше 3 МБ, старые записи вытесняются новыми.":
        "Activity log — what the app did and which errors happened. It helps to figure out what went wrong; "
        "it is never sent anywhere. Its size is capped at 3 MB, older entries are replaced by newer ones.",
    "Открыть папку журнала": "Open log folder",
    "Кэша на диске нет: превью живут только в памяти, пока открыто окно. Пока готовится сжатие, сжатые копии "
    "лежат в {work} — папка очищается при каждой новой подготовке и при выходе. Удалённые копии и заменённые "
    "оригиналы лежат в Корзине, пока ты её не очистишь.":
        "There is no cache on disk: previews live only in memory while the window is open. While compression is "
        "being prepared, compressed copies sit in {work} — the folder is emptied on every new preparation and "
        "on exit. Deleted copies and replaced originals stay in the Recycle Bin until you empty it.",
    "Что-то пошло не так: {err}\n\nПодробности записаны в журнал. Программа продолжит работать.":
        "Something went wrong: {err}\n\nThe details are in the activity log. The app keeps running.",
    "Открыть журнал": "Open log",
    "Закрыть": "Close",
    "Обновления": "Updates",
    "Версия {v}": "Version {v}",
    "Проверить обновления": "Check for updates",
    "Проверять при запуске": "Check at startup",
    "Проверка обращается к GitHub, где лежат выпуски программы; никаких данных о тебе и твоих файлах "
    "не отправляется.":
        "The check contacts GitHub, where the app's releases are published; no data about you or your files "
        "is sent.",
    "Проверяю…": "Checking…",
    "Установлена последняя версия.": "You have the latest version.",
    "Не удалось проверить обновления: {err}": "Couldn't check for updates: {err}",
    "Доступна версия {v}": "Version {v} is available",
    "Что нового": "What's new",
    "Обновить": "Update",
    "Позже": "Later",
    "Скачиваю обновление… {done} из {total}": "Downloading the update… {done} of {total}",
    "Обновление скачано. Программа закроется, установит новую версию и откроется снова.":
        "The update is downloaded. The app will close, install the new version and reopen.",
    "Установить и перезапустить": "Install and restart",
    "Не удалось скачать обновление: {err}": "Couldn't download the update: {err}",
    "Скачанный файл повреждён (не совпала контрольная сумма). Попробуй ещё раз.":
        "The downloaded file is damaged (checksum mismatch). Please try again.",
    "Сейчас идёт поиск. Остановить его и обновиться сейчас? Найденное будет потеряно.":
        "A scan is running. Stop it and update now? The results will be lost.",
    "Остановить и обновить": "Stop and update",
    "Отметить копии заново по новому правилу? Отметки, которые ты менял вручную, сбросятся.":
        "Re-mark copies using the new rule? The marks you changed by hand will be reset.",
    "Отметить заново": "Re-mark",
    "\n\n⚠ На дисках {drives} Корзины нет (флешка, карта памяти или сетевой диск): файлы оттуда удалятся "
    "НАВСЕГДА, вернуть их будет нельзя.":
        "\n\n⚠ Drives {drives} have no Recycle Bin (USB stick, memory card or network drive): files there will "
        "be deleted PERMANENTLY and cannot be restored.",
    "Удалить навсегда": "Delete permanently",
    "Отправляю в Корзину…": "Moving to the Recycle Bin…",
    # ---- трей и главное окно
    "Найдено групп копий: {n}. Можно освободить {size}.": "Duplicate groups found: {n}. You can free {size}.",
    "Точных копий не нашлось.": "No exact duplicates found.",
    "Поиск завершён": "Scan finished",
    "Программа свёрнута в трей и продолжает работать. Открыть — щелчок по значку, выйти — правой кнопкой "
    "→ «Выход». Поменять можно в «Настройках».":
        "The app is minimized to the tray and keeps running. Click the icon to open it; right-click → “Exit” "
        "to quit. You can change this in Settings.",
}
