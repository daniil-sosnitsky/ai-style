"""
Проверка текста на нейросетевой почерк.

Зачем: правки по стоп-листу человек делает глазами и половину пропускает -
особенно структурные, которые видно только в целом тексте (ровные абзацы,
подзаголовки-пустышки, ценность в конце вместо начала). Скрипт смотрит на весь
файл сразу и показывает, что именно править, с номерами строк.

Проверка не про обман детекторов. Она ловит ровно те следы, которые модель
оставляет по умолчанию: типографику, штампы, канцелярит и ровный ритм.
Человеческий вклад - фактуру, оценку, опыт - скрипт проверить не может, для
этого в конце выводятся четыре вопроса автору.

Запуск:
    python check_text.py текст.md              # один файл
    python check_text.py папка/                # все .md и .txt внутри
    python check_text.py текст.md --stoplist my.txt   # свой стоп-лист фраз
    python check_text.py текст.md --no-dash    # длинное тире разрешено
    python check_text.py пост.md --social      # пост для соцсети: тире и эмодзи разрешены

Код возврата: 0 - блокеров нет, 1 - есть. Удобно вешать на git-хук или CI.
"""

from __future__ import annotations

import argparse
import re
import statistics
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# --- Уровень 1: то, что не обсуждается ---------------------------------------

EM_DASH = "—"  # главная визуальная подпись генерации

# Основные пиктографические диапазоны. Типографика (кавычки, тире, стрелки)
# сюда намеренно не входит, иначе ложные срабатывания на каждом тексте.
EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF"
    "\U0001F000-\U0001F2FF\U0000FE0F\U00002B00-\U00002BFF]"
)

# Звёздочка на конце означает «основа слова»: «уникальн*» ловит и «уникальный»,
# и «уникальность». Без звёздочки фраза ищется как целое слово, иначе «шок»
# находится в «шоколадной» - на корпусе это была первая же ложная тревога.
CLICKBAIT = [
    "шок", "шокирующ*", "сенсация", "вы не поверите",
    "секрет, о котором молчат", "никто не говорит", "гарантия успеха",
    "без единого усилия", "это изменит всё",
]

# --- Уровень 2: штампы, норма не больше одного на 1000 знаков ----------------

CLICHES = [
    "в современном мире", "как никогда раньше", "играет ключевую роль",
    "играет важную роль", "давайте разберёмся", "давайте разберемся",
    "подводя итог", "в заключение", "стоит отметить", "следует отметить",
    "на сегодняшний день", "необходимо понимать", "таким образом",
    "важно учитывать", "данный аспект", "в конечном счёте", "в конечном счете",
    "не секрет, что", "трудно переоценить", "в эпоху цифровизации",
    "раз и навсегда",
]

AMPLIFIERS = [
    "значительно", "крайне важ*", "особенно важ*", "существенно",
    "поистине", "по-настоящему уникальн*",
]

EPITHETS = [
    "уникальн*", "потрясающ*", "невероятн*", "удивительн*",
    "захватывающ*", "революционн*", "инновационн*",
]

# Канцелярит: убирается целиком, а не заменяется синонимом того же регистра.
# Синоним-затычка («является» -> «представляет собой») маркер не снимает.
BUREAUCRAT = [
    "является", "представляет собой", "осуществляется", "производится",
    "данный", "данная", "данное", "данные решения", "вышеуказанн*",
    "вышеупомянут*", "в рамках", "с целью", "в случае необходимости",
    "позволяет осуществлять",
]

# Циклирование синонимов: модель боится повторов и переименовывает один и тот
# же предмет. Живой автор спокойно называет агента агентом во всём тексте.
RENAMING = [
    "данное решение", "этот инструмент", "указанный сервис",
    "рассматриваемый", "вышеописанн*", "данный продукт",
]

# --- Уровень 3: структура ----------------------------------------------------

EMPTY_HEADINGS = [
    "несколько мыслей", "что это значит", "дальше важное", "основная часть",
    "заключение", "введение", "вступление", "итоги", "выводы", "о чём статья",
    "общая информация", "немного теории", "что в итоге",
]

# Ровный ритм абзацев - самый сильный структурный след. Порог подобран на
# корпусе: у живого текста разброс длин абзацев заметно больше.
RHYTHM_MIN_PARAGRAPHS = 6
RHYTHM_CV_THRESHOLD = 0.35  # коэффициент вариации длин абзацев

CLICHE_PER_1000 = 1.0  # норма из стоп-листа


class Issue:
    """Одна находка. level: error блокирует, warn - нет."""

    def __init__(self, level: str, line: int | None, text: str):
        self.level = level
        self.line = line
        self.text = text


