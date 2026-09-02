# -*- coding: utf-8 -*-
r"""端口统一 + 19081 Hub 的源码级 TDD 测试（纯标准库，自带超时机制）。

验证 control/app.py 与 docker-compose.yml 已按要求调整：
  - 工具类与普通容器不再按端口段区分（移除 TOOL_START_PORT / TOOL_END_PORT / find_tool_port / is_tool 跳过）
  - 所有容器统一走 find_next_port()（19081+ 段）
  - 引入 tools_hub 模块，并暴露 /api/tools 与卡片注册接口
  - 19081 Hub 由 control 进程内第二个服务（8081）提供
  - docker-compose.yml 为 control 增加 18081:8081 映射
"""
import os
import sys
import threading

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))


def read(rel):
    with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as f:
        return f.read()


def main():
    app_src = read("control/app.py")
    compose = read("docker-compose.yml")

    # --- 端口段不再区分 ---
    assert "TOOL_START_PORT" not in app_src, "应移除工具端口段起点 TOOL_START_PORT"
    assert "TOOL_END_PORT" not in app_src, "应移除工具端口段终点 TOOL_END_PORT"
    assert "find_tool_port" not in app_src, "应移除 find_tool_port"
    assert "if is_tool(c):" not in app_src, "display_containers 不应跳过工具容器"

    # --- 统一端口分配 ---
    assert "host_port = find_next_port()" in app_src, "create_agent 应统一走 find_next_port()"

    # --- 引入 tools_hub 模块 ---
    assert "import tools_hub" in app_src, "app.py 应引入 tools_hub 模块"

    # --- 19081 Hub 服务（第二个服务 8081）---
    assert "/api/tools" in app_src, "应存在 /api/tools 路由"
    assert 'make_server("0.0.0.0", 8081' in app_src, "Hub 服务应监听 8081"

    # --- 卡片注册接口 ---
    assert "register_tool_file" in app_src, "卡片注册应调用 tools_hub.register_tool_file"
    assert "/register" in app_src, "应存在容器卡片注册接口"

    # --- docker-compose.yml：control 增加 18081:8081 映射 ---
    assert '"18081:8081"' in compose, "docker-compose.yml 应包含 18081:8081 映射"

    print("PASS: 端口统一 + 19081 Hub 源码结构正确")


if __name__ == "__main__":
    TIMEOUT = 30
    errors = {}

    def run():
        try:
            main()
        except Exception as exc:  # noqa: BLE001
            errors["e"] = exc

    worker = threading.Thread(target=run)
    worker.start()
    worker.join(TIMEOUT)
    if worker.is_alive():
        print("FAIL: 测试超时（%ds）" % TIMEOUT)
        sys.exit(1)
    if errors:
        print("FAIL:", errors["e"])
        sys.exit(1)
    print("ALL TESTS PASSED")
