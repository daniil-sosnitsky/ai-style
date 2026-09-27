"""
Unified Wordstat CLI — Yandex Cloud Search API v2 / Wordstat.

Единая Windows-совместимая замена bash-скриптам из оригинального скилла
(top_requests.sh, dynamics.sh, regions_stats.sh, regions_tree.sh,
search_region.sh, quota.sh). Требует только stdlib.

Секреты: .env рядом со скриптом (авто-подхват).

Использование:
  python wordstat.py top      --phrase "автоматизация"  [--limit 100] [--device all] [--regions 213] [--csv exports/out.csv]
  python wordstat.py dynamics --phrase "автоматизация"  [--from 2025-01-01] [--period monthly] [--device all]
  python wordstat.py regions  --phrase "автоматизация"  [--region-type cities] [--device all]
  python wordstat.py tree     [--search "Казань"]
  python wordstat.py quota
  python wordstat.py batch    phrases.txt               [--csv exports/out.csv]

Важно:
- Операторы Wordstat (!, +, "...", (a|b)) API v2 не поддерживает — только plain text.
- numPhrases обязателен для topRequests (нет дефолта в API, несмотря на документацию).
- Для dynamics с PERIOD_MONTHLY дата toDate должна быть последним днём месяца
  (скрипт корректирует автоматически).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# --- Конфиг ---
BASE_URL = "https://searchapi.api.cloud.yandex.net/v2/wordstat"
DEFAULT_REGIONS: list[str] = []  # пусто = вся Россия (без явного ограничения)
CACHE_DIR = Path(__file__).parent / "cache"

# TTL кеша в часах для каждого метода API
CACHE_TTL: dict[str, int] = {
    "topRequests": 24,
    "dynamics": 24,
    "regions": 24,
    "getRegionsTree": 720,  # 30 дней — данные меняются очень редко
}

# Справочник регионов (статический, без API-запроса)
REGION_NAMES: dict[str, str] = {
    "225": "Россия", "159": "Украина", "187": "Беларусь", "149": "Казахстан",
    "1": "Москва и область", "213": "Москва", "10716": "Московская область",
    "2": "Санкт-Петербург", "54": "Екатеринбург", "65": "Новосибирск",
    "43": "Казань", "35": "Краснодар", "47": "Нижний Новгород",
    "39": "Ростов-на-Дону", "51": "Уфа", "172": "Уфа (р-н)",
    "56": "Челябинск", "66": "Пермь", "38": "Красноярск",
    "37": "Воронеж", "195": "Минск", "11": "Барнаул",
    "14": "Владивосток", "44": "Самара",
    "3": "Центральный ФО", "17": "Северо-Западный ФО",
    "40": "Сибирский ФО", "52": "Приволжский ФО",
    "59": "Уральский ФО", "26": "Южный ФО",
    "73": "Дальневосточный ФО", "977": "Северо-Кавказский ФО",
}

DEVICE_MAP = {"all": "DEVICE_ALL", "desktop": "DEVICE_DESKTOP",
              "phone": "DEVICE_PHONE", "tablet": "DEVICE_TABLET"}
PERIOD_MAP = {"daily": "PERIOD_DAILY", "weekly": "PERIOD_WEEKLY",
              "monthly": "PERIOD_MONTHLY"}
REGION_TYPE_MAP = {"all": "REGION_ALL", "cities": "REGION_CITIES",
                   "regions": "REGION_REGIONS"}


# --- Кеш ---

def _cache_key(method: str, body: dict) -> str:
    """Стабильный ключ кеша: sha256 от метода + тела (без folderId)."""
    clean = {k: v for k, v in sorted(body.items()) if k != "folderId"}
    payload = f"{method}:{json.dumps(clean, ensure_ascii=False, sort_keys=True)}"
    return f"{method}_{hashlib.sha256(payload.encode()).hexdigest()[:16]}"


def _cache_get(key: str, ttl_hours: int) -> dict | None:
    """Вернуть данные из кеша, если файл существует и моложе ttl_hours."""
    path = CACHE_DIR / f"{key}.json"
    if not path.exists():
        return None
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
        cached_at = datetime.fromisoformat(stored["cached_at"])
        age_h = (datetime.now(timezone.utc) - cached_at).total_seconds() / 3600
        if age_h < ttl_hours:
            return stored["data"]
    except (KeyError, ValueError, OSError):
        pass
    return None


def _cache_set(key: str, data: dict) -> None:
    """Сохранить ответ API в кеш."""
    CACHE_DIR.mkdir(exist_ok=True)
    path = CACHE_DIR / f"{key}.json"
    path.write_text(
        json.dumps({"cached_at": datetime.now(timezone.utc).isoformat(), "data": data},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# --- Инфраструктура ---

class WordstatError(RuntimeError):
    """Ошибка обращения к API (сеть, авторизация, INVALID_ARGUMENT и т.п.)."""


def _load_dotenv() -> None:
    """Подхватить .env рядом со скриптом без внешних зависимостей."""
    path = Path(__file__).parent / ".env"
    if not path.exists():
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            os.environ.setdefault(name.strip(), value.strip())


def _fix_stdout() -> None:
    """Форсировать utf-8 в Windows-консоли (иначе кракозябры)."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass


def _fmt(n) -> str:
    """Форматировать число с пробелами-разделителями тысяч.

    count приходит строкой из-за protobuf int64 — int() обязателен.
    """
    try:
        return f"{int(n):,}".replace(",", " ")  # тонкий пробел
    except (TypeError, ValueError):
        return str(n)


def _region_name(rid: str) -> str:
    return REGION_NAMES.get(str(rid), str(rid))


@dataclass
class WordstatClient:
    api_key: str
    folder_id: str
    timeout: int = 30
    use_cache: bool = True

    @classmethod
    def from_env(cls, use_cache: bool = True) -> "WordstatClient":
        _load_dotenv()
        key = os.environ.get("YANDEX_API_KEY")
        folder = os.environ.get("YANDEX_FOLDER_ID")
        if not key or not folder:
            raise WordstatError(
                "Нет YANDEX_API_KEY и/или YANDEX_FOLDER_ID. "
                "Скопируй .env.example → .env и заполни."
            )
        return cls(api_key=key, folder_id=folder, use_cache=use_cache)

    def _post(self, method: str, body: dict) -> dict:
        cache_key = None
        if self.use_cache:
            ttl = CACHE_TTL.get(method, 24)
            cache_key = _cache_key(method, body)
            hit = _cache_get(cache_key, ttl)
            if hit is not None:
                print(f"  [кеш] {method} (TTL {ttl}ч, используется кешированный ответ)", file=sys.stderr)
                return hit

        body = {**body, "folderId": self.folder_id}
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            f"{BASE_URL}/{method}", data=data, method="POST",
            headers={
                "Authorization": f"Api-Key {self.api_key}",
                "Content-Type": "application/json; charset=utf-8",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:500]
            raise WordstatError(f"HTTP {e.code} на {method}: {detail}") from e
        except urllib.error.URLError as e:
            raise WordstatError(f"Сеть: {e.reason}") from e

        if cache_key is not None:
            _cache_set(cache_key, result)

        return result

    def top_requests(self, phrase: str, num_phrases: int = 20,
                     regions: list[str] | None = None,
                     device: str = "DEVICE_ALL") -> dict:
        body: dict = {"phrase": phrase, "numPhrases": num_phrases}
        if regions:
            body["regions"] = regions
        if device != "DEVICE_ALL":
            body["devices"] = device
        return self._post("topRequests", body)

    def dynamics(self, phrase: str, from_date: str, to_date: str,
                 period: str = "PERIOD_MONTHLY",
                 regions: list[str] | None = None,
                 device: str = "DEVICE_ALL") -> dict:
        body: dict = {
            "phrase": phrase,
            "period": period,
            "fromDate": _to_rfc3339(from_date),
            "toDate": _to_rfc3339(to_date),
        }
        if regions:
            body["regions"] = regions
        if device != "DEVICE_ALL":
            body["devices"] = device
        return self._post("dynamics", body)

    def regions_distribution(self, phrase: str,
                             region_type: str = "REGION_ALL",
                             device: str = "DEVICE_ALL") -> dict:
        body: dict = {"phrase": phrase, "region": region_type}
        if device != "DEVICE_ALL":
            body["devices"] = device
        return self._post("regions", body)

    def regions_tree(self) -> dict:
        return self._post("getRegionsTree", {})