def strip_code_and_front(raw: str) -> tuple[str, int]:
    """
    Убирает YAML-фронтматтер и блоки кода: в них тире и штампы не считаются
    ошибкой, а вот ложных срабатываний дают больше всего.

    Возвращает текст и число строк, срезанных сверху, чтобы номера строк в
    отчёте совпадали с настоящим файлом.
    """
    lines = raw.splitlines()
    offset = 0

    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                offset = i + 1
                lines = lines[offset:]
                break

    out, in_code = [], False
    for line in lines:
        if line.lstrip().startswith("```"):
            in_code = not in_code
            out.append("")  # строку сохраняем пустой, чтобы нумерация не сползла
            continue
        out.append("" if in_code else line)

    return "\n".join(out), offset


def compile_phrase(phrase: str) -> re.Pattern[str]:
    """
    Собирает выражение для одной фразы. Граница слова обязательна слева всегда,
    справа - только у целых слов: у основы со звёздочкой окончание как раз и
    должно быть любым.
    """
    core = phrase.rstrip("*")
    tail = "" if phrase.endswith("*") else r"\b"
    return re.compile(r"\b" + re.escape(core) + tail, re.IGNORECASE)


def count_phrases(body: str, phrases: list[str]) -> int:
    return sum(len(compile_phrase(p).findall(body)) for p in phrases)


def find_phrases(body: str, phrases: list[str], level: str, label: str,
                 offset: int) -> list[Issue]:
    """Ищет фразы без учёта регистра и возвращает находки с номерами строк."""
    patterns = [(p, compile_phrase(p)) for p in phrases]
    found = []
    for num, line in enumerate(body.splitlines(), start=1):
        for phrase, pattern in patterns:
            if pattern.search(line):
                found.append(Issue(
                    level, num + offset, f"{label}: «{phrase.rstrip('*')}»",
                ))
    return found


def check_dashes(body: str, offset: int) -> list[Issue]:
    found = []
    for num, line in enumerate(body.splitlines(), start=1):
        count = line.count(EM_DASH)
        if count:
            found.append(Issue(
                "error", num + offset,
                f"длинное тире ({count} шт.) - замени на дефис, запятую, "
                f"двоеточие или скобки",
            ))
    return found


def check_emoji(body: str, offset: int) -> list[Issue]:
    found = []
    for num, line in enumerate(body.splitlines(), start=1):
        hits = EMOJI_RE.findall(line)
        if hits:
            found.append(Issue(
                "error", num + offset,
                f"эмодзи в тексте: {' '.join(hits[:5])}",
            ))
    return found


def check_cliche_density(body: str) -> list[Issue]:
    """
    Штампы не запрещены, но их плотность нормирована. Считаем на 1000 знаков,
    иначе короткий текст всегда проходит, а длинный всегда падает.
    """
    total = count_phrases(body, CLICHES)
    chars = max(len(body), 1)
    per_1000 = total / chars * 1000

    if per_1000 > CLICHE_PER_1000:
        return [Issue(
            "warn", None,
            f"штампов {total} на {chars} знаков = {per_1000:.1f} на 1000 "
            f"(норма {CLICHE_PER_1000:.0f})",
        )]
    return []


def check_rhythm(body: str) -> list[Issue]:
    """
    Симметрия абзацев. Если все абзацы одной длины, текст читается как
    сгенерированный, даже когда каждое слово на месте.
    """
    paragraphs = [
        p.strip() for p in re.split(r"\n\s*\n", body)
        if p.strip() and not p.lstrip().startswith(("#", "|", ">", "-", "*"))
    ]
    if len(paragraphs) < RHYTHM_MIN_PARAGRAPHS:
        return []

    lengths = [len(p) for p in paragraphs]
    mean = statistics.mean(lengths)
    if mean == 0:
        return []
    cv = statistics.pstdev(lengths) / mean

    if cv < RHYTHM_CV_THRESHOLD:
        return [Issue(
            "warn", None,
            f"абзацы одной длины: {len(paragraphs)} абзацев, в среднем "
            f"{mean:.0f} знаков, разброс {cv:.2f} (нужен > "
            f"{RHYTHM_CV_THRESHOLD}). Сделай один короткий, потом длинный",
        )]
    return []


def check_headings(body: str, offset: int) -> list[Issue]:
    found = []
    for num, line in enumerate(body.splitlines(), start=1):
        if not line.lstrip().startswith("#"):
            continue
        title = line.lstrip("#").strip().lower().rstrip("?:.")
        for empty in EMPTY_HEADINGS:
            if title == empty or title.startswith(empty + " "):
                found.append(Issue(
                    "warn", num + offset,
                    f"подзаголовок-пустышка: «{line.lstrip('#').strip()}» - "
                    f"он маркирует место, а не говорит о смысле",
                ))
                break
    return found


