# -*- coding: utf-8 -*-
"""TDD 校验：容器模型读取必须"精确"，不得再用域名猜测。

背景（旧实现的 bug）：
  /api/agents/<name>/current-model 以前只读 settings.json 的 ANTHROPIC_BASE_URL，
  再用 model_map = {"api.deepseek.com": "deepseek", "api.minimaxi.com": "minimax"}
  按域名猜模型名。后果：
    - api.minimax.cn（minimax / minimax-m2.7-highspeed）→ 报 unknown
    - api.deepseek.com（deepseek / deepseek-flash）→ 两者都报 deepseek，分不出
    - 无后缀默认配置（api.minimaxi.com, provider "MiniMax", model MiniMax-M3）
      → 被报成 "minimax"，面板把 `minimax` 这个 profile 误标成「当前」
    - host.docker.internal:8000（localqwen）→ 报 unknown

现在要求：读容器内 settings.json + config.json 的真实内容，给出
  model_id（config.json provider env 的 ANTHROPIC_MODEL）
  provider_name / base_url / 匹配到的 profile，并列出不一致告警。

覆盖点：
  A) 纯逻辑（从 control/app.py 抽出嵌套 helper 直接跑，无需 flask/docker）
     1) _host_model_profiles() 能扫出"默认 + 5 个 profile"且模型 id 正确。
     2) _match_profile() 用 base_url + provider 名消歧：
        - 同域名的 deepseek / deepseek-flash 必须区分开
        - 同域名的 minimax / minimax-m2.7-highspeed 必须区分开
        - localqwen（host.docker.internal）能匹配
        - 未知端点返回 None
  B) 静态：control/app.py 里不得再出现旧的域名猜测（model_map）。
  C) 线上：抓每张卡片的 /current-model，模型信息必须非空且不含 unknown。
     面板未重建（仍是旧实现）时标记 SKIP，不算失败。

超时机制：整个校验在守护线程中执行，主线程 join(timeout)，超时判失败。
"""
import json
import os
import re
import sys
import textwrap
import threading
import urllib.parse
import urllib.request

TIMEOUT_SECONDS = 90
ROOT = os.path.dirname(os.path.abspath(__file__))
APP_PATH = os.path.join(ROOT, "control", "app.py")
CLAUDE_DIR = os.path.join(ROOT, "config", "claude")
CONTROL = os.environ.get("CONTROL_URL", "http://localhost:19080")

# profile -> (ANTHROPIC_MODEL, base_url)
EXPECT_PROFILES = {
    "minimax": ("MiniMax-M3", "https://api.minimax.cn/anthropic"),
    "minimax-m2.7-highspeed": ("MiniMax-M2.7-highspeed", "https://api.minimax.cn/anthropic"),
    "deepseek": ("deepseek-v4-flash", "https://api.deepseek.com/anthropic"),
    "deepseek-flash": ("deepseek-flash", "https://api.deepseek.com/anthropic"),
    "localqwen": ("qwen3.8-27b", "http://host.docker.internal:8000"),
    # webqwen：远端（dimond.top:21234）的 web 版千问，模型名带 publisher 前缀
    "webqwen": ("qwen/qwen3.8-27b", "http://dimond.top:21234"),
}

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


# ---------------------------------------------------------------- 源码抽取
def extract_func(src, name):
    """把 create_app 里 4 空格缩进的嵌套 def 整段抽出来（含其上的注释不算）。"""
    m = re.search(r"^(\s*)def %s\(" % re.escape(name), src, re.M)
    if not m:
        raise AssertionError("function not found: %s" % name)
    indent = m.group(1)
    nxt = re.compile(r"^%s(?:def |@)" % re.escape(indent), re.M).search(src, m.end())
    return src[m.start(): nxt.start() if nxt else len(src)]


def load_helpers():
    """抽取纯逻辑 helper 并在隔离命名空间里 exec（不 import flask/docker）。"""
    with open(APP_PATH, "r", encoding="utf-8") as f:
        src = f.read()

    names = ["_read_text_file", "_parse_json_object", "_read_container_text",
             "_first_provider", "_model_id_from_env", "_normalize_url",
             "_host_model_profiles", "_match_profile", "api_current_model"]
    code = textwrap.dedent("\n".join(extract_func(src, n) for n in names))

    class FakeApp(object):
        config = {"CONFIG_ROOT": os.path.join(ROOT, "config")}

    ns = {"json": json, "os": os, "re": re, "app": FakeApp(), "AGENT_RUNTIME_USER": "agent",
          "jsonify": lambda payload: payload, "docker": None}
    exec(compile(code, "control/app.py:helpers", "exec"), ns)
    return ns


class FakeResult(object):
    def __init__(self, output):
        self.output = output


