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
    "Скоро здесь можно будет уменьшить размер фото и видео. Пока вкладка показывает, как это будет устроено.":
        "Soon you'll be able to make photos and videos smaller here. For now this tab shows how it will work.",
    "Строго без потерь": "Strictly lossless",
    "Для фото JPEG и PNG: файл пересобирается так, что ни один пиксель не меняется — открой до и после, "
    "и они совпадут до последнего бита изображения. Экономия скромная: примерно 5–20%.":
        "For JPEG and PNG photos: the file is rebuilt so that not a single pixel changes — open it before and after "
        "and the image matches to the last bit. Savings are modest: about 5–20%.",
    "Без видимых потерь": "Visually lossless",
    "Для фото и видео: пережатие в современные форматы. На глаз разницу не увидеть, а места освобождается "
    "в разы больше — обычно 30–70%. Перед заменой программа покажет «было / стало» рядом, а оригинал "
    "отправит в Корзину.":
        "For photos and videos: re-encoding into modern formats. You won't see the difference, and it frees much "
        "more space — usually 30–70%. Before replacing, the app shows “before / after” side by side and moves "
        "the original to the Recycle Bin.",
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
    "В трее программа продолжает работать: значок у часов, поиск не прерывается.":
        "In the tray the app keeps running: icon next to the clock, the scan continues.",
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
    "Временных файлов и кэша на диске нет: превью живут только в памяти, пока открыто окно. Удалённые копии "
    "лежат в Корзине, пока ты её не очистишь.":
        "No temporary files or disk cache: previews live in memory only while the window is open. "
        "Deleted copies stay in the Recycle Bin until you empty it.",
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
