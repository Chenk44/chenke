<#
把本机正在跑的服务临时开到公网，让不在同一个 WiFi 的朋友也能填偏好。

    powershell -ExecutionPolicy Bypass -File .\share.ps1              # 默认：SSH 隧道（走 443）
    powershell -ExecutionPolicy Bypass -File .\share.ps1 -Cloudflare  # 备选：Cloudflare 隧道

两种方式怎么选：
    * SSH（默认，localhost.run）：只用系统的 ssh 客户端，不下载任何东西，
      走的是 443 端口——校园网、手机热点、公司网络基本都放行。缺点是免费域名
      过一段时间会轮换，长时间挂机可能中途换地址。
    * Cloudflare：速度更快、域名更稳定，但要能出 TCP/UDP 7844。
      如果日志里刷 "DialContext error: i/o timeout" 或 "no recent network activity"，
      就是这个端口被网络挡住了，换回默认的 SSH 方式。

共同点：地址每次启动都不一样，关掉窗口就断；本机服务必须一直开着。
#>

param(
    [int]$Port = 8000,
    [switch]$Cloudflare,
    [switch]$SkipServer
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

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

Write-Host ""

if ($Cloudflare) {
    $exe = Join-Path $root '.tmp\cloudflared.exe'
    $url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
    if (-not (Test-Path $exe)) {
        Write-Host "第一次用 Cloudflare 模式，下载 cloudflared（约 55 MB）…" -ForegroundColor Cyan
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
    Write-Host "正在开 Cloudflare 隧道，稍等十秒左右…" -ForegroundColor Cyan
    & $exe tunnel --url "http://127.0.0.1:$Port" --no-autoupdate
} else {
    Write-Host "正在开 SSH 隧道（localhost.run），稍等五秒左右…" -ForegroundColor Cyan
    Write-Host "地址会以 https://xxxx.lhr.life 的形式出现在下面。" -ForegroundColor DarkGray
    Write-Host ""
    $ssh = 'C:\Windows\System32\OpenSSH\ssh.exe'
    if (-not (Test-Path $ssh)) { $ssh = 'ssh' }
    & $ssh -o StrictHostKeyChecking=no -o ServerAliveInterval=20 -R "80:127.0.0.1:$Port" nokey@localhost.run
}