class FakeContainer(object):
    """按路径返回 settings.json / config.json 内容，并可伪造烤进容器的进程 env。"""

    def __init__(self, settings_text, config_text, env_base_url=""):
        self._settings = settings_text.encode("utf-8")
        self._config = config_text.encode("utf-8")
        env = ["PATH=/usr/bin"]
        if env_base_url:
            env.append("ANTHROPIC_BASE_URL=" + env_base_url)
        self.attrs = {"Config": {"Env": env}}

    def exec_run(self, cmd, user=None):
        target = cmd[-1]
        if "settings.json" in target:
            return FakeResult(self._settings)
        if "config.json" in target:
            return FakeResult(self._config)
        return FakeResult(b"")


def card_fixtures():
    def settings(base_url, primary="claude-3-5-sonnet-latest"):
        return json.dumps({"env": {"ANTHROPIC_BASE_URL": base_url},
                           "primaryModel": primary,
                           "permissions": {"defaultMode": "bypassPermissions"}}, indent=4)

    def config(provider_name, model_id, base_url):
        return json.dumps({"version": 2, "claude": {"providers": {"pid": {
            "id": "pid", "name": provider_name,
            "settingsConfig": {"env": {"ANTHROPIC_AUTH_TOKEN": "tok",
                                       "ANTHROPIC_MODEL": model_id,
                                       "ANTHROPIC_BASE_URL": base_url}},
            "websiteUrl": base_url}}, "current": "pid"}}, indent=2)

    return {
        # 文件与进程 env 一致：头部就用文件里的精确模型
        "legacy-in-sync": (
            settings("https://api.minimaxi.com/anthropic"),
            config("MiniMax", "MiniMax-M3", "https://api.minimaxi.com/anthropic"),
            "https://api.minimaxi.com/anthropic",
            {"in_sync": True, "model_id": "MiniMax-M3", "provider_name": "MiniMax",
             "profile": "", "configured_model_id": "MiniMax-M3"}),
        "localqwen-in-sync": (
            settings("http://host.docker.internal:8000", primary="qwen3.8-27b"),
            config("LocalQwen3.8-27B (vLLM)", "qwen3.8-27b", "http://host.docker.internal:8000"),
            "http://host.docker.internal:8000",
            {"in_sync": True, "model_id": "qwen3.8-27b", "provider_name": "LocalQwen3.8-27B (vLLM)",
             "profile": "localqwen", "configured_model_id": "qwen3.8-27b"}),
        # 真实线上状态：文件已是 localqwen，但进程 env 还是建容器时的旧端点（env 优先）
        "localqwen-stale-env": (
            settings("http://host.docker.internal:8000", primary="qwen3.8-27b"),
            config("LocalQwen3.8-27B (vLLM)", "qwen3.8-27b", "http://host.docker.internal:8000"),
            "https://api.minimaxi.com/anthropic",
            {"in_sync": False, "model_id": "", "provider_name": "",
             "profile": "", "configured_model_id": "qwen3.8-27b",
             "effective_base_url": "https://api.minimaxi.com/anthropic"}),
        # 同域名两兄弟：只有 provider 名能区分
        "deepseek-flash-in-sync": (
            settings("https://api.deepseek.com/anthropic"),
            config("DeepSeek-V4.1-Flash", "deepseek-flash", "https://api.deepseek.com/anthropic"),
            "https://api.deepseek.com/anthropic",
            {"in_sync": True, "model_id": "deepseek-flash", "provider_name": "DeepSeek-V4.1-Flash",
             "profile": "deepseek-flash", "configured_model_id": "deepseek-flash"}),
        "minimax-m27-in-sync": (
            settings("https://api.minimax.cn/anthropic"),
            config("MiniMax-M2.7-highspeed", "MiniMax-M2.7-highspeed", "https://api.minimax.cn/anthropic"),
            "https://api.minimax.cn/anthropic",
            {"in_sync": True, "model_id": "MiniMax-M2.7-highspeed",
             "provider_name": "MiniMax-M2.7-highspeed", "profile": "minimax-m2.7-highspeed",
             "configured_model_id": "MiniMax-M2.7-highspeed"}),
    }


