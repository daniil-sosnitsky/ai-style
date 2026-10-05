#!/usr/bin/env python3
"""
token-report — диагностика расхода токенов Claude Code по локальным транскриптам.

Зачем: прежде чем экономить, надо знать, на что именно уходит бюджет. Claude Code
пишет каждый запрос к модели в JSONL рядом с собой, и там лежит полная разбивка
расхода. Этот скрипт собирает её в четыре статьи и показывает, какая из них у
тебя главная. Никаких сетевых запросов и зависимостей — только стандартная
библиотека и файлы, которые уже лежат на диске.

Четыре статьи расхода:
  1. cache_write — запись контекста в кэш (дороже обычного входа)
  2. cache_read  — чтение из кэша (сильно дешевле входа)
  3. input       — вход мимо кэша
  4. output      — то, что модель написала (включая размышления)

Запуск:
  python token_report.py                      # всё, что есть, за 30 дней
  python token_report.py --days 7             # за неделю
  python token_report.py --project my-vault   # один проект (поиск по подстроке)
  python token_report.py --session <id>       # одна сессия
  python token_report.py --by day             # разбивка по дням
  python token_report.py --pricing pricing.json   # добавить деньги
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Имена статей расхода — порядок задаёт порядок колонок во всех таблицах.
# Запись в кэш разделена по TTL намеренно: 5 минут стоят 1.25x от цены входа,
# час — 2x. Считать их одной статьёй значит ошибиться в деньгах почти вдвое.
STATS = ("cache_write_5m", "cache_write_1h", "cache_read", "input", "output")
# Что сворачивается в колонку cache_wr при печати
WRITE_PARTS = ("cache_write_5m", "cache_write_1h")


def projects_dir() -> Path:
    """Где Claude Code держит транскрипты. CLAUDE_CONFIG_DIR перебивает дефолт."""
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(base) if base else Path.home() / ".claude") / "projects"


def parse_ts(value: str | None) -> datetime | None:
    """Время записи. В транскрипте ISO-8601 с Z, который fromisoformat не ест до 3.11."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def iter_usage(files, since: datetime | None):
    """
    Выдаёт по одной записи расхода: (время, модель, субагент ли, статьи, файл).

    Дедупликация по requestId обязательна: один запрос к модели может быть записан
    несколько раз (ретраи, несколько блоков ответа), и без неё расход задваивается.
    """
    seen: set[str] = set()

    for path in files:
        try:
            handle = path.open("r", encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"  пропускаю {path.name}: {exc}", file=sys.stderr)
            continue

        with handle:
            for line in handle:
                line = line.strip()
                # Быстрый отсев без разбора JSON: usage есть у меньшинства строк
                if not line or '"usage"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue

                message = rec.get("message") or {}
                usage = message.get("usage")
                if not isinstance(usage, dict):
                    continue

                request_id = rec.get("requestId")
                if request_id:
                    if request_id in seen:
                        continue
                    seen.add(request_id)

                ts = parse_ts(rec.get("timestamp"))
                if since and ts and ts < since:
                    continue

                # Разбивку по TTL даёт usage.cache_creation. Если её нет (старый
                # формат записи) — весь объём пишем в 5m: это консервативнее,
                # час стоит дороже, и завышать расход не хочется.
                creation = usage.get("cache_creation") or {}
                written = usage.get("cache_creation_input_tokens", 0) or 0
                w5 = creation.get("ephemeral_5m_input_tokens")
                w1h = creation.get("ephemeral_1h_input_tokens")
                if w5 is None and w1h is None:
                    w5, w1h = written, 0

                yield (
                    ts,
                    message.get("model") or "unknown",
                    bool(rec.get("isSidechain")),
                    {
                        "cache_write_5m": w5 or 0,
                        "cache_write_1h": w1h or 0,
                        "cache_read": usage.get("cache_read_input_tokens", 0) or 0,
                        "input": usage.get("input_tokens", 0) or 0,
                        "output": usage.get("output_tokens", 0) or 0,
                    },
                    path,
                )


def add(dst: dict, src: dict) -> None:
    for key in STATS:
        dst[key] += src[key]


