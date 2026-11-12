<#
把本机正在跑的服务临时开到公网，让不在同一个 WiFi 的朋友也能填偏好。

用法（在仓库根目录）：
    powershell -ExecutionPolicy Bypass -File .\share.ps1

它会做三件事：
    1. 服务没起来就先起（后台窗口，最小化）
    2. 第一次运行时自动下载 cloudflared.exe 到 .tmp\（约 55 MB）
    3. 开一条 Cloudflare 临时隧道，把公网地址打印出来

注意：
    * 地址每次启动都不一样（形如 https://xxx-yyy-zzz.trycloudflare.com）
    * 关掉这个窗口，链接立刻失效；你的电脑关机也一样
    * 这是给「今晚就要收偏好」用的，不是给评委长期访问用的——
      长期请按 README 第八节部署到云服务器
#>

param(
    [int]$Port = 8000,
    [switch]$SkipServer
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$exe = Join-Path $root '.tmp\cloudflared.exe'
$url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"

function Test-Health {
    param([int]$p)
    try {
        $r = Invoke-RestMethod "http://127.0.0.1:$p/api/health" -TimeoutSec 3
        return [bool]$r.status
    } catch {
        return $false
    }
}

if (-not $SkipServer -and -not (Test-Health -p $Port)) {
    $py = Join-Path $root '.venv\Scripts\python.exe'
    if (-not (Test-Path $py)) {
        throw "找不到 $py —— 先按 README 建好虚拟环境（python -m venv .venv）"
    }
    Write-Host "服务没在跑，先起一个（端口 $Port）…" -ForegroundColor Cyan
    Start-Process -FilePath $py `
        -ArgumentList '-m', 'uvicorn', 'app.main:app', '--app-dir', 'backend', '--host', '0.0.0.0', '--port', "$Port" `
        -WorkingDirectory $root -WindowStyle Minimized

    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        if (Test-Health -p $Port) { break }
    }
    if (-not (Test-Health -p $Port)) { throw "服务在 30 秒内没起来，先手动跑一次看看报什么错" }
    Write-Host "服务已就绪。" -ForegroundColor Green
}

if (-not (Test-Path $exe)) {
    Write-Host "第一次运行，下载 cloudflared（约 55 MB）…" -ForegroundColor Cyan
    $old = $ProgressPreference
    $ProgressPreference = 'SilentlyContinue'
    try {
        Invoke-WebRequest -Uri $url -OutFile $exe -TimeoutSec 300
    } catch {
        $ProgressPreference = $old
        throw "下载失败（$($_.Exception.Message)）。可以手动下载后放到 .tmp\cloudflared.exe：`n  $url"
    }
    $ProgressPreference = $old
    Write-Host "下载完成。" -ForegroundColor Green
}

Write-Host ""
Write-Host "正在开隧道，稍等十秒左右，下面这个地址就是发给朋友的链接：" -ForegroundColor Cyan
Write-Host "（地址是 https://xxxx.trycloudflare.com 这种，Ctrl+C 或关窗口就断）" -ForegroundColor DarkGray
Write-Host ""

# 用 http2 而不是默认的 quic：笔记本休眠或切换网络之后，quic 的 UDP 连接经常半死，
# 表现为日志里一直 "Retrying connection"、外网打不开但本机好好的；http2 走 TCP，重连快得多。
& $exe tunnel --url "http://127.0.0.1:$Port" --no-autoupdate --protocol http2
