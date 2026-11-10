# Windows 一键启动。第一次会自动建虚拟环境并装依赖。
# 用法：右键「使用 PowerShell 运行」，或在终端执行  .\run.ps1

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

# 找一个 3.10+ 的解释器：项目用了 zip(strict=) 这类 3.10 才有的特性
$found = $null
$foundVer = ''
foreach ($cand in @('py -3.12', 'py -3.11', 'py -3.10', 'python')) {
    $parts = $cand.Split(' ')
    $exe = $parts[0]
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
    $extra = @()
    if ($parts.Length -gt 1) { $extra = $parts[1..($parts.Length - 1)] }
    $ver = & $exe @extra -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
    if ($LASTEXITCODE -eq 0 -and $ver -match '^\d+\.\d+$' -and [version]$ver -ge [version]'3.10') {
        $found = $cand
        $foundVer = $ver
        break
    }
}

if (-not $found) {
    Write-Host '[x] 找不到 Python 3.10 或更高版本。' -ForegroundColor Red
    Write-Host '    请安装 Python 3.12: https://www.python.org/downloads/' -ForegroundColor Yellow
    Write-Host '    安装时勾选 Add python.exe to PATH。' -ForegroundColor Yellow
    exit 1
}

Write-Host "[ok] 使用 Python $foundVer ($found)" -ForegroundColor Cyan
$parts = $found.Split(' ')
$exe = $parts[0]
$extra = @()
if ($parts.Length -gt 1) { $extra = $parts[1..($parts.Length - 1)] }

if (-not (Test-Path '.venv')) {
    Write-Host '[..] 创建虚拟环境 .venv' -ForegroundColor Cyan
    & $exe @extra -m venv .venv
}

$py = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
Write-Host '[..] 检查依赖' -ForegroundColor Cyan
& $py -m pip install --quiet --upgrade pip
& $py -m pip install --quiet -r requirements.txt

Write-Host '[..] 灌入深圳地点数据' -ForegroundColor Cyan
& $py -m scripts.seed

Write-Host ''
Write-Host '  就绪: http://127.0.0.1:8000' -ForegroundColor Green
Write-Host '  接口文档: http://127.0.0.1:8000/docs' -ForegroundColor Green
Write-Host '  按 Ctrl+C 停止' -ForegroundColor DarkGray
Write-Host ''

& $py -m uvicorn app.main:app --app-dir backend --reload