def run_endpoint_dry_run():
    """用真实容器里读到的配置做 fixture，直接跑 endpoint 函数体。"""
    ns = load_helpers()
    endpoint = ns["api_current_model"]
    containers = {}

    def require_managed(name):
        return containers[name]

    ns["_require_managed"] = require_managed

    for name, (settings_text, config_text, env_base_url, expect) in card_fixtures().items():
        containers[name] = FakeContainer(settings_text, config_text, env_base_url)
        try:
            data = endpoint(name)
        except Exception as e:
            check("endpoint dry-run %s" % name, False)
            print("   -> raised: %r" % (e,), flush=True)
            continue
        check("endpoint %s in_sync=%s" % (name, expect["in_sync"]),
              data.get("in_sync") == expect["in_sync"])
        check("endpoint %s headline model_id=%r" % (name, expect["model_id"]),
              data.get("model_id") == expect["model_id"])
        check("endpoint %s headline profile=%r" % (name, expect["profile"]),
              data.get("profile") == expect["profile"])
        check("endpoint %s configured model_id=%s" % (name, expect["configured_model_id"]),
              (data.get("configured") or {}).get("model_id") == expect["configured_model_id"])
        check("endpoint %s model field mirrors headline" % name,
              data.get("model") == data.get("model_id"))
        check("endpoint %s reports both layers" % name,
              isinstance(data.get("effective"), dict) and isinstance(data.get("configured"), dict))
        if expect.get("effective_base_url"):
            check("endpoint %s effective base_url=%s" % (name, expect["effective_base_url"]),
                  (data.get("effective") or {}).get("base_url") == expect["effective_base_url"])
        print("   -> %s: headline=%s/%s | effective=%s | configured=%s | in_sync=%s"
              % (name, data.get("model_id") or "(空)", data.get("provider_name") or "-",
                 (data.get("effective") or {}).get("base_url"),
                 (data.get("configured") or {}).get("model_id"), data.get("in_sync")), flush=True)

    # 关键语义：env 优先 —— 头部必须报"实际生效"的端点，而不是文件里那个
    stale = endpoint("localqwen-stale-env")
    check("stale env: headline is the effective (env) endpoint",
          stale.get("base_url") == "https://api.minimaxi.com/anthropic")
    check("stale env: configured keeps the file model",
          (stale.get("configured") or {}).get("model_id") == "qwen3.8-27b")
    check("stale env: warning explains 实际生效 vs 文件",
          any("实际生效" in w for w in stale.get("warnings") or []))

    # 告警必须能指出两类真实问题
    legacy = endpoint("legacy-in-sync")
    check("legacy card warns it lags the current default",
          any("落后于当前默认配置" in w for w in legacy.get("warnings") or []))
    check("legacy card warns the endpoint matches no profile",
          any("不在现有 profile 中" in w for w in legacy.get("warnings") or []))
    check("in-sync card has no stale-env warning",
          not any("不一致：实际生效" in w for w in legacy.get("warnings") or []))
    clean = endpoint("localqwen-in-sync")
    # 不要求"完全无告警"：当前默认 profile 可能不是 localqwen（会给出"落后于当前默认配置"的提示），
    # 这里只要求没有"env 与文件不一致"那类真正的问题告警。
    check("in-sync localqwen card has no stale-env warning",
          not any("实际生效" in w for w in clean.get("warnings") or []))

    # settings.json 与 config.json 端点打架时必须报出来
    containers["mismatch"] = FakeContainer(
        json.dumps({"env": {"ANTHROPIC_BASE_URL": "http://a.invalid"}}),
        json.dumps({"claude": {"providers": {"p": {"name": "X",
                                                   "settingsConfig": {"env": {"ANTHROPIC_MODEL": "m",
                                                                              "ANTHROPIC_BASE_URL": "http://b.invalid"}}}}}}))
    mismatched = endpoint("mismatch")
    check("mismatched base_url reported",
          any("不一致" in w for w in mismatched.get("warnings") or []))

    # 读不到文件时不得崩，且要明确告警
    containers["empty"] = FakeContainer("", "")
    empty = endpoint("empty")
    check("empty files -> warnings, no crash", len(empty.get("warnings") or []) >= 2)
    check("empty files -> empty model_id", empty.get("model_id") == "")

    # 容器不存在时不得 500
    def boom(name):
        raise RuntimeError("no such container")

    ns["_require_managed"] = boom
    missing = endpoint("nope")
    payload = missing[0] if isinstance(missing, tuple) else missing   # 错误分支返回 (payload, status)
    check("missing container -> error payload", isinstance(payload, dict) and "error" in payload)


