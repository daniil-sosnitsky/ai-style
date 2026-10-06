#!/usr/bin/env bash
# Установка anti-ai-text (Linux, macOS)
#
# Копирует скилл в ~/.claude/skills и проверяет, что Python на месте.
# Намеренно не трогает твой CLAUDE.md и settings.json: правка чужих файлов без
# спроса - худшее, что может сделать установщик.

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
claude_dir="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
skills_dir="$claude_dir/skills"
target="$skills_dir/anti-ai-text"

echo
echo "anti-ai-text — установка"
echo

if [ ! -d "$claude_dir" ]; then
    echo "Не нашёл папку $claude_dir."
    echo "Claude Code здесь не запускался? Запусти его хотя бы раз и повтори."
    echo "Скрипт проверки при этом работает и без Claude Code:"
    echo "   python3 \"$here/scripts/check_text.py\" текст.md"
    exit 1
fi

mkdir -p "$skills_dir"

if [ -d "$target" ]; then
    # Папка с таким именем уже есть - не перезаписываем молча чужую работу
    echo "Папка $target уже существует."
    read -r -p "Перезаписать? (y/n) " answer
    if [ "$answer" != "y" ]; then
        echo "Отменил, ничего не изменил."
        exit 0
    fi
    rm -rf "$target"
fi

mkdir -p "$target"
cp "$here/SKILL.md" "$here/README.md" "$target/"
cp -r "$here/rules" "$here/scripts" "$target/"
echo "Скилл поставлен: $target"

python_cmd=""
for cmd in python3 python; do
    if command -v "$cmd" >/dev/null 2>&1; then python_cmd="$cmd"; break; fi
done

if [ -n "$python_cmd" ]; then
    echo "Python найден ($python_cmd) — проверка текста будет работать."
else
    echo "Python не найден. Правила скилл прочитает, но скрипт не запустится."
    python_cmd="python3"   # чтобы подсказка ниже осталась читаемой
fi

echo
echo "Попробуй на своём тексте:"
echo "   $python_cmd \"$target/scripts/check_text.py\" текст.md"
echo
echo "Скилл подхватится при следующем запуске Claude Code —"
echo "включается на «почисти текст» и «звучит как нейросеть»."
echo
