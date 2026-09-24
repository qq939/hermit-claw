# -*- coding: utf-8 -*-
"""TDD 校验：control 面板「注册」与 19081 Hub 必须共用同一份注册表。

背景（踩过的两个坑）：
  1) 注册表分叉：control 写 /config/tools_registry.json（宿主机 config/），而 19081 Hub 卡片
     的容器里根本没有 /config，它的 server.js 就把路径改到自己的 logs/ 下 →
     面板注册成功的卡片在 Hub 首页/接口里看不到。
  2) 卡片挂载指错目录：compose 里 HOST_CONFIG_ROOT=${PWD}/config，${PWD} 取的是「执行 compose
     那个 shell 的环境变量」。只要从别的目录跑 compose，HOST_* 就会被烤成那个目录，
     之后新建/重建的卡片会把 /agent-config、/config、workspace 全挂到错误甚至空的目录上
     （实测：Hub 卡片挂到空目录后 web 服务直接起不来）。

覆盖点：
  A) 静态
     1) control 把 tools_hub.TOOLS_REGISTRY_PATH 指到 /config/registry/tools_registry.json。
     2) create_agent / recreate_agent 都挂了注册表卷（_registry_volume → 卡片 /config）。
     3) control 用「自己容器的挂载」解析宿主机根目录（不再无条件信 ${PWD}）。
     4) registry.py 的容器内默认路径仍是 /config/tools_registry.json。
  B) 线上（需要 docker + 面板/Hub 在跑，缺任一则 SKIP）
     5) 宿主机 config/registry/tools_registry.json 存在。
     6) control 容器的 /config、/workspaces 挂载源 = 本仓库的 config/、workspaces/。
     7) 每张卡片的 /agent-config 与 workspace 挂载源都在本仓库下（防止挂到别的目录）。
     8) Hub 卡片挂到了 config/registry，且容器内 /config/tools_registry.json 可读。
     9) Hub /api/tools 的工具集合 == 宿主机注册表的集合（无分叉）。
    10) 闭环：面板注册 19088-test → Hub 立刻能看到 → 注销后消失（用后即还原）。

超时机制：整个校验在守护线程中执行，主线程 join(timeout)，超时判失败。
"""
import json
import os
import subprocess
import sys
import threading
import urllib.parse
import urllib.request

TIMEOUT_SECONDS = 180
ROOT = os.path.dirname(os.path.abspath(__file__))
CONTROL = os.environ.get("CONTROL_URL", "http://localhost:19080")
HUB = os.environ.get("HUB_URL", "http://localhost:19081")
CONTROL_CONTAINER = "hermit-control-19080"
HUB_CONTAINER = "19081-hub"
E2E_CARD = "19088-test"          # 闭环测试用（测完会注销，恢复原状）
REGISTRY_HOST = os.path.join(ROOT, "config", "registry", "tools_registry.json")

failures = []
skips = []

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def check(name, ok):
    print(("[PASS] " if ok else "[FAIL] ") + name, flush=True)
    if not ok:
        failures.append(name)


def skip(name, reason):
    print("[SKIP] %s (%s)" % (name, reason), flush=True)
    skips.append(name)


def norm(path):
    return (path or "").replace("\\", "/").rstrip("/").lower()


def docker(*args, **kw):
    try:
        p = subprocess.run(["docker", *args], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=kw.get("timeout", 30))
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()
    except Exception as e:
        return 1, "", str(e)


def container_mounts(name):
    rc, out, err = docker("inspect", name, "--format", "{{range .Mounts}}{{.Source}}|{{.Destination}}\n{{end}}")
    mounts = {}
    if rc != 0:
        return mounts
    for line in out.splitlines():
        if "|" in line:
            src, dest = line.split("|", 1)
            mounts[dest.strip()] = src.strip()
    return mounts


def http_json(url, method="GET", payload=None, timeout=20):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body) if body.strip().startswith(("{", "[")) else body


# ------------------------------------------------------------------ 静态
def run_static():
    with open(os.path.join(ROOT, "control", "app.py"), "r", encoding="utf-8") as f:
        app = f.read()
    with open(os.path.join(ROOT, "tools", "hub", "registry.py"), "r", encoding="utf-8") as f:
        reg = f.read()

    check("control pins shared registry path",
          'TOOLS_REGISTRY_PATH' in app and "/config/registry/tools_registry.json" in app)
    check("control defines _registry_volume", "def _registry_volume()" in app)
    check("create_agent mounts registry volume", app.count("**_registry_volume(),") >= 2)
    check("control resolves host roots from own mounts",
          "_host_roots_from_self_mounts" in app and 'mounts.get("/config")' in app)
    check("registry default path unchanged", '"/config/tools_registry.json"' in reg)


