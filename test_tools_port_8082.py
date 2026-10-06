# -*- coding: utf-8 -*-
"""TDD 校验：tools 下三个项目（hub / obs / email）内部端口统一为 8082；
obs/email 作为 18000 端口段的 compose 服务，宿主机端口固定 18000 / 18001。

覆盖点：
  1) obs：server.py 默认 PORT=8082，Dockerfile 存在（compose 服务）。
  2) email：app.py uvicorn 监听 8082，Dockerfile 存在（compose 服务）。
  3) hub：app.py run_hub 监听 8082。
  4) docker-compose.yml 定义 obs-18000 / email-18001 服务（18000:8082 / 18001:8082）。

超时机制：整个校验在守护线程中执行，主线程 join(timeout)，超时判失败。
"""
import os
import sys
import threading

TIMEOUT_SECONDS = 60
ROOT = os.path.dirname(os.path.abspath(__file__))

failures = []


def check(name, ok):
    print(("[PASS] " if ok else "[FAIL] ") + name, flush=True)
    if not ok:
        failures.append(name)


def read(rel):
    p = os.path.join(ROOT, rel)
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


def run():
    obs_py = read("tools/obs/server.py")
    email_py = read("tools/email/app.py")
    hub_py = read("tools/hub/app.py")
    compose = read("docker-compose.yml")

    # 1) obs：内部端口 8082，Dockerfile 存在（18000 compose 服务）
    check("obs server.py default PORT=8082", 'int(os.environ.get("PORT", 8082))' in obs_py)
    check("obs server.py no 8088", "8088" not in obs_py)
    check("obs Dockerfile exists", os.path.exists(os.path.join(ROOT, "tools/obs/Dockerfile")))

    # 2) email：内部端口 8082，Dockerfile 存在（18001 compose 服务）
    check("email app.py uvicorn port=8082", "port=8082" in email_py)
    check("email app.py no 5030", "5030" not in email_py)
    check("email Dockerfile exists", os.path.exists(os.path.join(ROOT, "tools/email/Dockerfile")))

    # 3) hub：内部端口 8082（注意 18xxx 端口里含子串 8081，故只查 port=8081）
    check("hub app.py run_hub port=8082", "port=8082" in hub_py)
    check("hub app.py no port=8081", "port=8081" not in hub_py)

    # 4) docker-compose 定义 obs-18000 / email-18001（18000 端口段的 compose 服务）
    check("compose has obs-18000 service", "obs-18000:" in compose)
    check("compose has email-18001 service", "email-18001:" in compose)
    check("compose maps obs 18000:8082", "18000:8082" in compose)
    check("compose maps email 18001:8082", "18001:8082" in compose)
    check("compose builds ./tools/obs", "./tools/obs" in compose)
    check("compose builds ./tools/email", "./tools/email" in compose)


if __name__ == "__main__":
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(TIMEOUT_SECONDS)
    if t.is_alive():
        print("FAIL: test timed out after %ds" % TIMEOUT_SECONDS, flush=True)
        sys.exit(1)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)), flush=True)
        sys.exit(1)
    print("ALL CHECKS PASSED", flush=True)
    sys.exit(0)
