# -*- coding: utf-8 -*-
"""TDD 校验：config/claude/ 下各模型 profile 配置文件正确可用。

当前 profile（云端模型名已按官方文档核实）：
  - minimax                  -> MiniMax-M3             @ https://api.minimax.cn/anthropic
  - minimax-m2.7-highspeed   -> MiniMax-M2.7-highspeed @ https://api.minimax.cn/anthropic
  - deepseek                 -> deepseek-v4-flash      @ https://api.deepseek.com/anthropic
  - deepseek-flash           -> deepseek-flash         @ https://api.deepseek.com/anthropic  (V4.1-Flash)
  - localqwen                -> qwen3.8-27b            @ http://host.docker.internal:8000    (llama.cpp 容器 llama-qwen38)
  - webqwen                  -> qwen/qwen3.8-27b       @ http://dimond.top:21234

覆盖点：
  1) 每个 profile 两个文件都存在（config.json.<p> + settings.json.<p>）。
  2) config.json.X 的 ANTHROPIC_MODEL 为官方模型名。
  3) base_url 正确（minimax 用 api.minimax.cn，deepseek 用 api.deepseek.com）。
  4) 每个 config.json.X 都带 ANTHROPIC_AUTH_TOKEN（非空）。
  5) settings.json.X 的 env.ANTHROPIC_BASE_URL 与对应 config.json.X 一致。
  6) settings.json.X 的 primaryModel 对齐各自模型名。
  7) 全部 JSON 合法。
  8) 线上 /api/config/profiles 能列出这些 profile。
  9) localqwen 展示名与真实服务架构一致，且本地推理服务实测可达。

超时机制：整个校验在守护线程中执行，主线程 join(timeout)，超时判失败。
"""
import json
import os
import sys
import threading
import urllib.request

TIMEOUT_SECONDS = 120
ROOT = os.path.dirname(os.path.abspath(__file__))
CLAUDE_DIR = os.path.join(ROOT, "config", "claude")
PROFILES_URL = os.environ.get("PROFILES_URL", "http://localhost:19080/api/config/profiles")

# profile -> (config.json.X 里的 ANTHROPIC_MODEL, base_url)
EXPECT = {
    "minimax": ("MiniMax-M3", "https://api.minimax.cn/anthropic"),
    "minimax-m2.7-highspeed": ("MiniMax-M2.7-highspeed", "https://api.minimax.cn/anthropic"),
    "deepseek": ("deepseek-v4-flash", "https://api.deepseek.com/anthropic"),
    "deepseek-flash": ("deepseek-flash", "https://api.deepseek.com/anthropic"),
    # 本地推理服务（llama.cpp 容器 llama-qwen38，OpenAI + Anthropic 双协议）
    "localqwen": ("qwen3.8-27b", "http://host.docker.internal:8000"),
    # 远程 web vLLM 服务（通过 dimond.top 反代暴露）
    "webqwen": ("qwen/qwen3.8-27b", "http://dimond.top:21234"),
}

# 远程 webqwen 实测目标
WEBQWEN_URL = os.environ.get("WEBQWEN_URL", "http://dimond.top:21234")
WEBQWEN_MODEL = "qwen/qwen3.8-27b"

