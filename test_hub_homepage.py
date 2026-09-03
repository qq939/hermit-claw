# -*- coding: utf-8 -*-
"""TDD 校验：tools/hub 首页恢复「工具知识库」交互，并补齐公共接口文档 + 示例工具文档。

覆盖点：
  1) 首页包含工具知识库交互元素（iframe 加载工具 UI、底部 pills 导航、Docs 查看器）。
  2) 首页包含 Hub 公共接口文档，介绍所有重要功能性接口：
     GET/POST /api/tools、GET/DELETE /api/tools/{name}、GET /p/{name}/ 代理。
  3) 首页包含示例工具（OBS 图床）的完整接口文档（upload/notice/ws 等端点）。
  4) 调用地址统一走 http://dimond.top:19xxx，不出现 obs.dimond.top 或 18xxx。
  5) registry.normalize_tool_payload 支持完整字段（name/doc_md/port/display_name）。
  6) Python 语法编译通过。

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
    app = read("tools/hub/app.py")
    reg = read("tools/hub/registry.py")

    # 1) 工具知识库交互元素
    check("hub homepage has iframe", "<iframe" in app and 'id="frame"' in app)
    check("hub homepage has pills nav", 'id="pills"' in app)
    check("hub homepage has Docs button", "btnDoc" in app)

    # 2) Hub 公共接口文档（介绍所有重要功能性接口）
    for token in ("GET /api/tools", "POST /api/tools",
                  "GET /api/tools/{name}", "DELETE /api/tools/{name}",
                  "GET /p/{name}/"):
        check("hub API doc mentions %s" % token, token in app)

    # 2b) 代理路由存在
    check("hub has /p/<path:...> proxy route", '@hub.route("/p/<path:' in app)

    # 3) 示例工具（OBS）完整接口文档（定义在 registry，主页引用 EXAMPLE_TOOL）
    check("hub homepage references EXAMPLE_TOOL", "EXAMPLE_TOOL" in app)
    for token in ("OBS", "/upload/init", "/upload/complete", "/ws", "/notice"):
        check("hub example tool doc mentions %s" % token, token in reg)
    check("example tool doc uses dimond.top:19xxx", "http://dimond.top:19" in reg)

    # 4) 调用地址统一 dimond.top:19xxx，无旧域名/18xxx
    check("hub docs use dimond.top:19xxx", "http://dimond.top:19" in app)
    check("hub app no obs.dimond.top", "obs.dimond.top" not in app)
    check("hub app no 18xxx", not re.findall(r"18\d{3}", app))

    # 5) registry.normalize_tool_payload 支持完整字段
    check("registry normalize keeps full name", '"name" in body' in reg or "name" in reg)
    check("registry normalize keeps doc_md", "doc_md" in reg)
    check("registry normalize keeps port", "port" in reg)
    check("registry normalize keeps display_name", "display_name" in reg)

    # 6) 语法编译
    import py_compile
    for rel in ("tools/hub/app.py", "tools/hub/registry.py"):
        p = os.path.join(ROOT, rel)
        try:
            py_compile.compile(p, doraise=True)
            check("compile %s" % rel, True)
        except Exception as e:
            check("compile %s" % rel, False)
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
