# -*- coding: utf-8 -*-
"""TDD 校验：注册按钮 + 端口按钮 UI 与后端端口映射。

覆盖点：
  1) UI: 注册 checkbox 替换为按钮样式（.register-btn）。
  2) UI: 新增端口按钮（.port-btn）。
  3) UI: register-btn[data-registered] 和 port-btn[data-ports] 属性存在。
  4) 后端: _port_config_path / _read_port_config / _write_port_config 函数存在。
  5) 后端: POST /api/agents/<name>/ports 接口存在。
  6) create_agent 与 recreate_agent 读取 config/port.txt 合并端口。
  7) CSS 样式存在（.register-btn / .port-btn）。
  8) 编译通过。

超时机制：整个校验在守护线程中执行，主线程 join(timeout)，超时判失败。
"""
import os
import re
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

    # 1) 注册按钮存在，checkbox 不存在
    check("register checkbox removed", "type=\"checkbox\" class=\"register-toggle\"" not in app)
    check("register-btn exists", 'class="register-btn"' in app)
    check("register-btn has data-registered attr", 'data-registered=' in app)

    # 2) 端口按钮存在
    check("port-btn exists", 'class="port-btn"' in app)
    check("port-btn has data-ports attr", 'data-ports=' in app)

    # 3) JS 处理逻辑存在
    check("register btn click handler", "registerBtn.onclick" in app)
    check("port btn click handler", "portBtn.onclick" in app)
    check("port prompt message", "container_port:host_port" in app)
    check("port fetch POST /ports", "/api/agents/" in app and "/ports" in app)

    # 4) 后端端口函数存在
    check("_port_config_path exists", "def _port_config_path" in app)
    check("_read_port_config exists", "def _read_port_config" in app)
    check("_write_port_config exists", "def _write_port_config" in app)
    # 4b) _port_config_path 在 create_app 内、可访问 app.config
    check("_port_config_path uses app.config", 'host_ws = app.config["HOST_WORKSPACES_ROOT"]' in app)

    # 5) POST ports 接口
    check("POST /api/agents/<name>/ports", '@app.post("/api/agents/<path:name>/ports")' in app)
    check("ports API calls recreate_agent", "recreate_agent(name)" in app)

    # 6) create_agent 读取 config/port.txt
    check("create_agent reads port config", "_read_port_config" in app)
    check("create_agent merges port_map", "port_map[" in app)

    # 7) recreate_agent 读取 config/port.txt
    # 找 recreate_agent 里的 ports= 行
    recreate_ports = re.search(r'def recreate_agent.*?ports=\{', app, re.DOTALL)
    check("recreate_agent uses port config", recreate_ports is not None)

    # 8) CSS 样式
    check("register-btn CSS exists", ".register-btn {" in app)
    check("register-btn green for registered", "16a34a" in app)  # 绿色
    check("port-btn CSS exists", ".port-btn {" in app)
    # 8b) .actions 必须允许换行，否则窄窗口下末尾按钮被 .card{overflow:hidden} 裁掉
    actions_css = re.search(r"\.actions \{\{([^}]*)\}\}", app)
    check(".actions has flex-wrap", actions_css is not None and "flex-wrap" in actions_css.group(1))

    # 9) 编译通过
    import py_compile
    p = os.path.join(ROOT, "control", "app.py")
    try:
        py_compile.compile(p, doraise=True)
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
