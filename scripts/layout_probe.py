"""用 CDP 量一下移动端布局有没有横向溢出，并找出越界的元素。

Edge 的无头模式需要比沙箱更高的权限，所以这个脚本只在「拍截图 / 查布局」时用，
不参与应用运行，也不进 requirements.txt 的运行时依赖。
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
import urllib.request

import websockets

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 9333
URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000/#demo"
WIDTH = int(sys.argv[2]) if len(sys.argv) > 2 else 430

PROBE = """
(() => {
  const vw = document.documentElement.clientWidth;
  const bad = [];
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (r.right > vw + 1 && r.width > 0) {
      bad.push({
        tag: el.tagName.toLowerCase(),
        cls: el.className && String(el.className).slice(0, 40),
        right: Math.round(r.right),
        width: Math.round(r.width),
      });
    }
  }
  return JSON.stringify({
    vw,
    scrollWidth: document.documentElement.scrollWidth,
    bodyWidth: document.body.getBoundingClientRect().width,
    offenders: bad.slice(0, 12),
  });
})()
"""


def ws_url() -> str:
    for _ in range(40):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=1) as resp:
                tabs = json.load(resp)
            for tab in tabs:
                if tab.get("type") == "page":
                    return tab["webSocketDebuggerUrl"]
        except Exception:  # noqa: BLE001 - 浏览器还没起来
            pass
        time.sleep(0.4)
    raise RuntimeError("连不上 Edge 的调试端口")


async def main() -> None:
    proc = subprocess.Popen(
        [
            EDGE,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--no-first-run",
            f"--remote-debugging-port={PORT}",
            "--user-data-dir=D:\\bisai\\.tmp\\edge-probe",
            f"--window-size={WIDTH},1700",
            URL,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        async with websockets.connect(ws_url(), max_size=8 << 20) as ws:
            await ws.send(json.dumps({"id": 1, "method": "Runtime.enable"}))
            await ws.recv()
            await asyncio.sleep(3.5)  # 等 #demo 的接口串完
            await ws.send(
                json.dumps(
                    {
                        "id": 2,
                        "method": "Runtime.evaluate",
                        "params": {"expression": PROBE, "returnByValue": True},
                    }
                )
            )
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("id") == 2:
                    print(msg["result"]["result"]["value"])
                    break
    finally:
        proc.terminate()


if __name__ == "__main__":
    asyncio.run(main())
