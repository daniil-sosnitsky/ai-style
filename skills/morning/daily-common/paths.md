# Конфиг системы «День» — пути и идентификаторы (ШАБЛОН)

Единый источник путей для скилов `morning` и `evening`. Замени все
`<ПЛЕЙСХОЛДЕРЫ>` на свои значения. Секреты (токены, ID чатов) —
только в `.env`, никогда здесь.

## Волт Obsidian
- Корень: `<VAULT_ROOT>`
- Дневник: `<VAULT_ROOT>/daily/` → файл дня `ГГГГ-ММ-ДД.md`
- Личное: `<VAULT_ROOT>/livestyle/`
- Финансы: `<VAULT_ROOT>/investport/` (ideas.md, tasks.md, portfolio.md)
- Соцсети: `<VAULT_ROOT>/content/`
- Спорт: `<VAULT_ROOT>/sport/`
- Профиль: `<VAULT_ROOT>/profile/`

## База задач (пример — Notion)
- База «Задачи», data source: `<NOTION_TASKS_COLLECTION_ID>`
- View «📌 Сегодня» (Дата = today): `<NOTION_VIEW_TODAY_ID>`
- View «🔥 Хвосты» (Статус ≠ Готово): `<NOTION_VIEW_TAILS_ID>`
- Свойство сферы: `Сфера` (select: Работа / Личное / Финансы / Спорт).
  Если свойства нет — классифицируй задачи по тексту (см. contract.md).

> Можно заменить Notion на любой свой источник задач — правь ссылки в мостах.

## Telegram (бот для поста)
- Отправка: `python send_telegram.py <файл>`
- Токен бота и chat_id — в `.env` (см. `.env.example`). Не читать, не логировать.

## Сессии Claude Code
- Логи проектов: `~/.claude/projects/<slug>/*.jsonl`
  (slug — путь проекта с заменой разделителей на `-`).
