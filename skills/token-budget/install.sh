#!/usr/bin/env bash
# Установка token-budget (macOS, Linux)
#
# Ставит четыре субагента в ~/.claude/agents и показывает, что делать дальше.
# Намеренно не трогает твой CLAUDE.md и settings.json: правка чужих файлов без
# спроса — худшее, что может сделать установщик. Правила ты вставишь сам.

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
claude_dir="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
agents_dir="$claude_dir/agents"

green() { printf '\033[32m%s\033[0m\n' "$1"; }
yellow() { printf '\033[33m%s\033[0m\n' "$1"; }
cyan() { printf '\033[36m%s\033[0m\n' "$1"; }

echo
cyan "token-budget — установка"
echo

if [ ! -d "$claude_dir" ]; then
  printf '\033[31m%s\033[0m\n' "Не нашёл папку $claude_dir."
  echo "Claude Code здесь не запускался? Запусти его хотя бы раз и повтори."
  exit 1
fi

# --- субагенты ---
mkdir -p "$agents_dir"

installed=() ; skipped=()
for file in "$here"/agents/*.md; do
  name="$(basename "$file" .md)"
  if [ -e "$agents_dir/$(basename "$file")" ]; then
    # Агент с таким именем уже есть — не перезаписываем чужую работу
    skipped+=("$name")
  else
    cp "$file" "$agents_dir/"
    installed+=("$name")
  fi
done

[ ${#installed[@]} -gt 0 ] && green "Поставлены субагенты: ${installed[*]}"
[ ${#skipped[@]} -gt 0 ] && yellow "Уже были на месте (не трогал): ${skipped[*]}"

# --- проверка Python ---
python=""
for cmd in python3 python; do
  if command -v "$cmd" >/dev/null 2>&1; then python="$cmd"; break; fi
done
if [ -n "$python" ]; then
  green "Python найден ($python) — отчёты будут работать."
else
  yellow "Python не найден. Субагенты работают и без него, но отчёты не запустятся."
  python="python3"
fi

# --- что дальше ---
echo
cyan "Осталось два шага:"
echo
echo "1. Вставь правила в свой CLAUDE.md (целиком, править не надо):"
echo "   $here/rules/CLAUDE.snippet.md"
echo "   Глобальный файл: $claude_dir/CLAUDE.md"
echo
echo "2. Посмотри, куда уходят твои токены:"
echo "   $python \"$here/scripts/token_report.py\"            — четыре статьи расхода"
echo "   $python \"$here/scripts/token_report.py\" --startup  — цена входа в сессию"
echo "   $python \"$here/scripts/token_report.py\" --growth   — как дорожает сессия"
echo
echo "Субагенты подхватятся при следующем запуске Claude Code."
echo