# ------------------------------------------------------------------ 线上
def run_live():
    rc, _, _ = docker("inspect", CONTROL_CONTAINER, "--format", "{{.Id}}")
    if rc != 0:
        skip("live checks", "docker/control 容器不可用")
        return

    check("host registry file exists", os.path.isfile(REGISTRY_HOST))
    with open(REGISTRY_HOST, "r", encoding="utf-8") as f:
        host_items = set((json.load(f).get("items") or {}).keys())

    ctl = container_mounts(CONTROL_CONTAINER)
    check("control /config = repo config/", norm(ctl.get("/config")) == norm(os.path.join(ROOT, "config")))
    check("control /workspaces = repo workspaces/", norm(ctl.get("/workspaces")) == norm(os.path.join(ROOT, "workspaces")))

    # 每张卡片的挂载都必须落在本仓库下（防止 ${PWD} 取错导致挂到别的目录）
    try:
        items = http_json(CONTROL + "/api/agents").get("items") or []
    except Exception as e:
        skip("live card mounts", "面板不可达: %s" % e)
        items = []
    bad_mounts = []
    for it in items:
        name = it.get("container_name")
        m = container_mounts(name)
        if not m:
            continue
        cfg, ws = m.get("/agent-config"), m.get("/home/agent/.claude/workspace/project")
        for label, path in (("agent-config", cfg), ("workspace", ws)):
            if not path or not norm(path).startswith(norm(ROOT) + "/"):
                bad_mounts.append("%s/%s=%s" % (name, label, path))
    check("every card mounts under repo root", not bad_mounts)
    for b in bad_mounts[:5]:
        print("   -> %s" % b, flush=True)

    # Hub 卡片必须挂到 config/registry，且容器内能读到注册表
    hub = container_mounts(HUB_CONTAINER)
    if not hub:
        skip("live hub registry mount", "hub 容器不可用")
    else:
        check("hub /config = repo config/registry",
              norm(hub.get("/config")) == norm(os.path.join(ROOT, "config", "registry")))
        rc, out, err = docker("exec", HUB_CONTAINER, "cat", "/config/tools_registry.json")
        ok = False
        try:
            ok = isinstance(json.loads(out).get("items"), dict)
        except Exception:
            ok = False
        check("hub can read /config/tools_registry.json", ok)
        if not ok:
            print("   -> rc=%s err=%s" % (rc, err[:200]), flush=True)

    # 两边集合必须一致（无分叉）
    try:
        hub_items = set(t.get("name") for t in (http_json(HUB + "/api/tools").get("items") or []))
        check("hub tools == host registry (%s)" % (", ".join(sorted(host_items)) or "空"),
              hub_items == host_items)
    except Exception as e:
        skip("live hub /api/tools", "Hub 不可达: %s" % e)
        return

    # 闭环：注册 → Hub 可见 → 注销 → 消失
    tool_name = "test"   # derive_tool_name("19088-test")
    try:
        http_json("%s/api/agents/%s/register" % (CONTROL, urllib.parse.quote(E2E_CARD)), method="POST", payload={})
        after = set(t.get("name") for t in (http_json(HUB + "/api/tools").get("items") or []))
        check("register via panel is visible in hub", tool_name in after)
    except Exception as e:
        check("register via panel is visible in hub", False)
        print("   -> %s" % e, flush=True)
    finally:
        try:
            http_json("%s/api/agents/%s/register" % (CONTROL, urllib.parse.quote(E2E_CARD)), method="DELETE")
            back = set(t.get("name") for t in (http_json(HUB + "/api/tools").get("items") or []))
            check("unregister removes it from hub", tool_name not in back)
            check("hub set restored to host registry", back == host_items)
        except Exception as e:
            check("unregister removes it from hub", False)
            print("   -> %s" % e, flush=True)


def run():
    try:
        run_static()
        run_live()
    except Exception as e:
        import traceback
        traceback.print_exc()
        check("harness completed without exception (%s)" % e, False)


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
    print("ALL CHECKS PASSED%s" % (" (%d skipped)" % len(skips) if skips else ""), flush=True)
    sys.exit(0)