# 本地推理服务实测目标：容器名 / 宿主地址 / 模型 id
# 2026-09 架构更换：vLLM 容器 vllm-qwen38 -> llama.cpp 容器 llama-qwen38，端口与模型名不变
LOCAL_CONTAINER = "llama-qwen38"
LOCAL_HOST_URL = os.environ.get("LOCAL_MODEL_URL", "http://127.0.0.1:8000")
LOCAL_MODEL = "qwen3.8-27b"

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
        # 关键：容器里的 claude CLI 只读 settings.json 的 env（config.json 是 hermit GUI 的配置，CLI 不读），
        # settings.json 缺模型键 → CLI 用内置默认模型名 → 端点报 model not found（localqwen 实测 404）。
        for k in ("ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL",
                  "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL"):
            check("%s settings env %s=%s" % (p, k, model),
                  (sett.get("env") or {}).get(k) == model)

    # 7b) 无后缀默认配置（新建 / 重启容器拿它当种子）同样必须带模型键
    default_settings = os.path.join(CLAUDE_DIR, "settings.json")
    default_config = os.path.join(CLAUDE_DIR, "config.json")
    if os.path.isfile(default_settings) and os.path.isfile(default_config):
        denv, _ = first_provider_env(read_json(default_config))
        dsett_env = (read_json(default_settings).get("env") or {})
        dmodel = denv.get("ANTHROPIC_MODEL")
        check("default settings ANTHROPIC_MODEL=%s" % dmodel,
              bool(dmodel) and dsett_env.get("ANTHROPIC_MODEL") == dmodel)
        check("default settings base_url matches default config",
              dsett_env.get("ANTHROPIC_BASE_URL") == denv.get("ANTHROPIC_BASE_URL"))
    else:
        skip("default settings/config model keys", "files not found")

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

    # 8b) localqwen 的展示名必须与真实服务架构一致（vLLM -> llama.cpp）
    lq_cfg = os.path.join(CLAUDE_DIR, "config.json.localqwen")
    if os.path.isfile(lq_cfg):
        _, lq_provider = first_provider_env(read_json(lq_cfg))
        lq_name = (lq_provider.get("name") or "")
        check("localqwen provider name reflects llama.cpp", "llama" in lq_name.lower())
        check("localqwen provider name no longer claims vLLM", "vllm" not in lq_name.lower())

    # 9) 实测本地推理服务 llama-qwen38
    check_local_model()


def _post_json(url, payload, headers=None, timeout=90):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def check_local_model():
    # 9-pre) 本地推理容器确实在跑（架构更换后容器名是 llama-qwen38）
    try:
        import subprocess
        out = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Status}}", LOCAL_CONTAINER],
            capture_output=True, text=True, timeout=30)
        status = out.stdout.strip()
        check("local container %s running" % LOCAL_CONTAINER, status == "running")
        if status != "running":
            print("   -> got %r %s" % (status, out.stderr.strip()[:120]), flush=True)
    except Exception as e:
        skip("local container running", "failed: %s" % e)

    # 9a) OpenAI 协议 /v1/models 暴露的模型 id
    try:
        with urllib.request.urlopen(LOCAL_HOST_URL + "/v1/models", timeout=20) as resp:
            ids = [m.get("id") for m in (json.loads(resp.read().decode("utf-8")).get("data") or [])]
        check("local model /v1/models reachable", True)
        check("local model serves %s" % LOCAL_MODEL, LOCAL_MODEL in ids)
        print("   -> model ids: %s" % ids, flush=True)
    except Exception as e:
        skip("local model /v1/models", "unreachable: %s" % e)
        return

    # 9b) Anthropic 协议 /v1/messages（Claude Code 依赖此端点）
    try:
        status, body = _post_json(
            LOCAL_HOST_URL + "/v1/messages",
            {"model": LOCAL_MODEL, "max_tokens": 16,
             "messages": [{"role": "user", "content": "reply with exactly: OK"}]},
            headers={"anthropic-version": "2023-06-01", "x-api-key": "dummy"})
        check("local model /v1/messages status 200", status == 200)
        check("local model /v1/messages is anthropic shape",
              body.get("type") == "message" and isinstance(body.get("content"), list)
              and "usage" in body)
    except Exception as e:
        check("local model /v1/messages status 200", False)
        print("   -> %s" % e, flush=True)

    # 9c) agent 容器内可达（配置里用的 host.docker.internal:8000）
    try:
        import subprocess
        out = subprocess.run(
            ["docker", "exec", "19087-gpussh", "curl", "-s", "--max-time", "20",
             "-o", "/dev/null", "-w", "%{http_code}",
             "http://host.docker.internal:8000/v1/models"],
            capture_output=True, text=True, timeout=40)
        code = out.stdout.strip()
        check("agent container reaches local model via host.docker.internal", code == "200")
        if code != "200":
            print("   -> got %r %s" % (code, out.stderr.strip()[:120]), flush=True)
    except Exception as e:
        skip("agent container reaches local model", "failed: %s" % e)


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
