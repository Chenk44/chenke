# Windows 一键启动。第一次会自动建虚拟环境并装依赖。
# 用法：右键「使用 PowerShell 运行」，或在终端执行  .\run.ps1

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not (Test-Path '.venv')) {
    Write-Host '→ 创建虚拟环境 .venv ...' -ForegroundColor Cyan
    python -m venv .venv
}

$py = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
Write-Host '→ 检查依赖 ...' -ForegroundColor Cyan
& $py -m pip install --quiet -r requirements.txt

Write-Host '→ 灌入深圳地点数据 ...' -ForegroundColor Cyan
& $py -m scripts.seed

Write-Host ''
Write-Host '  就绪：http://127.0.0.1:8000' -ForegroundColor Green
Write-Host '  接口文档：http://127.0.0.1:8000/docs' -ForegroundColor Green
Write-Host ''

& $py -m uvicorn app.main:app --app-dir backend --reload