def blank() -> dict:
    return {key: 0 for key in STATS}


def human(n: float) -> str:
    """Короткая запись числа: 1.2M, 340.5K, 912."""
    for limit, suffix in ((1_000_000, "M"), (1_000, "K")):
        if abs(n) >= limit:
            return f"{n / limit:.1f}{suffix}"
    return f"{n:.0f}"


def load_pricing(path: str | None) -> dict | None:
    """
    Цены намеренно не зашиты в код: тарифы и линейка моделей меняются быстрее,
    чем обновляется скрипт, а соврамши в деньгах — хуже, чем не сказать вовсе.
    Формат файла — в pricing.example.json рядом.
    """
    if not path:
        return None
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Не читается файл цен ({exc}) — показываю только токены.\n", file=sys.stderr)
        return None

    if "models" not in data:
        print("В файле цен нет ключа 'models' — показываю только токены.\n", file=sys.stderr)
        return None
    return data


def money(stats: dict, model: str, pricing: dict | None) -> float | None:
    """Стоимость статей расхода по тарифу модели. None — тарифа для неё нет."""
    if not pricing:
        return None
    rates = pricing["models"].get(model)
    if not rates:
        return None
    return sum(stats[key] * rates.get(key, 0) for key in STATS) / 1_000_000


def read_session(path: Path) -> list[dict]:
    """
    Все шаги одной сессии по порядку. Шаг — один запрос к модели.
    Нужен для режимов --startup и --growth: там важен не общий итог,
    а то, как сессия росла от шага к шагу.
    """
    steps, seen = [], set()
    try:
        handle = path.open("r", encoding="utf-8", errors="replace")
    except OSError:
        return steps

    with handle:
        for line in handle:
            if '"usage"' not in line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            usage = (rec.get("message") or {}).get("usage")
            if not isinstance(usage, dict):
                continue
            rid = rec.get("requestId")
            if rid:
                if rid in seen:
                    continue
                seen.add(rid)
            steps.append({
                "in": ((usage.get("cache_read_input_tokens", 0) or 0)
                       + (usage.get("cache_creation_input_tokens", 0) or 0)
                       + (usage.get("input_tokens", 0) or 0)),
                "written": usage.get("cache_creation_input_tokens", 0) or 0,
                "ts": rec.get("timestamp"),
            })
    return steps


