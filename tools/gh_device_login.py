# -*- coding: utf-8 -*-
"""GitHub 设备码授权（device flow）。

和 gh auth login --web 是同一套流程，但把设备码明确打印出来，便于在
非交互终端里由人手动完成授权。

用法：
    python gh_device_login.py            # 申请设备码，打印链接和验证码
    python gh_device_login.py poll [秒]  # 轮询换 token，并灌进 gh 的凭证存储
"""
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request

# gh CLI 自带的 OAuth App client id（从 gh.exe 里提取，与 gh auth login 一致）
CLIENT_ID = "178c6fc778ccc68e1d6a"
SCOPE = "repo read:org gist workflow"
HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "_device.json")
GH = os.environ.get("RYG_GH") or r"C:\Users\mattq\.workbuddy\binaries\gh\bin\gh.exe"

# github.com 主站在本机直连会被掐断，得借本机代理出去（api.github.com 则相反）。
# 用 RYG_PROXY 覆盖；置空表示直连。
PROXY = os.environ.get("RYG_PROXY", "http://127.0.0.1:10808")


def _opener():
    if not PROXY:
        return urllib.request.build_opener()
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))


def post(url, params):
    req = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(params).encode("utf-8"),
        headers={"Accept": "application/json", "User-Agent": "renyugou-publish"},
    )
    with _opener().open(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def start():
    d = post("https://github.com/login/device/code",
             {"client_id": CLIENT_ID, "scope": SCOPE})
    json.dump(d, open(STORE, "w", encoding="utf-8"))
    print("URL=" + d["verification_uri"])
    print("CODE=" + d["user_code"])
    print("EXPIRES=%s INTERVAL=%s" % (d.get("expires_in"), d.get("interval")))
    return 0


def poll(max_wait=600):
    d = json.load(open(STORE, encoding="utf-8"))
    interval = max(5, int(d.get("interval", 5)))
    deadline = time.time() + max_wait
    while time.time() < deadline:
        time.sleep(interval)
        r = post("https://github.com/login/oauth/access_token",
                 {"client_id": CLIENT_ID, "device_code": d["device_code"],
                  "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
        if r.get("access_token"):
            tok = r["access_token"]
            p = subprocess.run(
                [GH, "auth", "login", "--hostname", "github.com", "--with-token"],
                input=tok.encode("utf-8"),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            print("TOKEN_OK")
            print(p.stdout.decode("utf-8", "replace").strip())
            return 0
        err = r.get("error")
        if err == "authorization_pending":
            print("pending", flush=True)
            continue
        if err == "slow_down":
            interval += 5
            continue
        print("ERR=" + json.dumps(r, ensure_ascii=False))
        return 2
    print("TIMEOUT")
    return 3


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "poll":
        sys.exit(poll(int(sys.argv[2]) if len(sys.argv) > 2 else 600))
    sys.exit(start())