# --- Вспомогательные функции ---

def _to_rfc3339(d: str) -> str:
    return d if ("T" in d) else f"{d}T00:00:00Z"


def _last_day_of_month(d: date) -> date:
    """Вернуть последний день месяца для даты d."""
    next_month = d.replace(day=28) + timedelta(days=4)
    return next_month - timedelta(days=next_month.day)


def _auto_month_bounds(period: str, from_str: str, to_str: str) -> tuple[str, str]:
    """Для PERIOD_MONTHLY: fromDate → первый день месяца, toDate → последний."""
    if period != "PERIOD_MONTHLY":
        return from_str, to_str
    f = date.fromisoformat(from_str)
    t = date.fromisoformat(to_str)
    f_adj = f.replace(day=1)
    t_adj = _last_day_of_month(t)
    if f_adj != f:
        print(f"  [авто] fromDate: {from_str} → {f_adj} (первый день месяца)", file=sys.stderr)
    if t_adj != t:
        print(f"  [авто] toDate:   {to_str} → {t_adj} (последний день месяца)", file=sys.stderr)
    return str(f_adj), str(t_adj)


def _parse_regions(regions_str: str | None) -> list[str] | None:
    if not regions_str:
        return None
    return [r.strip() for r in regions_str.split(",") if r.strip()]


def _write_csv(path: str, rows: list[tuple], header: list[str], sep: str = ";") -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=sep)
        w.writerow(header)
        w.writerows(rows)


def _check_api_error(obj: dict, method: str) -> None:
    if "message" in obj and "results" not in obj and "regions" not in obj:
        raise WordstatError(f"API {method}: {obj.get('message')} (code={obj.get('code')})")


# --- Команды (subcommands) ---

def cmd_top(args) -> None:
    """Топ похожих запросов + ассоциации. Аналог top_requests.sh."""
    client = WordstatClient.from_env(use_cache=not args.no_cache)
    regions = _parse_regions(args.regions)
    device = DEVICE_MAP.get(args.device, "DEVICE_ALL")
    limit = min(max(args.limit, 1), 2000)

    print(f"=== Yandex Wordstat: Top Requests ===")
    print(f"  Фраза:   {args.phrase}")
    print(f"  Лимит:   {limit}")
    print(f"  Регион:  {regions or 'все'}")
    print(f"  Девайс:  {args.device}")
    print()

    data = client.top_requests(args.phrase, num_phrases=limit,
                                regions=regions, device=device)
    _check_api_error(data, "topRequests")

    total = data.get("totalCount")
    if total is not None:
        print(f"Всего показов (broad match): {_fmt(total)}")
    print()

    csv_rows: list[tuple] = []
    stdout_max = 20

    def show_section(entries: list[dict], label: str, type_tag: str) -> None:
        if not entries:
            return
        print(f"=== {label} ===")
        print()
        print(f"{'#':>4}  {'Показы':>10}  Фраза")
        print("-" * 60)
        for i, e in enumerate(entries, 1):
            phrase = e.get("phrase", "")
            count = e.get("count", "0")
            csv_rows.append((i, phrase, int(count), type_tag))
            if i <= stdout_max:
                print(f"{i:>4}  {_fmt(count):>10}  {phrase}")
            elif i == stdout_max + 1 and args.csv:
                print(f"  ... ещё {len(entries) - stdout_max} строк → {args.csv}")
        print()

    show_section(data.get("results", []), "Top Requests", "top")
    show_section(data.get("associations", []), "Associations (похожие запросы)", "assoc")

    if args.csv and csv_rows:
        _write_csv(args.csv, csv_rows, ["n", "phrase", "impressions", "type"], args.sep)
        print(f"CSV сохранён: {args.csv} ({len(csv_rows)} строк)")