def run_logic():
    ns = load_helpers()
    profiles = ns["_host_model_profiles"]()
    match = ns["_match_profile"]

    by_name = {p["profile"]: p for p in profiles}

    check("profiles: default entry present", "" in by_name)
    for p, (model, base_url) in EXPECT_PROFILES.items():
        entry = by_name.get(p)
        check("profiles: %s scanned" % p, entry is not None)
        if entry is None:
            continue
        check("profiles: %s model_id=%s" % (p, model), entry["model_id"] == model)
        check("profiles: %s base_url=%s" % (p, base_url), entry["base_url"] == base_url)
        check("profiles: %s has provider_name" % p, bool(entry["provider_name"]))

    # 同域名必须靠 provider 名消歧 —— 旧实现做不到的两组
    for profile, provider in (("deepseek", "DeepSeek-V4-Flash"),
                              ("deepseek-flash", "DeepSeek-V4.1-Flash")):
        hit = match(profiles, "https://api.deepseek.com/anthropic", provider, "")
        got = (hit or {}).get("profile")
        check("disambiguate deepseek pair -> %s (provider=%s)" % (profile, provider), got == profile)

    for profile, provider in (("minimax", "MiniMax-M3"),
                              ("minimax-m2.7-highspeed", "MiniMax-M2.7-highspeed")):
        hit = match(profiles, "https://api.minimax.cn/anthropic", provider, "")
        got = (hit or {}).get("profile")
        check("disambiguate minimax pair -> %s (provider=%s)" % (profile, provider), got == profile)

    hit = match(profiles, "http://host.docker.internal:8000", "LocalQwen3.8-27B (vLLM)", "qwen3.8-27b")
    check("match localqwen by base_url", (hit or {}).get("profile") == "localqwen")

    # 末尾斜杠差异不应影响匹配
    hit = match(profiles, "http://host.docker.internal:8000/", "LocalQwen3.8-27B (vLLM)", "")
    check("match tolerates trailing slash", (hit or {}).get("profile") == "localqwen")

    # 不在任何 profile 里的端点 → None（面板应显示"无匹配"，而不是猜一个名字）
    for url in ("https://api.anthropic.com", "https://api.minimaxi.com/anthropic", ""):
        hit = match(profiles, url, "Whatever", "whatever")
        check("no bogus match for %r" % (url or "<empty>"), hit is None)


def run_static():
    with open(APP_PATH, "r", encoding="utf-8") as f:
        src = f.read()
    check("old domain-guess model_map removed", "model_map" not in src)
    check("endpoint returns model_id", "def api_current_model" in src and '"model_id": headline["model_id"]' in src)
    check("endpoint separates effective vs configured",
          '"effective": effective' in src and '"configured": configured' in src and '"in_sync": in_sync' in src)
    check("endpoint reports warnings", '"warnings": warnings' in src)


def run_live():
    try:
        with urllib.request.urlopen(CONTROL + "/api/agents", timeout=15) as resp:
            items = json.loads(resp.read().decode("utf-8")).get("items") or []
    except Exception as e:
        skip("live /current-model per card", "control unreachable: %s" % e)
        return

    if not items:
        skip("live /current-model per card", "no cards")
        return

    old_shape = []
    for item in items:
        name = item.get("container_name")
        try:
            url = "%s/api/agents/%s/current-model" % (CONTROL, urllib.parse.quote(name))
            with urllib.request.urlopen(url, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            check("live %s /current-model reachable" % name, False)
            print("   -> %s" % e, flush=True)
            continue

        if "model_id" not in data or "effective" not in data:
            old_shape.append(name)
            continue

        model_id = (data.get("model_id") or "").strip()
        base_url = (data.get("base_url") or "").strip()
        effective = data.get("effective") or {}
        configured = data.get("configured") or {}
        in_sync = data.get("in_sync")
        check("live %s base_url non-empty" % name, bool(base_url))
        check("live %s model_id is not 'unknown'" % name, model_id.lower() != "unknown")
        check("live %s reports effective layer" % name, bool(effective.get("base_url")))
        check("live %s reports configured layer" % name, bool(configured.get("base_url")))

        if in_sync:
            check("live %s in-sync -> headline model_id non-empty (%s)" % (name, model_id or "-"),
                  bool(model_id))
        else:
            # 头部必须是"实际生效"（进程 env）的那一层，且文件层信息仍完整可读
            check("live %s out-of-sync -> headline is the env endpoint" % name,
                  base_url == (data.get("env_base_url") or ""))
            check("live %s out-of-sync -> configured model_id non-empty" % name,
                  bool((configured.get("model_id") or "").strip()))
            check("live %s out-of-sync -> warns about it" % name,
                  any("实际生效" in w for w in data.get("warnings") or []))

        profile = data.get("profile") or ""
        if profile and model_id:
            entry = EXPECT_PROFILES.get(profile)
            check("live %s profile=%s matches model_id" % (name, profile),
                  entry is not None and entry[0] == model_id)
        print("   -> %s: headline=%s @ %s | configured=%s @ %s | profile=%s | in_sync=%s | warnings=%d"
              % (name, model_id or "(空)", base_url,
                 configured.get("model_id") or "-", configured.get("base_url") or "-",
                 profile or "(none)", in_sync, len(data.get("warnings") or [])), flush=True)

    if old_shape:
        skip("live /current-model uses new precise shape",
             "%d card(s) still return the old domain-guess payload — 面板未重建: %s"
             % (len(old_shape), ", ".join(old_shape)))


def run():
    try:
        run_logic()
        run_endpoint_dry_run()
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