def startup_report(files) -> None:
    """
    Цена входа в сессию.

    Первый запрос любой сессии записывает в кэш весь неизменяемый префикс:
    системную инструкцию, описания ВСЕХ подключённых инструментов (каждый
    MCP-сервер приносит свои) и файлы инструкций проекта. Это и есть
    стартовый налог — он платится в каждой сессии и перечитывается на
    каждом её шаге.
    """
    starts = []
    for path in files:
        steps = read_session(path)
        if steps and steps[0]["written"]:
            starts.append((steps[0]["written"], path.parent.name, (steps[0]["ts"] or "")[:10]))

    if not starts:
        print("Не нашёл ни одной сессии с замером старта.", file=sys.stderr)
        return

    starts.sort(reverse=True)
    values = sorted(s[0] for s in starts)
    median = values[len(values) // 2]

    print(f"\n=== Цена входа в сессию ===")
    print(f"Замерено сессий: {len(starts)}\n")
    print(f"  Типичный старт:  {human(median):>9} токенов")
    print(f"  Самый лёгкий:    {human(values[0]):>9}")
    print(f"  Самый тяжёлый:   {human(values[-1]):>9}")
    print(f"  Всего за период: {human(sum(values)):>9} — только на входы в сессии")

    print("\nСамые тяжёлые старты:")
    width = max(len(s[1]) for s in starts[:8])
    for written, project, day in starts[:8]:
        print(f"  {human(written):>9}  {day}  {project:<{width}}")

    print("\nИз чего состоит стартовый префикс: системная инструкция, описания")
    print("всех подключённых инструментов и файлы инструкций проекта. Каждый")
    print("MCP-сервер добавляет сюда описание каждого своего инструмента —")
    print("и ты платишь за них, даже если ни разу их не вызвал.")


def growth_report(files) -> None:
    """
    Как дорожает шаг по мере роста сессии.

    Каждый следующий шаг перечитывает всё, что накопилось раньше. Поэтому
    длинная сессия дорожает не пропорционально числу шагов, а быстрее:
    удвоив число шагов, ты больше чем удваиваешь расход.
    """
    buckets = {"1-20 шагов": [], "21-50": [], "51-100": [], "101-200": [], "больше 200": []}
    longest, longest_name = [], ""

    for path in files:
        steps = read_session(path)
        if len(steps) < 5:          # совсем короткие сессии статистику только зашумят
            continue
        n = len(steps)
        key = ("1-20 шагов" if n <= 20 else "21-50" if n <= 50 else
               "51-100" if n <= 100 else "101-200" if n <= 200 else "больше 200")
        buckets[key].append((n, sum(s["in"] for s in steps)))
        if n > len(longest):
            longest, longest_name = steps, path.stem[:8]

    if not any(buckets.values()):
        print("Сессий длиннее пяти шагов не нашлось — росту негде проявиться.", file=sys.stderr)
        return

    print("\n=== Как дорожает сессия ===\n")
    print(f"  {'длина сессии':<14} {'сессий':>7} {'цена шага':>12} {'вся сессия':>13}")
    print("  " + "-" * 50)
    for name, items in buckets.items():
        if not items:
            continue
        steps_total = sum(n for n, _ in items)
        tokens_total = sum(t for _, t in items)
        print(f"  {name:<14} {len(items):>7} {human(tokens_total / steps_total):>12} "
              f"{human(tokens_total / len(items)):>13}")

    short = buckets["1-20 шагов"]
    long_ = buckets["101-200"] + buckets["больше 200"]
    if short and long_:
        per_short = sum(t for _, t in short) / sum(n for n, _ in short)
        per_long = sum(t for _, t in long_) / sum(n for n, _ in long_)
        print(f"\n  Шаг в длинной сессии дороже шага в короткой "
              f"в {per_long / per_short:.1f} раза.")
        print("  Это не потому, что задачи сложнее. Это потому, что каждый шаг")
        print("  перечитывает всё, что накопилось в разговоре до него.")

    if len(longest) >= 8:
        quarter = len(longest) // 4
        print(f"\n  Та же картина внутри одной сессии ({len(longest)} шагов, {longest_name}):")
        for i, label in enumerate(["первая четверть", "вторая", "третья", "последняя"]):
            part = longest[i * quarter:(i + 1) * quarter]
            if part:
                avg = sum(s["in"] for s in part) / len(part)
                print(f"    {label:<16} {human(avg):>9} на шаг")

    print("\n  Вывод: работу дешевле дробить на короткие сессии под одну задачу,")
    print("  чем вести одну длинную. Механическое и объёмное — отдавать субагенту:")
    print("  он читает в своём окне, а в твою сессию возвращает только итог.")


def per_request(stats: dict, requests: int) -> dict:
    """
    Расход на один запрос. Сравнивать абсолютные цифры бессмысленно: в неделю
    с тремя выпусками статей их всегда больше, чем в тихую. Экономия видна
    только в удельном расходе — сколько стоит один шаг агента.
    """
    return {key: stats[key] / requests for key in STATS} if requests else blank()


def save_snapshot(path: str, total: dict, requests: int, days: int) -> None:
    snapshot = {
        "saved": datetime.now().astimezone().isoformat(timespec="seconds"),
        "days": days,
        "requests": requests,
        "total": total,
        "per_request": per_request(total, requests),
    }
    try:
        Path(path).write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nСнимок сохранён: {path}. Это точка отсчёта — "
              f"после правок запусти с --compare {path}.")
    except OSError as exc:
        print(f"\nНе смог сохранить снимок: {exc}", file=sys.stderr)