def cmd_dynamics(args) -> None:
    """Динамика частотности во времени. Аналог dynamics.sh."""
    client = WordstatClient.from_env(use_cache=not args.no_cache)
    regions = _parse_regions(args.regions)
    device = DEVICE_MAP.get(args.device, "DEVICE_ALL")
    period_enum = PERIOD_MAP.get(args.period, "PERIOD_MONTHLY")

    # Дефолтные даты (год назад → сегодня), затем выравниваем по месяцам для monthly
    from_date = args.from_date or str(date.today() - timedelta(days=365))
    to_date = args.to_date or str(date.today())
    from_date, to_date = _auto_month_bounds(period_enum, from_date, to_date)

    print(f"=== Yandex Wordstat: Dynamics ===")
    print(f"  Фраза:    {args.phrase}")
    print(f"  Период:   {args.period} ({period_enum})")
    print(f"  Диапазон: {from_date} → {to_date}")
    print(f"  Регион:   {regions or 'все'}")
    print()

    data = client.dynamics(args.phrase, from_date, to_date,
                           period=period_enum, regions=regions, device=device)
    _check_api_error(data, "dynamics")

    results = data.get("results", [])
    print(f"{'Дата':<12}  {'Показы':>10}  {'Доля':>8}")
    print("-" * 35)
    for r in results:
        dt = (r.get("date") or "").split("T")[0]
        count = r.get("count", "0")
        share = r.get("share")
        share_str = f"{share:.4f}" if isinstance(share, (int, float)) else "—"
        print(f"{dt:<12}  {_fmt(count):>10}  {share_str:>8}")

    if results:
        counts = [int(r.get("count", 0)) for r in results]
        peak_idx = counts.index(max(counts))
        peak_dt = (results[peak_idx].get("date") or "").split("T")[0]
        print()
        print(f"Пик: {peak_dt} ({_fmt(max(counts))} показов)")


def cmd_regions(args) -> None:
    """Региональная статистика. Аналог regions_stats.sh."""
    client = WordstatClient.from_env(use_cache=not args.no_cache)
    device = DEVICE_MAP.get(args.device, "DEVICE_ALL")
    region_type = REGION_TYPE_MAP.get(args.region_type, "REGION_ALL")

    print(f"=== Yandex Wordstat: Regions ===")
    print(f"  Фраза:      {args.phrase}")
    print(f"  Тип:        {args.region_type}")
    print()

    data = client.regions_distribution(args.phrase, region_type=region_type, device=device)
    _check_api_error(data, "regions")

    results = sorted(data.get("results", []),
                     key=lambda r: int(r.get("count", 0)), reverse=True)

    print(f"{'Регион ID':<12}  {'Название':<25}  {'Показы':>10}  {'Аффинити':>9}")
    print("-" * 65)
    for r in results[:30]:
        rid = str(r.get("region", ""))
        count = r.get("count", "0")
        affinity = r.get("affinityIndex")
        aff_str = f"{affinity:.1f}" if isinstance(affinity, (int, float)) else "—"
        name = _region_name(rid)
        print(f"{rid:<12}  {name:<25}  {_fmt(count):>10}  {aff_str:>9}")

    print()
    print("Аффинити > 100: регион ищет запрос чаще среднего.")
    print("Для имени региона по ID: python wordstat.py tree --search <ID>")


