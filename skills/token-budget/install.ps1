# Установка token-budget (Windows, PowerShell)
#
# Ставит четыре субагента в ~/.claude/agents и показывает, что делать дальше.
# Намеренно не трогает твой CLAUDE.md и settings.json: правка чужих файлов без
# спроса — худшее, что может сделать установщик. Правила ты вставишь сам.

$ErrorActionPreference = "Stop"

$here      = Split-Path -Parent $MyInvocation.MyCommand.Path
$claudeDir = if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { Join-Path $HOME ".claude" }
$agentsDir = Join-Path $claudeDir "agents"

Write-Host ""
Write-Host "token-budget — установка" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path $claudeDir)) {
    Write-Host "Не нашёл папку $claudeDir." -ForegroundColor Red
    Write-Host "Claude Code здесь не запускался? Запусти его хотя бы раз и повтори."
    exit 1
}

# --- субагенты ---
if (-not (Test-Path $agentsDir)) { New-Item -ItemType Directory -Path $agentsDir | Out-Null }

$installed = @()
$skipped   = @()
foreach ($file in Get-ChildItem (Join-Path $here "agents") -Filter *.md) {
    $target = Join-Path $agentsDir $file.Name
    if (Test-Path $target) {
        # Агент с таким именем уже есть — не перезаписываем чужую работу
        $skipped += $file.BaseName
    } else {
        Copy-Item $file.FullName $target
        $installed += $file.BaseName
    }
}

if ($installed) { Write-Host "Поставлены субагенты: $($installed -join ', ')" -ForegroundColor Green }
if ($skipped)   { Write-Host "Уже были на месте (не трогал): $($skipped -join ', ')" -ForegroundColor Yellow }

# --- проверка Python ---
$python = $null
foreach ($cmd in @("python", "python3", "py")) {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) { $python = $cmd; break }
}
if ($python) {
    Write-Host "Python найден ($python) — отчёты будут работать." -ForegroundColor Green
} else {
    Write-Host "Python не найден. Субагенты работают и без него, но отчёты не запустятся." -ForegroundColor Yellow
    $python = "python"   # чтобы подсказки ниже остались читаемыми
}

# --- что дальше ---
$rules = Join-Path $here "rules\CLAUDE.snippet.md"
$script = Join-Path $here "scripts\token_report.py"

Write-Host ""
Write-Host "Осталось два шага:" -ForegroundColor Cyan
Write-Host ""
Write-Host "1. Вставь правила в свой CLAUDE.md (целиком, править не надо):"
Write-Host "   $rules" -ForegroundColor White
Write-Host "   Глобальный файл: $(Join-Path $claudeDir 'CLAUDE.md')"
Write-Host ""
Write-Host "2. Посмотри, куда уходят твои токены:"
Write-Host "   $python `"$script`"            — четыре статьи расхода" -ForegroundColor White
Write-Host "   $python `"$script`" --startup  — цена входа в сессию" -ForegroundColor White
Write-Host "   $python `"$script`" --growth   — как дорожает сессия" -ForegroundColor White
Write-Host ""
Write-Host "Субагенты подхватятся при следующем запуске Claude Code."
Write-Host ""
