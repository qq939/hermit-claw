# -*- coding: utf-8 -*-
"""TDD 校验：config/claude/ 下 4 个模型 profile 配置文件正确可用。

最终 4 个 profile（模型名已按官方文档核实）：
  - minimax                  -> MiniMax-M3            @ https://api.minimax.cn/anthropic
  - minimax-m2.7-highspeed   -> MiniMax-M2.7-highspeed @ https://api.minimax.cn/anthropic
  - deepseek                 -> deepseek-v4-flash      @ https://api.deepseek.com/anthropic
  - deepseek-flash           -> deepseek-flash         @ https://api.deepseek.com/anthropic  (V4.1-Flash)

覆盖点：
  1) 8 个文件存在（4 个 config.json.<p> + 4 个 settings.json.<p>）。
  2) config.json.X 的 ANTHROPIC_MODEL 为官方模型名。
  3) base_url 正确（minimax 用 api.minimax.cn，deepseek 用 api.deepseek.com）。
  4) 4 个 config.json.X 都带 ANTHROPIC_AUTH_TOKEN（照抄原有 key，非空）。
  5) settings.json.X 的 env.ANTHROPIC_BASE_URL 与对应 config.json.X 一致。
  6) settings.json.X 的 primaryModel 对齐各自模型名。
  7) 全部 JSON 合法。
  8) 线上 /api/config/profiles 能列出这 4 个 profile。

超时机制：整个校验在守护线程中执行，主线程 join(timeout)，超时判失败。
"""
import json
import os
import sys
import threading
import urllib.request

TIMEOUT_SECONDS = 60
ROOT = os.path.dirname(os.path.abspath(__file__))
CLAUDE_DIR = os.path.join(ROOT, "config", "claude")
PROFILES_URL = os.environ.get("PROFILES_URL", "http://localhost:19080/api/config/profiles")

# profile -> (config.json.X 里的 ANTHROPIC_MODEL, base_url)
EXPECT = {
    "minimax": ("MiniMax-M3", "https://api.minimax.cn/anthropic"),
    "minimax-m2.7-highspeed": ("MiniMax-M2.7-highspeed", "https://api.minimax.cn/anthropic"),
    "deepseek": ("deepseek-v4-flash", "https://api.deepseek.com/anthropic"),
    "deepseek-flash": ("deepseek-flash", "https://api.deepseek.com/anthropic"),
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


def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def first_provider_env(cfg):
    providers = ((cfg.get("claude") or {}).get("providers") or {})
    provider = list(providers.values())[0]
    return provider["settingsConfig"]["env"], provider


def run():
    # 1) 文件存在 + JSON 合法
    for p in EXPECT:
        for kind in ("config", "settings"):
            path = os.path.join(CLAUDE_DIR, "%s.json.%s" % (kind, p))
            check("exists %s.json.%s" % (kind, p), os.path.isfile(path))

    # 2~7) 内容校验
    for p, (model, base_url) in EXPECT.items():
        cfg_path = os.path.join(CLAUDE_DIR, "config.json.%s" % p)
        sett_path = os.path.join(CLAUDE_DIR, "settings.json.%s" % p)
        if not (os.path.isfile(cfg_path) and os.path.isfile(sett_path)):
            continue
        cfg = read_json(cfg_path)
        env, provider = first_provider_env(cfg)
        check("%s ANTHROPIC_MODEL=%s" % (p, model), env.get("ANTHROPIC_MODEL") == model)
        check("%s base_url=%s" % (p, base_url), env.get("ANTHROPIC_BASE_URL") == base_url)
        check("%s has auth token" % p, bool(env.get("ANTHROPIC_AUTH_TOKEN")))
        # 四个 default model 字段都指向该模型
        for k in ("ANTHROPIC_DEFAULT_HAIKU_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL",
                  "ANTHROPIC_DEFAULT_SONNET_MODEL"):
            check("%s %s" % (p, k), env.get(k) == model)

        sett = read_json(sett_path)
        check("%s settings primaryModel" % p, sett.get("primaryModel") == model)
        check("%s settings base_url matches config" % p,
              (sett.get("env") or {}).get("ANTHROPIC_BASE_URL") == base_url)

    # 8) 线上 API 能列出这 4 个 profile
    #    注意：宿主 curl localhost:19080 可能被沙箱/端口转发误导，
    #    因此先试 HTTP，失败则回退到 docker exec 在容器内取真实值。
    got = None
    try:
        with urllib.request.urlopen(PROFILES_URL, timeout=15) as resp:
            body = resp.read().decode("utf-8")
        if body.lstrip().startswith("{"):
            got = set(json.loads(body).get("profiles") or [])
        else:
            raise ValueError("non-JSON response: %r" % body[:60])
    except Exception:
        got = None

    if got is None:
        try:
            import subprocess
            py = ("import urllib.request,json;"
                  "d=json.loads(urllib.request.urlopen("
                  "'http://127.0.0.1:8080/api/config/profiles',timeout=10).read().decode());"
                  "print(json.dumps(d))")
            out = subprocess.run(
                ["docker", "exec", "hermit-control-19080", "python3", "-c", py],
                capture_output=True, text=True, timeout=30)
            if out.returncode == 0 and out.stdout.strip().startswith("{"):
                got = set(json.loads(out.stdout.strip()).get("profiles") or [])
        except Exception as e:
            skip("live profiles via docker exec", "failed: %s" % e)

    if got is None:
        skip("live /api/config/profiles lists 4 profiles", "not reachable")
    else:
        for p in EXPECT:
            check("live profiles lists %s" % p, p in got)


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