def cmd_tree(args) -> None:
    """Справочник регионов. Аналог regions_tree.sh + search_region.sh."""
    # Статический поиск по имени (быстро, без API)
    if args.search:
        query = args.search.lower()
        found = [(rid, name) for rid, name in REGION_NAMES.items()
                 if query in name.lower() or query == rid]
        if found:
            print(f"Найдено по '{args.search}':")
            for rid, name in found:
                print(f"  {rid:>6}  {name}")
        else:
            print(f"Не найдено '{args.search}' в статическом справочнике.")
            print("Попробуй полное дерево из API: python wordstat.py tree (без --search)")
        return

    # Полное дерево из API (кеш 30 дней через _post())
    client = WordstatClient.from_env(use_cache=not getattr(args, 'no_cache', False))
    data = client.regions_tree()

    regions = data.get("regions", [])

    print()
    print("=== Страны / верхний уровень ===")
    for r in regions:
        print(f"  {str(r.get('id','')):>6}  {r.get('label', '')}")

    # Россия (225) → федеральные округа
    def find_node(nodes: list, target_id) -> dict | None:
        for n in nodes:
            if str(n.get("id")) == str(target_id):
                return n
            found = find_node(n.get("children", []), target_id)
            if found:
                return found
        return None

    russia = find_node(regions, "225")
    if russia:
        print()
        print("=== Россия (225) → федеральные округа ===")
        for r in russia.get("children", []):
            print(f"  {str(r.get('id','')):>6}  {r.get('label', '')}")

    print()
    print("Быстрый поиск: python wordstat.py tree --search \"Казань\"")
    print(f"Полное дерево в кеше: {CACHE_DIR}")


def cmd_quota(args) -> None:
    """Проверка соединения и вывод лимитов. Аналог quota.sh."""
    client = WordstatClient.from_env()
    print("Проверяю соединение с Wordstat API v2...")
    try:
        data = client.regions_tree()
        count = len(data.get("regions", []))
        print(f"✅  OK — getRegionsTree вернул {count} узлов верхнего уровня")
    except WordstatError as e:
        print(f"❌  Ошибка: {e}")

    print()
    print("=== API лимиты ===")
    print("  10 запросов/сек, 100 запросов/час")
    print()
    print("=== Ценообразование ===")
    print("  topRequests / dynamics — 20 ₽ / 1000 запросов")
    print("  regions               — 50 ₽ / 1000 запросов")
    print("  getRegionsTree        — бесплатно")
    print()
    print("=== Endpoint ===")
    print(f"  {BASE_URL}/{{topRequests|dynamics|regions|getRegionsTree}}")
    print("  Authorization: Api-Key <ключ>")
    print("  folderId: обязателен в теле каждого запроса")
    print()
    print("=== Ограничения API v2 ===")
    print("  Операторы (!, +, \"...\", (a|b), минус-слова) НЕ поддерживаются.")
    print("  phrase — только plain text, до 400 символов.")
    print("  numPhrases — обязателен для topRequests, нет дефолта в API.")


