# -*- coding: utf-8 -*-
r"""hub 源码位置整理的 TDD 测试（纯标准库，自带超时机制）。

验证 hub 源码已从 control/ 抽离到 tools/hub/ 目录：
  - tools/hub/registry.py 承载注册表逻辑（原 control/tools_hub.py）
  - tools/hub/app.py 承载 Hub Flask app（原 control/app.py 内的 create_tools_hub_app）
  - control/app.py 通过 `from tools.hub` 引用，不再内联定义 create_tools_hub_app
  - control/tools_hub.py 已移除
  - control/Dockerfile 与 docker-compose.yml 调整 build context 以 COPY tools/hub
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


def exists(rel):
    return os.path.isfile(os.path.join(ROOT, rel))


def main():
    # --- tools/hub 目录存在且含核心源码 ---
    assert exists("tools/hub/__init__.py"), "应存在 tools/hub/__init__.py"
    assert exists("tools/hub/registry.py"), "应存在 tools/hub/registry.py"
    assert exists("tools/hub/app.py"), "应存在 tools/hub/app.py"

    registry_src = read("tools/hub/registry.py")
    app_hub_src = read("tools/hub/app.py")

    # 注册表逻辑已迁移
    for token in ["derive_tool_name", "build_tool_record", "register_tool_file",
                  "list_tools_file", "unregister_tool_file"]:
        assert token in registry_src, "registry.py 应包含 %s" % token

    # Hub Flask app 已迁移
    for token in ["create_tools_hub_app", "/api/tools", "make_server", "8081"]:
        assert token in app_hub_src, "app.py 应包含 %s" % token

    # --- control/app.py：不再内联定义，改为 import tools.hub ---
    app_src = read("control/app.py")
    assert "def create_tools_hub_app" not in app_src, "control/app.py 不应再内联定义 create_tools_hub_app"
    assert "from tools.hub" in app_src, "control/app.py 应从 tools.hub 导入 hub 源码"
    assert "import tools_hub" not in app_src, "control/app.py 不应再顶层 import tools_hub"

    # --- control/tools_hub.py 已移除 ---
    assert not exists("control/tools_hub.py"), "control/tools_hub.py 应已删除"

    # --- control/Dockerfile：COPY tools/hub ---
    dockerfile = read("control/Dockerfile")
    assert "tools/hub" in dockerfile, "control/Dockerfile 应 COPY tools/hub"

    # --- docker-compose.yml：control build context 指向项目根 ---
    compose = read("docker-compose.yml")
    assert "dockerfile: control/Dockerfile" in compose, "control 服务应指定 dockerfile: control/Dockerfile"

    print("PASS: hub 源码已整理到 tools/hub")


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