def compare_snapshot(path: str, total: dict, requests: int) -> None:
    """Сравнение удельного расхода с сохранённой точкой отсчёта."""
    try:
        old = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"\nНе читается снимок для сравнения: {exc}", file=sys.stderr)
        return

    was, now = old.get("per_request") or {}, per_request(total, requests)
    print(f"\n=== Сравнение со снимком от {old.get('saved', '?')} ===")
    print("Удельный расход — токенов на один запрос к модели:\n")
    print(f"  {'статья':<16} {'было':>10} {'стало':>10} {'разница':>10}")
    print("  " + "-" * 48)

    for key in STATS:
        before, after = was.get(key, 0), now[key]
        if not before and not after:
            continue
        delta = f"{(after - before) / before * 100:+.1f}%" if before else "—"
        print(f"  {key:<16} {human(before):>10} {human(after):>10} {delta:>10}")

    total_before, total_after = sum(was.get(k, 0) for k in STATS), sum(now.values())
    if total_before:
        change = (total_after - total_before) / total_before * 100
        print(f"\n  Итого на запрос: {human(total_before)} → {human(total_after)} "
              f"({change:+.1f}%)")
        # Шум между прогонами легко даёт единицы процентов — не выдаём его за результат
        print("  " + ("Экономия есть." if change <= -5 else
                      "Стало дороже." if change >= 5 else
                      "Разница в пределах шума: сравнивай на сопоставимых задачах."))


