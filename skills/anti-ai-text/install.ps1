# Установка anti-ai-text (Windows, PowerShell)
#
# Копирует скилл в ~/.claude/skills и проверяет, что Python на месте.
# Намеренно не трогает твой CLAUDE.md и settings.json: правка чужих файлов без
# спроса - худшее, что может сделать установщик.

$ErrorActionPreference = "Stop"

$here      = Split-Path -Parent $MyInvocation.MyCommand.Path
$claudeDir = if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { Join-Path $HOME ".claude" }
$skillsDir = Join-Path $claudeDir "skills"
$target    = Join-Path $skillsDir "anti-ai-text"

Write-Host ""
Write-Host "anti-ai-text — установка" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path $claudeDir)) {
    Write-Host "Не нашёл папку $claudeDir." -ForegroundColor Red
    Write-Host "Claude Code здесь не запускался? Запусти его хотя бы раз и повтори."
    Write-Host "Скрипт проверки при этом работает и без Claude Code:"
    Write-Host "   python `"$(Join-Path $here 'scripts\check_text.py')`" текст.md"
    exit 1
}

if (-not (Test-Path $skillsDir)) { New-Item -ItemType Directory -Path $skillsDir | Out-Null }

if (Test-Path $target) {
    # Папка с таким именем уже есть - не перезаписываем молча чужую работу
    Write-Host "Папка $target уже существует." -ForegroundColor Yellow
    $answer = Read-Host "Перезаписать? (y/n)"
    if ($answer -ne "y") {
        Write-Host "Отменил, ничего не изменил."
        exit 0
    }
    Remove-Item $target -Recurse -Force
}

New-Item -ItemType Directory -Path $target | Out-Null
foreach ($item in @("SKILL.md", "README.md", "rules", "scripts")) {
    Copy-Item (Join-Path $here $item) $target -Recurse
}
Write-Host "Скилл поставлен: $target" -ForegroundColor Green

# --- проверка Python ---
$python = $null
foreach ($cmd in @("python", "python3", "py")) {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) { $python = $cmd; break }
}
if ($python) {
    Write-Host "Python найден ($python) — проверка текста будет работать." -ForegroundColor Green
} else {
    Write-Host "Python не найден. Правила скилл прочитает, но скрипт не запустится." -ForegroundColor Yellow
    $python = "python"   # чтобы подсказка ниже осталась читаемой
}

Write-Host ""
Write-Host "Попробуй на своём тексте:" -ForegroundColor Cyan
Write-Host "   $python `"$(Join-Path $target 'scripts\check_text.py')`" текст.md" -ForegroundColor White
Write-Host ""
Write-Host "Скилл подхватится при следующем запуске Claude Code —"
Write-Host "включается на «почисти текст» и «звучит как нейросеть»."
Write-Host ""
