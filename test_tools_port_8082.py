# -*- coding: utf-8 -*-
"""TDD 校验：tools 下三个项目（hub / obs / email）内部端口统一为 8082，外部端口不再定义。

覆盖点：
  1) obs：server.py 默认 PORT=8082，不再残留 8088 / HOST_PORT，Dockerfile 已删除。
  2) email：app.py uvicorn 监听 8082，不再残留 5030 / HOST_PORT，Dockerfile 已删除。
  3) hub：app.py run_hub 监听 8082，不再残留 8081。
  4) docker-compose.yml 不再定义 obs/email 工具服务（改为容器卡片创建，外部端口由 control 记录）。

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

    # 1) obs：内部端口 8082，Dockerfile 已删除
    check("obs server.py default PORT=8082", 'int(os.environ.get("PORT", 8082))' in obs_py)
    check("obs server.py no HOST_PORT", "HOST_PORT" not in obs_py)
    check("obs server.py no 8088", "8088" not in obs_py)
    check("obs Dockerfile removed", not os.path.exists(os.path.join(ROOT, "tools/obs/Dockerfile")))

    # 2) email：内部端口 8082，Dockerfile 已删除
    check("email app.py uvicorn port=8082", "port=8082" in email_py)
    check("email app.py no HOST_PORT", "HOST_PORT" not in email_py)
    check("email app.py no 5030", "5030" not in email_py)
    check("email Dockerfile removed", not os.path.exists(os.path.join(ROOT, "tools/email/Dockerfile")))

    # 3) hub：内部端口 8082
    check("hub app.py run_hub port=8082", "port=8082" in hub_py)
    check("hub app.py no 8081", "8081" not in hub_py)

    # 4) docker-compose 不再定义 obs/email 工具服务（改为容器卡片创建）
    check("compose no obs-19000 service", "obs-19000" not in compose)
    check("compose no email-19001 service", "email-19001" not in compose)
    check("compose no ./tools/obs build", "./tools/obs" not in compose)
    check("compose no ./tools/email build", "./tools/email" not in compose)


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