def cmd_batch(args) -> None:
    """Пакетная проверка частотности из файла с фразами (одна на строку)."""
    phrases_path = Path(args.file)
    if not phrases_path.exists():
        raise WordstatError(f"Файл не найден: {args.file}")

    phrases = [
        line.strip() for line in phrases_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    if not phrases:
        raise WordstatError("Файл пуст или содержит только комментарии.")

    client = WordstatClient.from_env(use_cache=not args.no_cache)
    regions = _parse_regions(args.regions)

    print(f"=== Batch: {len(phrases)} фраз ===")
    print()

    rows: list[tuple] = []
    for i, phrase in enumerate(phrases, 1):
        try:
            data = client.top_requests(phrase, num_phrases=1, regions=regions)
            total = int(data.get("totalCount", 0))
        except WordstatError as e:
            total = -1
            print(f"  [{i}/{len(phrases)}] ❌ {phrase}: {e}", file=sys.stderr)
        else:
            print(f"  [{i}/{len(phrases)}] {_fmt(total):>10}  {phrase}")
        rows.append((phrase, total))

    rows.sort(key=lambda r: r[1], reverse=True)
    print()
    print("=== Результат по убыванию ===")
    print()
    print(f"{'Показы':>10}  Фраза")
    print("-" * 60)
    for phrase, total in rows:
        mark = "❌" if total < 0 else ""
        print(f"{_fmt(total) if total >= 0 else '—':>10}  {phrase} {mark}")

    if args.csv:
        _write_csv(args.csv, [(p, t) for p, t in rows],
                   ["phrase", "total_count"], args.sep)
        print(f"\nCSV: {args.csv}")


# --- CLI ---

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Yandex Wordstat CLI (Yandex Cloud Search API v2)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="command", required=True)

    # top
    t = sub.add_parser("top", help="Топ похожих запросов + ассоциации")
    t.add_argument("--phrase", "-p", required=True, help="Поисковая фраза (plain text)")
    t.add_argument("--limit", "-l", type=int, default=20, help="Количество результатов (1-2000, по умолч. 20)")
    t.add_argument("--regions", "-r", default=None, help="ID регионов через запятую, напр. 213,2")
    t.add_argument("--device", "-d", default="all", choices=["all","desktop","phone","tablet"])
    t.add_argument("--csv", "-c", default=None, help="Путь для CSV-выгрузки (папку создаст сам)")
    t.add_argument("--sep", default=";", help="Разделитель CSV (по умолч. ;)")
    t.add_argument("--no-cache", action="store_true", dest="no_cache", help="Игнорировать кеш, запросить свежие данные")

    # dynamics
    d = sub.add_parser("dynamics", help="Динамика частотности во времени")
    d.add_argument("--phrase", "-p", required=True)
    d.add_argument("--from", dest="from_date", default=None, metavar="YYYY-MM-DD", help="Начало (по умолч. год назад)")
    d.add_argument("--to", dest="to_date", default=None, metavar="YYYY-MM-DD", help="Конец (по умолч. сегодня)")
    d.add_argument("--period", default="monthly", choices=["daily","weekly","monthly"])
    d.add_argument("--regions", "-r", default=None)
    d.add_argument("--device", "-d", default="all", choices=["all","desktop","phone","tablet"])
    d.add_argument("--no-cache", action="store_true", dest="no_cache", help="Игнорировать кеш")

    # regions
    r = sub.add_parser("regions", help="Региональная статистика + affinity index")
    r.add_argument("--phrase", "-p", required=True)
    r.add_argument("--region-type", "-t", default="all", choices=["all","cities","regions"])
    r.add_argument("--device", "-d", default="all", choices=["all","desktop","phone","tablet"])
    r.add_argument("--no-cache", action="store_true", dest="no_cache", help="Игнорировать кеш")

    # tree
    tr = sub.add_parser("tree", help="Справочник регионов (кеш 30 дней)")
    tr.add_argument("--search", "-s", default=None, help="Фильтр по названию города/региона")
    tr.add_argument("--no-cache", action="store_true", dest="no_cache", help="Игнорировать кеш")

    # quota
    sub.add_parser("quota", help="Проверка соединения и вывод тарифов")

    # batch
    b = sub.add_parser("batch", help="Пакетная частотность из файла (одна фраза на строку)")
    b.add_argument("file", help="Путь к файлу с фразами")
    b.add_argument("--regions", "-r", default=None)
    b.add_argument("--csv", "-c", default=None)
    b.add_argument("--sep", default=";")
    b.add_argument("--no-cache", action="store_true", dest="no_cache", help="Игнорировать кеш")

    return p


def main() -> None:
    _fix_stdout()
    parser = build_parser()
    args = parser.parse_args()
    try:
        {
            "top": cmd_top,
            "dynamics": cmd_dynamics,
            "regions": cmd_regions,
            "tree": cmd_tree,
            "quota": cmd_quota,
            "batch": cmd_batch,
        }[args.command](args)
    except WordstatError as e:
        print(f"❌ Ошибка: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
