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
    "Заменяю файлы: {done} из {total}": "Replacing files: {done} of {total}",
    "Отправляю в Корзину: {done} из {total}": "Moving to the Recycle Bin: {done} of {total}",
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
    "к снимку приложены HDR-карта, второй снимок или видео «живого фото» — их бы потерять":
        "an HDR map, a second image or a motion-photo video is attached to the photo — it would be lost",
    "служебные данные в конце снимка не перенеслись — файл не трогаю":
        "the extra data at the end of the photo was not carried over — file left alone",
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
    "готовая копия пропала — подготовь заново": "the prepared copy is gone — prepare again",
    "оригинал не удалось убрать в Корзину — оставлен как был":
        "couldn't move the original to the Recycle Bin — left as it was",
    "оригинал в Корзине, а новый файл остался под именем {name}: {err}":
        "the original is in the Recycle Bin, but the new file stayed as {name}: {err}",
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
    # ---- перетаскивание
    "Сбросить": "Clear",
    "Снова сжимать папку из поля": "Compress the folder from the field again",
    " Перетащенных файлов другого типа: {n} — программа их не сжимает.":
        " Dropped files of other types: {n} — the app doesn't compress them.",
    "Перетащено: {what}": "Dropped: {what}",
    "Перетащенных файлов больше нет на месте.": "The dropped files are no longer there.",
    "Отпусти — сожму только {what}": "Drop to compress only {what}",
    "Остальные файлы в папках не трону. Сжатые копии начну готовить по кнопке.":
        "Other files in the folders stay untouched. Compressed copies are prepared when you press the button.",
    "поиск": "a scan",
    "сжатие": "compression",
    "Сейчас идёт {what} — дождись конца или останови его.":
        "Duplio is busy with {what} — wait until it finishes or stop it.",
    "Отпусти — подставлю папку «{name}» в «Дубликаты»": "Drop to use the folder “{name}” in Duplicates",
    "Искать начну по кнопке «Начать поиск».": "The scan starts when you press “Start scan”.",
    "Отпусти — подставлю папку «{name}» в «Сжатие»": "Drop to use the folder “{name}” in Compression",
    "Сжатые копии начну готовить по кнопке.": "Compressed copies are prepared when you press the button.",
    " и ": " and ",
    "Перетащено несколько папок — подставлена первая: {name}": "Several folders were dropped — using the first one: {name}",
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
    "не удалось открыть файл, чтобы поставить даты": "couldn't open the file to set its dates",
    "не удалось поставить даты": "couldn't set the dates",
    "копия легла с ошибкой": "the copy was written with errors",
    # ---- метаданные: окно
    "Метаданные": "Metadata",
    "Метаданные фото и видео": "Photo and video metadata",
    "Остановить работу с метаданными": "Stop metadata work",
    "Сейчас идёт работа с метаданными — если закрыть программу, она остановится. Уже готовые файлы останутся "
    "готовыми.": "Metadata work is in progress — closing the app will stop it. Files already done stay done.",
    "Идёт работа с метаданными. Закрыть программу и остановить её?":
        "Metadata work is in progress. Close the app and stop it?",
    "Продолжить": "Continue",
    "работа с метаданными": "metadata work",
    "Отпусти — подставлю папку «{name}» в «Метаданные»": "Drop to put the folder “{name}” into Metadata",
    "Проверю файлы по кнопке «Проверить файлы».": "Files are checked when you press “Check files”.",
    "Отпусти — проверю только {what}": "Drop to check only {what}",
    "Остальные файлы в папках не трону. Проверю по кнопке.":
        "Other files in those folders won't be touched. Checking starts with the button.",
    "Снова проверять папку из поля": "Check the folder from the field again",
    "Убрать": "Remove",
    "Поворот и цвет остаются всегда. Без пересжатия.": "Rotation and color always stay. No re-encoding.",
    "Результат": "Result",
    "Проверить файлы": "Check files",
    "Выбери папку и что убрать, и нажми «Проверить файлы».": "Choose a folder and what to remove, then press “Check files”.",
    "Что уберётся": "To be removed",
    "Выбери файл в списке — здесь будет всё, что в нём записано, и что из этого уберётся.":
        "Select a file in the list — everything recorded in it will be shown here, and what will be removed.",
    "Поле": "Field",
    "Значение": "Value",
    "После": "After",
    "Здесь появятся фото и видео, в которых есть что убрать: геометка, камера, время, автор.\n\n"
    "Программа ничего не пересжимает — меняются только служебные записи файла. Сначала проверь список и "
    "«было → стало», потом нажми кнопку внизу.":
        "Photos and videos with something to remove will appear here: location, camera, time, author.\n\n"
        "Nothing is re-encoded — only the file's service records change. Review the list and “before → after” "
        "first, then press the button at the bottom.",
    "Оригиналы — в Корзину; имена и даты те же.": "Originals go to the Recycle Bin; names and dates stay.",
    "Папка для очищенных копий": "Folder for cleaned copies",
    "Где проверить метаданные": "Where to check metadata",
    "Читаю файлы…": "Reading files…",
    "Читаю файлы · {done} из {total}": "Reading files · {done} of {total}",
    "Убираю метаданные · {done} из {total}": "Removing metadata · {done} of {total}",
    "Заменяю файлы · {done} из {total}": "Replacing files · {done} of {total}",
    "Сохраняю копии · {done} из {total}": "Saving copies · {done} of {total}",
    "{app} — метаданные, {pct}%": "{app} — metadata, {pct}%",
    "Работа прервалась из-за ошибки:\n{text}": "The work stopped because of an error:\n{text}",
    "Проверено файлов: {n}.": "Files checked: {n}.",
    " Перетащенных файлов другого типа: {n} — их программа не читает.":
        " Dropped files of another type: {n} — the app doesn't read them.",
    "Проверка остановлена.": "Check stopped.",
    " Прочитанное — в списке.": " What was read is in the list.",
    "Готово за {t}. Убирать нечего.": "Done in {t}. Nothing to remove.",
    "Готово за {t}. Проверь список и «было → стало» и нажми кнопку внизу.":
        "Done in {t}. Review the list and “before → after”, then press the button at the bottom.",
    "В этих файлах нет ничего из выбранного.": "These files contain none of the selected items.",
    "Подходящих фото и видео тут нет.": "No suitable photos or videos here.",
    "Папки с ошибками: {n}": "Folders with errors: {n}",
    "Отметка — из файла уберётся выбранное": "Checked — the selected items will be removed from the file",
    "Сохранить {n} {copies}": "Save {n} {copies}",
    "Сохранить очищенные копии": "Save cleaned copies",
    "Убрать из {n} {files}": "Remove from {n} {files}",
    "Убрать из отмеченных файлов": "Remove from checked files",
    "Прочитано: {seen}  ·  есть что убрать: {shown}  ·  отмечено: {n}":
        "Read: {seen}  ·  with something to remove: {shown}  ·  checked: {n}",
    "не убрать": "can't remove",
    "не всё": "not all",
    "Часть полей убрать нельзя — какие и почему, видно справа.":
        "Some fields can't be removed — see which and why on the right.",
    "уберётся": "removed",
    "останется": "stays",
    "Эти файлы не удалось прочитать — они остаются как есть:\n\n": "These files couldn't be read — they stay as they are:\n\n",
    "Укажи папку для очищенных копий.": "Choose a folder for the cleaned copies.",
    "Копии нельзя класть в ту же папку, где лежат оригиналы — выбери другую.":
        "Copies can't go into the same folder as the originals — choose another one.",
    "Убрать ({what}) из {n} {files}?\n\nКартинка и видео не пересжимаются. Оригиналы уйдут в Корзину — вернуть "
    "можно оттуда. Имена и даты файлов останутся прежними.":
        "Remove ({what}) from {n} {files}?\n\nPictures and videos are not re-encoded. Originals go to the Recycle "
        "Bin — you can restore them from there. File names and dates stay the same.",
    "Убрать, оригиналы навсегда": "Remove, originals permanently",
    "Убираю метаданные…": "Removing metadata…",
    "Остановлено — ни один файл не изменён.": "Stopped — no file was changed.",
    "Сохранено очищенных копий: {n}. Папка: {folder}": "Cleaned copies saved: {n}. Folder: {folder}",
    "Сохранено очищенных копий: {n}.": "Cleaned copies saved: {n}.",
    "Готово: метаданные убраны из {n} {files}. Оригиналы — в Корзине.":
        "Done: metadata removed from {n} {files}. Originals are in the Recycle Bin.",
    "\n\nОставлены как есть ({n}):\n": "\n\nLeft as they are ({n}):\n",
    "\n\nНе получилось ({n}):\n": "\n\nFailed ({n}):\n",
    "Открыть папку": "Open folder",
    "Готово: метаданные убраны из {n} {files}.\n\nФайлы остались на своих местах с теми же именами и датами. "
    "Старые версии — в Корзине: оттуда их можно вернуть.":
        "Done: metadata removed from {n} {files}.\n\nThe files stayed in place with the same names and dates. "
        "The old versions are in the Recycle Bin — you can restore them from there.",
    "Готово: в проверенных файлах больше нечего убирать.": "Done: nothing left to remove in the checked files.",
    # ---- метаданные: группы, наборы
    "Место (GPS)": "Location (GPS)",
    "Камера и серийный номер": "Camera and serial number",
    "Время съёмки": "Capture time",
    "Автор и программа": "Author and software",
    "Превью внутри файла": "Embedded preview",
    "Прочее (XMP, IPTC, Samsung)": "Other (XMP, IPTC, Samsung)",
    "Всё": "Everything",
    "Только место": "Location only",
    "Свой набор": "Custom",
    "Сохранить копии в папку": "Save copies to a folder",
    "место": "location", "камера": "camera", "время": "time", "автор": "author", "превью": "preview",
    "прочее": "other",
    "Без метаданных": "Without metadata",
    "{name} — без метаданных": "{name} — without metadata",
    # ---- метаданные: поля
    "Описание": "Description",
    "Производитель камеры": "Camera make",
    "Модель камеры": "Camera model",
    "Программа": "Software",
    "Дата изменения": "Date modified",
    "Автор": "Author",
    "Компьютер": "Computer",
    "Авторские права": "Copyright",
    "Название": "Title",
    "Комментарий": "Comment",
    "Ключевые слова": "Keywords",
    "Тема": "Subject",
    "Дата съёмки": "Date taken",
    "Дата оцифровки": "Date digitized",
    "Часовой пояс": "Time zone",
    "Часовой пояс съёмки": "Time zone (taken)",
    "Часовой пояс оцифровки": "Time zone (digitized)",
    "Доли секунды": "Subseconds",
    "Доли секунды съёмки": "Subseconds (taken)",
    "Доли секунды оцифровки": "Subseconds (digitized)",
    "Служебная запись производителя": "Maker note",
    "Номер снимка": "Image ID",
    "Владелец камеры": "Camera owner",
    "Серийный номер камеры": "Camera serial number",
    "Объектив": "Lens",
    "Производитель объектива": "Lens make",
    "Модель объектива": "Lens model",
    "Серийный номер объектива": "Lens serial number",
    "Геометка": "Location",
    "Параметры съёмки": "Shooting settings",
    "Превью и служебная запись Samsung": "Samsung preview and service record",
    "Параметры камеры Samsung": "Samsung camera parameters",
    "{v} мм": "{v} mm",
    "ещё полей: {n}": "{n} more fields",
    "без координат": "no coordinates",
    "Превью в EXIF": "Preview in EXIF",
    "Превью Photoshop": "Photoshop preview",
    "Превью JFXX": "JFXX preview",
    "Превью FlashPix": "FlashPix preview",
    "XMP (дополнительный)": "XMP (extended)",
    "Подпись C2PA (история снимка)": "C2PA credentials (image history)",
    "Служебный блок {name}": "Service block {name}",
    "Должность автора": "Author's position",
    "Источник": "Source",
    "Автор описания": "Description writer",
    "Город": "City",
    "Район": "Sublocation",
    "Регион": "Province / state",
    "Код страны": "Country code",
    "Страна": "Country",
    "Место": "Location",
    "Дата создания": "Date created",
    "Время создания": "Time created",
    "Время оцифровки": "Time digitized",
    "Дата публикации": "Release date",
    "Время публикации": "Release time",
    "Заголовок": "Headline",
    "Дата записи": "Recording date",
    "Обложка": "Cover",
    "Превью": "Preview",
    "Дорожка с GPS": "GPS track",
    "приложенная картинка {n}": "attached picture {n}",
    "видео «живого фото»": "motion photo video",
    "Видео «живого фото»": "Motion photo video",
    "не разобрать": "can't parse",
    # ---- метаданные: почему не тронуто
    "EXIF не разобрать — не трогаю": "can't parse EXIF — left alone",
    "XMP не разобрать — не трогаю": "can't parse XMP — left alone",
    "видео не разобрать — не трогаю": "can't parse the video — left alone",
    "в записи Samsung лежат карта глубины или видео — не трогаю, чтобы они не потерялись":
        "the Samsung record holds a depth map or video — left alone so they aren't lost",
    "запись Samsung не разобрать — не трогаю": "can't parse the Samsung record — left alone",
    "это отдельный поток внутри видео — без перепаковки не убрать":
        "it's a separate stream inside the video — can't be removed without remuxing",
    "картинка изменилась бы — файл не трогаю": "the picture would change — file left alone",
    "приложенная картинка потерялась бы — файл не трогаю": "the attached picture would be lost — file left alone",
    "приложенная картинка изменилась бы — файл не трогаю": "the attached picture would change — file left alone",
    "приложенная картинка изменила бы размер": "the attached picture would change size",
    "размер видео изменился бы — файл не трогаю": "the video size would change — file left alone",
    "видео изменилось бы — файл не трогаю": "the video would change — file left alone",
    "после очистки поля не сошлись — файл не трогаю": "fields didn't match after cleaning — file left alone",
    "убирать нечего": "nothing to remove",
    "нет программы ffprobe": "ffprobe is missing",
    "слишком большой файл": "file is too large",
    "служебный блок не помещается в JPEG": "the service block doesn't fit into the JPEG",
    "XMP не помещается на старое место": "XMP doesn't fit into its old place",
    "файл не похож на PNG": "the file doesn't look like a PNG",
    "испорченный PNG": "damaged PNG",
    "испорченный MP4": "damaged MP4",
    "необычный MP4": "unusual MP4",
    "в файле нет описания видео (moov)": "the file has no video description (moov)",
    "испорченный EXIF": "damaged EXIF",
    "испорченный блок Photoshop": "damaged Photoshop block",
    "необычный IPTC": "unusual IPTC",
    "испорченный JPEG: нет конца картинки": "damaged JPEG: no end of image",
}