def table(title: str, rows: list[tuple[str, dict]], total: dict, pricing: dict | None,
          model_of=None) -> None:
    """Печатает таблицу: строка | четыре статьи | итог | доля | (деньги)."""
    if not rows:
        return

    grand = sum(total.values()) or 1
    width = max([len(name) for name, _ in rows] + [len(title)])
    show_money = pricing is not None and model_of is not None

    head = (f"{title:<{width}}  {'cache_wr':>9} {'cache_rd':>9} {'input':>8} "
            f"{'output':>8} {'ИТОГО':>9} {'доля':>6}")
    if show_money:
        head += f" {'$':>8}"
    print("\n" + head)
    print("-" * len(head))

    for name, stats in rows:
        total_row = sum(stats.values())
        written = sum(stats[k] for k in WRITE_PARTS)
        line = (f"{name:<{width}}  {human(written):>9} "
                f"{human(stats['cache_read']):>9} {human(stats['input']):>8} "
                f"{human(stats['output']):>8} {human(total_row):>9} "
                f"{total_row / grand * 100:>5.1f}%")
        if show_money:
            cost = money(stats, model_of(name), pricing)
            line += f" {cost:>8.2f}" if cost is not None else f" {'—':>8}"
        print(line)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Куда уходят токены Claude Code — по локальным транскриптам",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--days", type=int, default=30, help="период в днях (0 — всё; по умолчанию 30)")
    ap.add_argument("--project", help="фильтр по имени папки проекта (подстрока)")
    ap.add_argument("--session", help="фильтр по id сессии (подстрока имени файла)")
    ap.add_argument("--by", choices=["model", "project", "day", "session"], default="model",
                    help="главный срез (по умолчанию model)")
    ap.add_argument("--top", type=int, default=15, help="сколько строк показывать в срезе")
    ap.add_argument("--pricing", help="путь к JSON с тарифами — добавит колонку с деньгами")
    ap.add_argument("--save", metavar="FILE", help="сохранить снимок расхода — точка отсчёта")
    ap.add_argument("--compare", metavar="FILE", help="сравнить с сохранённым снимком")
    ap.add_argument("--startup", action="store_true",
                    help="сколько стоит вход в сессию — вес инструментов и инструкций")
    ap.add_argument("--growth", action="store_true",
                    help="как дорожает шаг по мере роста сессии")
    args = ap.parse_args()

    root = projects_dir()
    if not root.is_dir():
        print(f"Не нахожу транскрипты: {root}\n"
              "Claude Code здесь не запускался, или путь переопределён в CLAUDE_CONFIG_DIR.",
              file=sys.stderr)
        return 1

    files = [p for p in root.rglob("*.jsonl")
             if (not args.project or args.project.lower() in p.parent.name.lower())
             and (not args.session or args.session.lower() in p.stem.lower())]
    if not files:
        print("Под фильтры не попал ни один транскрипт.", file=sys.stderr)
        return 1

    # Режимы --startup и --growth отвечают на свои вопросы и завершаются:
    # им нужна структура сессий, а не общий котёл расхода
    if args.startup or args.growth:
        if args.startup:
            startup_report(files)
        if args.growth:
            growth_report(files)
        return 0

    since = (datetime.now(timezone.utc) - timedelta(days=args.days)) if args.days else None
    pricing = load_pricing(args.pricing)

    total = blank()
    by_model: dict[str, dict] = defaultdict(blank)
    by_project: dict[str, dict] = defaultdict(blank)
    by_day: dict[str, dict] = defaultdict(blank)
    by_session: dict[str, dict] = defaultdict(blank)
    main_vs_sub = {"основная модель": blank(), "субагенты": blank()}
    # Модель каждой группы нужна, чтобы посчитать деньги по её тарифу
    model_hint: dict[str, str] = {}
    requests = 0

    for ts, model, is_sub, stats, path in iter_usage(files, since):
        requests += 1
        add(total, stats)
        add(by_model[model], stats)
        add(by_project[path.parent.name], stats)
        add(by_session[path.stem[:8]], stats)
        add(main_vs_sub["субагенты" if is_sub else "основная модель"], stats)
        if ts:
            add(by_day[ts.astimezone().strftime("%Y-%m-%d")], stats)
        # За группу отвечает модель, которая нажгла в ней больше всех
        for group in (path.parent.name, path.stem[:8]):
            model_hint.setdefault(group, model)

    grand = sum(total.values())
    if not grand:
        print("Записей расхода за период нет.", file=sys.stderr)
        return 1

    period = f"последние {args.days} дн." if args.days else "всё время"
    print(f"\n=== Расход токенов: {period} ===")
    print(f"Транскриптов: {len(files)} | запросов к модели: {requests} | всего токенов: {human(grand)}")

    print("\nЧетыре статьи расхода:")
    writes = sum(total[k] for k in WRITE_PARTS)
    articles = [("cache_write", writes), ("cache_read", total["cache_read"]),
                ("input", total["input"]), ("output", total["output"])]
    for key, value in articles:
        share = value / grand * 100
        bar = "#" * round(share / 2)
        print(f"  {key:<12} {human(value):>9}  {share:>5.1f}%  {bar}")

    # Главный диагностический вопрос: кэш читается или переписывается?
    # Порог окупаемости зависит от TTL: 5 минут отбиваются со второго чтения,
    # час — с третьего (запись стоит вдвое). Берём порог по тому TTL,
    # которым реально писали больше.
    if writes:
        ratio = total["cache_read"] / writes
        hour_mode = total["cache_write_1h"] > total["cache_write_5m"]
        need = 3 if hour_mode else 2
        verdict = ("кэш работает" if ratio >= need * 2 else
                   "кэш окупается, но впритык" if ratio >= need else
                   "кэш не окупается — контекст рвётся до того, как его успевают перечитать")
        ttl = "1 час" if hour_mode else "5 минут"
        print(f"\n  Кэш: на 1 токен записи приходится {ratio:.1f} чтения "
              f"(TTL {ttl}, порог окупаемости — {need}) — {verdict}.")

    srez = {"model": (by_model, "Модель"), "project": (by_project, "Проект"),
            "day": (by_day, "День"), "session": (by_session, "Сессия")}
    data, label = srez[args.by]
    rows = sorted(data.items(), key=lambda kv: sum(kv[1].values()), reverse=True)[:args.top]
    if args.by == "day":
        rows.sort(key=lambda kv: kv[0])

    model_of = (lambda name: name) if args.by == "model" else (lambda name: model_hint.get(name, ""))
    table(label, rows, total, pricing, model_of)
    table("Кто тратит", list(main_vs_sub.items()), total, pricing, None)

    if args.compare:
        compare_snapshot(args.compare, total, requests)
    if args.save:
        save_snapshot(args.save, total, requests, args.days)

    if pricing:
        print(f"\nЦены из {args.pricing}" +
              (f", сверено {pricing['checked']}" if pricing.get("checked") else "") +
              ". Это оценка по твоему тарифу, а не счёт.")
    else:
        print("\nДеньги не показаны: передай --pricing со своим тарифом "
              "(образец — pricing.example.json).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
