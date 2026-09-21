#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Простой отправщик утреннего поста в Telegram.

Использование:
    python send_telegram.py <путь-к-файлу-с-текстом>

Файл содержит готовый текст поста в HTML-разметке Telegram.
Токен бота и chat_id берутся из окружения или из .env рядом:
    TELEGRAM_BOT_TOKEN=...
    TELEGRAM_CHAT_ID=...
Секреты только в .env, никогда в коде и не в гите.
"""
import sys, os, json, urllib.request, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))


def load_env():
    env = dict(os.environ)
    envp = os.path.join(HERE, ".env")
    if os.path.exists(envp):
        for line in open(envp, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env


def main():
    if len(sys.argv) < 2:
        print("Укажи файл с текстом поста"); sys.exit(1)
    with open(sys.argv[1], encoding="utf-8") as f:
        text = f.read()

    env = load_env()
    token = env.get("TELEGRAM_BOT_TOKEN")
    chat_id = env.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Нет TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID (окружение или .env)"); sys.exit(1)

    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=30) as r:
        resp = json.loads(r.read().decode())
    print("OK" if resp.get("ok") else "Ошибка: " + json.dumps(resp, ensure_ascii=False))


if __name__ == "__main__":
    main()
