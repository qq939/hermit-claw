# -*- coding: utf-8 -*-
"""TDD 校验：control 创建/重建容器时，把宿主机 tools 目录挂载到每个容器卡片工作目录下。

覆盖点：
  1) control/app.py 声明 HOST_TOOLS_ROOT_ENV = "HOST_TOOLS_ROOT"。
  2) create_app 里解析宿主机 tools 根目录（默认由 HOST_WORKSPACES_ROOT 推导 <项目根>/tools）。
  3) create_agent 与 recreate_agent 两处 volumes 都包含 tools 挂载，
     挂载目标为 project_path_for_agent_type(agent_type) + "/tools"。
  4) Python 语法编译通过。

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

    # 1) 全局环境变量声明
    check("control/app.py declares HOST_TOOLS_ROOT_ENV", 'HOST_TOOLS_ROOT_ENV = "HOST_TOOLS_ROOT"' in app)

    # 2) create_app 解析宿主机 tools 根目录（默认 dirname(host_ws)/tools）
    check("create_app resolves HOST_TOOLS_ROOT from env",
          'app.config["HOST_TOOLS_ROOT"] = os.environ.get(HOST_TOOLS_ROOT_ENV)' in app)
    check("create_app derives tools under project root",
          'os.path.join(os.path.dirname(host_ws), "tools")' in app)

    # 3) create_agent / recreate_agent 两处都读取 host_tools_root
    check("create_agent reads host_tools_root",
          app.count('host_tools_root = app.config["HOST_TOOLS_ROOT"]') >= 1)
    check("recreate_agent reads host_tools_root",
          app.count('host_tools_root = app.config["HOST_TOOLS_ROOT"]') >= 2)

    # 4) 两处 volumes 都挂载 tools 到工作目录下的 tools 子目录
    tools_bind = 'f"{host_tools_root}": {"bind": project_path_for_agent_type(agent_type) + "/tools"'
    check("create_agent volumes mount tools", app.count(tools_bind) >= 1)
    check("recreate_agent volumes mount tools", app.count(tools_bind) >= 2)

    # 5) 语法编译
    import py_compile
    try:
        py_compile.compile(os.path.join(ROOT, "control/app.py"), doraise=True)
        check("compile control/app.py", True)
    except Exception as e:
        check("compile control/app.py", False)
        print("   -> %s" % e, flush=True)


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