def check_late_value(body: str) -> list[Issue]:
    """
    Поздняя ценность: первые 70 слов ушли на контекст, а не на ответ «зачем
    читать». Признак - ни одной цифры и ни одного личного маркера в начале.
    """
    words = re.findall(r"\S+", re.sub(r"^#.*$", "", body, flags=re.M))
    if len(words) < 120:
        return []

    opening = " ".join(words[:70]).lower()
    has_number = bool(re.search(r"\d", opening))
    has_person = any(m in opening for m in (
        " я ", "я ", "мой", "моя", "мне", "у меня", "ты ", "тебе", "твой",
    ))

    if not has_number and not has_person:
        return [Issue(
            "warn", None,
            "в первых 70 словах нет ни цифры, ни обращения - похоже на разгон. "
            "Ценность должна стоять в первых 40-70 словах",
        )]
    return []


def load_stoplist(path: Path | None) -> list[str]:
    """Личный стоп-лист: свои формулировки, которые уже повторялись."""
    if not path or not path.exists():
        return []
    phrases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            phrases.append(line.lower())
    return phrases


def check_file(path: Path, stoplist: list[str], allow_dash: bool,
               allow_emoji: bool) -> list[Issue]:
    raw = path.read_text(encoding="utf-8")
    body, offset = strip_code_and_front(raw)

    issues: list[Issue] = []
    if not allow_dash:
        issues += check_dashes(body, offset)
    if not allow_emoji:
        issues += check_emoji(body, offset)
    issues += find_phrases(body, CLICKBAIT, "error", "кликбейт", offset)
    issues += find_phrases(body, stoplist, "error", "свой стоп-лист", offset)
    issues += check_cliche_density(body)
    issues += find_phrases(body, BUREAUCRAT, "warn", "канцелярит", offset)
    issues += find_phrases(body, RENAMING, "warn", "переименование предмета", offset)
    issues += find_phrases(body, AMPLIFIERS, "warn", "пустой усилитель", offset)
    issues += find_phrases(body, EPITHETS, "warn", "пустой эпитет", offset)
    issues += check_headings(body, offset)
    issues += check_rhythm(body)
    issues += check_late_value(body)
    return issues


FINAL_QUESTIONS = """
Что скрипт проверить не может - проверь сам:
  1. Есть ли в тексте хотя бы одна мысль, которая не собирается из чужих статей?
  2. Можно ли убрать первые два абзаца без потери смысла? Если да - перепиши их.
  3. Структура похожа на маршрут мысли или на автоматический план?
  4. Есть ли место, где сказано «вот тут я не уверен» или «это работает, но»?
"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Проверка текста на нейросетевой почерк",
    )
    parser.add_argument("target", help="файл или папка с .md / .txt")
    parser.add_argument("--stoplist", help="свой стоп-лист фраз (по строке на фразу)")
    parser.add_argument("--no-dash", action="store_true",
                        help="не считать длинное тире ошибкой")
    parser.add_argument("--social", action="store_true",
                        help="пост для соцсети: тире и эмодзи там норма формата")
    parser.add_argument("--quiet", action="store_true",
                        help="только блокеры, без предупреждений")
    args = parser.parse_args()

    target = Path(args.target)
    if not target.exists():
        print(f"Не нашёл: {target}")
        return 1

    files = (
        sorted(p for p in target.rglob("*") if p.suffix.lower() in (".md", ".txt"))
        if target.is_dir() else [target]
    )
    if not files:
        print("Внутри нет ни одного .md или .txt")
        return 1

    stoplist = load_stoplist(Path(args.stoplist) if args.stoplist else None)
    total_errors = 0

    for path in files:
        issues = check_file(
            path, stoplist,
            allow_dash=args.no_dash or args.social,
            allow_emoji=args.social,
        )
        errors = [i for i in issues if i.level == "error"]
        warns = [i for i in issues if i.level == "warn"]
        total_errors += len(errors)

        print(f"\n{path}")
        # В тихом режиме «чисто» означает «блокеров нет»: правки скрыты
        # осознанно, и молчаливая пустая строка выглядела бы как сбой.
        if not errors and (args.quiet or not warns):
            print("  чисто" if not warns else f"  блокеров нет, правок: {len(warns)}")
            continue

        for issue in errors:
            where = f"строка {issue.line}" if issue.line else "весь текст"
            print(f"  [блокер] {where}: {issue.text}")
        if not args.quiet:
            for issue in warns:
                where = f"строка {issue.line}" if issue.line else "весь текст"
                print(f"  [правка] {where}: {issue.text}")

    print(f"\nИтого блокеров: {total_errors}")
    if len(files) == 1:
        print(FINAL_QUESTIONS)
    return 1 if total_errors else 0


if __name__ == "__main__":
    sys.exit(main())
