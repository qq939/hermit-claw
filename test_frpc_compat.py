# -*- coding: utf-8 -*-
"""TDD 校验：control 创建容器卡片时 frpc 规则同步兼容 frp / frpc 两种目录。

覆盖点：
  1) control/app.py 兼容 frp 与 frpc 两种配置目录（FRPC_PATH / FRPC_ALT_PATH）。
  2) control/app.py 提供 resolve_frpc_config_path 动态探测实际存在的 frpc.ini。
  3) add_frpc_rule 每次写入前动态解析路径，不再依赖固定 FRPC_CONFIG_PATH。
  4) docker-compose.yml 同时挂载 ../frpc 与 ../frp 两个目录。

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
    app = read("control/app.py")
    compose = read("docker-compose.yml")

    # 1) 兼容两种目录
    check("control FRPC_PATH frpc dir", 'FRPC_PATH = "/Users/jimjiang/Downloads/frpc"' in app)
    check("control FRPC_ALT_PATH frp dir", 'FRPC_ALT_PATH = "/Users/jimjiang/Downloads/frp"' in app)

    # 2) 动态探测函数
    check("control has resolve_frpc_config_path", "def resolve_frpc_config_path" in app)
    check("control resolve probes frpc.ini", 'os.path.join(d, "frpc.ini")' in app)

    # 3) add_frpc_rule 动态解析，不再依赖固定 FRPC_CONFIG_PATH
    check("control no fixed FRPC_CONFIG_PATH", "FRPC_CONFIG_PATH" not in app)
    check("control add_frpc_rule uses cfg_path", "cfg_path = resolve_frpc_config_path()" in app)

    # 4) docker-compose 同时挂载两种目录
    check("compose mounts ../frpc", "${PWD}/../frpc:/Users/jimjiang/Downloads/frpc" in compose)
    check("compose mounts ../frp", "${PWD}/../frp:/Users/jimjiang/Downloads/frp" in compose)


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
