import os
import re
from datetime import datetime, timezone
from io import BytesIO

import docker
from docker.types import LogConfig
from flask import Flask, jsonify, make_response, request, send_file

# GLOBAL PARAMETERS
# Used in find_next_port (line 76) as the first generated agent host port.
START_HOST_PORT = 18081
# Used in find_next_port (line 76) as the upper bound for generated host ports.
END_HOST_PORT = 19999
# Used in create_agent (line 123) and API responses to enforce fixed in-container service port.
SERVICE_PORT = 8082
# Used in helper filters (line 52, 67) to identify containers created by this control plane.
MANAGED_LABEL_KEY = "hermit.managed"
# Used in create_agent (line 139) to mark new containers as managed by this control plane.
MANAGED_LABEL_VALUE = "true"
# Used in create_agent (line 127, 144) and validation to map UI type to image/config directory.
AGENT_SPECS = {
    "claude": {"image": "hermit-agent-claude:latest", "config_subdir": "claude"},
    "openclaw@2026.2.9": {"image": "hermit-agent-openclaw-2026.2.9:latest", "config_subdir": "openclaw"},
}
# Used in API handlers (line 259, 300, 310) as default line count shown in each 20-line card.
DEFAULT_TAIL_LINES = 20
# Used in _safe_name_part (line 92) to sanitize user-provided agent names.
NAME_SANITIZE_PATTERN = re.compile(r"[^a-zA-Z0-9_-]+")
# Used in create_agent (line 132) and api_command (line 247) so container startup and exec run as non-root agent user.
AGENT_RUNTIME_USER = "agent"
#
# Used in create_app (line 46-50) and create_agent (line 118-130) to translate in-container paths to actual host bind mount paths when creating new containers via Docker socket.
HOST_CONFIG_ROOT_ENV = "HOST_CONFIG_ROOT"
# Used in create_app (line 46-50) and create_agent (line 118-130) to translate in-container paths to actual host bind mount paths when creating new containers via Docker socket.
HOST_WORKSPACES_ROOT_ENV = "HOST_WORKSPACES_ROOT"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def create_app(docker_client=None):
    app = Flask(__name__)
    app.config["DOCKER_CLIENT"] = docker_client
    app.config["CONFIG_ROOT"] = "/config"
    app.config["WORKSPACES_ROOT"] = "/workspaces"
    app.config["HOST_CONFIG_ROOT"] = os.environ.get(HOST_CONFIG_ROOT_ENV) or app.config["CONFIG_ROOT"]
    app.config["HOST_WORKSPACES_ROOT"] = os.environ.get(HOST_WORKSPACES_ROOT_ENV) or app.config["WORKSPACES_ROOT"]

    def docker_client_or_default():
        configured = app.config.get("DOCKER_CLIENT")
        if configured is not None:
            return configured
        return docker.from_env()

    def all_containers():
        return docker_client_or_default().containers.list(all=True)

    def is_managed(container):
        labels = ((getattr(container, "attrs", {}) or {}).get("Config", {}) or {}).get("Labels", {}) or {}
        if MANAGED_LABEL_KEY in labels:
            return labels.get(MANAGED_LABEL_KEY) == MANAGED_LABEL_VALUE
        return (getattr(container, "labels", {}) or {}).get(MANAGED_LABEL_KEY) == MANAGED_LABEL_VALUE

    def is_compose_member(container):
        labels = ((getattr(container, "attrs", {}) or {}).get("Config", {}) or {}).get("Labels", {}) or {}
        project = labels.get("com.docker.compose.project") or ""
        return project == "hermit-claw"

    def managed_containers():
        return sorted([c for c in all_containers() if is_managed(c)], key=lambda c: c.name)

    def display_containers():
        items = []
        for c in all_containers():
            if is_managed(c):
                items.append(c)
                continue
            if is_compose_member(c) and c.name != "hermit-control-18080":
                items.append(c)
        return sorted(items, key=lambda c: c.name)

    def container_host_port(container):
        bindings = ((getattr(container, "attrs", {}) or {}).get("HostConfig", {}) or {}).get("PortBindings", {}) or {}
        values = bindings.get(f"{SERVICE_PORT}/tcp") or []
        if not values:
            return None
        try:
            return int(values[0].get("HostPort"))
        except (TypeError, ValueError, AttributeError):
            return None

    def find_next_port():
        used = {p for p in [container_host_port(c) for c in managed_containers()] if p is not None}
        for port in range(START_HOST_PORT, END_HOST_PORT + 1):
            if port not in used:
                return port
        raise RuntimeError("No available host port in configured range")

    def _safe_name_part(raw):
        base = (raw or "").strip().lower()
        if not base:
            base = "agent"
        base = NAME_SANITIZE_PATTERN.sub("-", base)
        base = base.strip("-")
        return base or "agent"

    def _tail_logs(container, tail):
        raw = container.logs(tail=tail, stdout=True, stderr=True)
        if isinstance(raw, bytes):
            return raw.decode("utf-8", errors="replace")
        return str(raw)

    def create_agent(agent_type, custom_name):
        if agent_type not in AGENT_SPECS:
            raise ValueError("Unsupported agent type")
        spec = AGENT_SPECS[agent_type]
        host_port = find_next_port()
        normalized_name = _safe_name_part(custom_name)
        container_name = f"{host_port}-{normalized_name}"
        labels = {
            MANAGED_LABEL_KEY: MANAGED_LABEL_VALUE,
            "hermit.agent_type": agent_type,
            "hermit.host_port": str(host_port),
            "hermit.service_port": str(SERVICE_PORT),
        }
        host_config_root = app.config["HOST_CONFIG_ROOT"]
        host_workspaces_root = app.config["HOST_WORKSPACES_ROOT"]
        volumes = {
            f"{host_config_root}/{spec['config_subdir']}": {"bind": "/agent-config", "mode": "ro"},
            f"{host_workspaces_root}/{container_name}": {"bind": "/workspace", "mode": "rw"},
        }
        log_config = LogConfig(type=LogConfig.types.JSON, config={"max-size": "500m", "max-file": "2"})

        env_vars = {}
        if agent_type == "claude":
            # 读取 claude 的 settings.json，把 env 字段注入到容器环境变量中
            # 注意：使用 CONFIG_ROOT (= /config) 因为这是容器内的挂载路径
            config_root = app.config["CONFIG_ROOT"]
            settings_path = os.path.join(config_root, spec["config_subdir"], "settings.json")
            if os.path.exists(settings_path):
                try:
                    import json
                    with open(settings_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if "env" in data and isinstance(data["env"], dict):
                            for k, v in data["env"].items():
                                env_vars[k] = str(v)
                except Exception:
                    pass
            # 也读取 config.json，提取 ANTHROPIC_AUTH_TOKEN（新版 Claude Code 使用）
            config_path = os.path.join(config_root, spec["config_subdir"], "config.json")
            if os.path.exists(config_path):
                try:
                    import json
                    with open(config_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        providers = (((data.get("claude") or {}).get("providers") or {}).values())
                        for provider in providers:
                            env_cfg = ((provider or {}).get("settingsConfig") or {}).get("env") or {}
                            auth_token = env_cfg.get("ANTHROPIC_AUTH_TOKEN")
                            if auth_token:
                                env_vars["ANTHROPIC_AUTH_TOKEN"] = str(auth_token)
                                break
                except Exception:
                    pass
        elif agent_type == "openclaw@2026.2.9":
            # 读取 openclaw.json，提取 auth token 注入到环境变量中
            config_root = app.config["CONFIG_ROOT"]
            openclaw_path = os.path.join(config_root, spec["config_subdir"], "openclaw.json")
            if os.path.exists(openclaw_path):
                try:
                    import json
                    with open(openclaw_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        token = data.get("gateway", {}).get("auth", {}).get("token")
                        if token:
                            env_vars["OPENCLAW_GATEWAY_TOKEN"] = str(token)
                except Exception:
                    pass

        container = docker_client_or_default().containers.run(
            spec["image"],
            name=container_name,
            detach=True,
            tty=True,
            stdin_open=True,
            user=AGENT_RUNTIME_USER,
            environment=env_vars,
            labels=labels,
            ports={f"{SERVICE_PORT}/tcp": host_port},
            volumes=volumes,
            restart_policy={"Name": "unless-stopped"},
            log_config=log_config,
        )
        return {
            "container_name": container.name,
            "agent_type": agent_type,
            "host_port": host_port,
            "service_port": SERVICE_PORT,
            "created_at": now_iso(),
        }

    def recreate_agent(container_name):
        container = docker_client_or_default().containers.get(container_name)
        labels = ((getattr(container, "attrs", {}) or {}).get("Config", {}) or {}).get("Labels", {}) or (getattr(container, "labels", {}) or {})
        agent_type = labels.get("hermit.agent_type") or ""
        if agent_type not in AGENT_SPECS:
            raise ValueError("Unsupported agent type")
        host_port = container_host_port(container)
        if host_port is None:
            raise RuntimeError("Missing port binding")
        spec = AGENT_SPECS[agent_type]
        host_config_root = app.config["HOST_CONFIG_ROOT"]
        host_workspaces_root = app.config["HOST_WORKSPACES_ROOT"]
        volumes = {
            f"{host_config_root}/{spec['config_subdir']}": {"bind": "/agent-config", "mode": "ro"},
            f"{host_workspaces_root}/{container_name}": {"bind": "/workspace", "mode": "rw"},
        }
        log_config = LogConfig(type=LogConfig.types.JSON, config={"max-size": "500m", "max-file": "2"})
        container.remove(force=True)

        env_vars = {}
        if agent_type == "claude":
            # 读取 claude 的 settings.json，把 env 字段注入到容器环境变量中
            # 注意：使用 CONFIG_ROOT (= /config) 因为这是容器内的挂载路径
            config_root = app.config["CONFIG_ROOT"]
            settings_path = os.path.join(config_root, spec["config_subdir"], "settings.json")
            if os.path.exists(settings_path):
                try:
                    import json
                    with open(settings_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if "env" in data and isinstance(data["env"], dict):
                            for k, v in data["env"].items():
                                env_vars[k] = str(v)
                except Exception:
                    pass
            # 也读取 config.json，提取 ANTHROPIC_AUTH_TOKEN（新版 Claude Code 使用）
            config_path = os.path.join(config_root, spec["config_subdir"], "config.json")
            if os.path.exists(config_path):
                try:
                    import json
                    with open(config_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        providers = (((data.get("claude") or {}).get("providers") or {}).values())
                        for provider in providers:
                            env_cfg = ((provider or {}).get("settingsConfig") or {}).get("env") or {}
                            auth_token = env_cfg.get("ANTHROPIC_AUTH_TOKEN")
                            if auth_token:
                                env_vars["ANTHROPIC_AUTH_TOKEN"] = str(auth_token)
                                break
                except Exception:
                    pass

        new_container = docker_client_or_default().containers.run(
            spec["image"],
            name=container_name,
            detach=True,
            tty=True,
            stdin_open=True,
            user=AGENT_RUNTIME_USER,
            environment=env_vars,
            labels={
                MANAGED_LABEL_KEY: MANAGED_LABEL_VALUE,
                "hermit.agent_type": agent_type,
                "hermit.host_port": str(host_port),
                "hermit.service_port": str(SERVICE_PORT),
            },
            ports={f"{SERVICE_PORT}/tcp": host_port},
            volumes=volumes,
            restart_policy={"Name": "unless-stopped"},
            log_config=log_config,
        )
        return {"container_name": new_container.name, "agent_type": agent_type, "host_port": host_port, "service_port": SERVICE_PORT, "recreated_at": now_iso()}

    def format_item(container, tail):
        port = container_host_port(container)
        labels = ((getattr(container, "attrs", {}) or {}).get("Config", {}) or {}).get("Labels", {}) or (getattr(container, "labels", {}) or {})
        agent_type = labels.get("hermit.agent_type", "")
        if not agent_type:
            svc = labels.get("com.docker.compose.service") or ""
            if svc:
                agent_type = f"compose/{svc}"
            else:
                agent_type = "unknown"
        item = {
            "container_name": container.name,
            "agent_type": agent_type,
            "status": getattr(container, "status", "unknown"),
            "host_port": port,
            "service_port": SERVICE_PORT,
            "managed": is_managed(container),
            "logs": _tail_logs(container, tail=tail),
        }
        return item

    @app.get("/api/agent-types")
    def api_agent_types():
        return jsonify({"items": [{"value": k, "label": k} for k in AGENT_SPECS]})

    @app.get("/api/agents")
    def api_agents():
        try:
            tail = int(request.args.get("tail", DEFAULT_TAIL_LINES))
        except ValueError:
            tail = DEFAULT_TAIL_LINES
        tail = max(1, min(200, tail))
        items = [format_item(c, tail) for c in display_containers()]
        return jsonify({"generated_at": now_iso(), "items": items})

    @app.post("/api/agents")
    def api_create_agent():
        body = request.get_json(silent=True) or {}
        agent_type = (body.get("type") or "").strip()
        name = body.get("name") or ""
        try:
            payload = create_agent(agent_type, name)
            return jsonify(payload), 201
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except docker.errors.ImageNotFound:
            return jsonify({"error": "Agent image missing. Please run: docker compose build"}), 400
        except docker.errors.APIError as e:
            return jsonify({"error": f"Docker API error: {str(e)}"}), 500
        except RuntimeError as e:
            return jsonify({"error": str(e)}), 409

    def _require_managed(name):
        container = docker_client_or_default().containers.get(name)
        if not is_managed(container) and not is_compose_member(container):
            raise PermissionError("Container is not managed by this control plane")
        return container

    @app.get("/api/agents/<path:name>/logs")
    def api_logs(name):
        try:
            tail = int(request.args.get("tail", DEFAULT_TAIL_LINES))
        except ValueError:
            tail = DEFAULT_TAIL_LINES
        tail = max(1, min(1000, tail))
        try:
            container = _require_managed(name)
            return jsonify({"container_name": name, "logs": _tail_logs(container, tail)})
        except PermissionError as e:
            return jsonify({"error": str(e)}), 403
        except docker.errors.NotFound:
            return jsonify({"error": "Container not found"}), 404

    @app.get("/api/agents/<path:name>/logs/download")
    def api_logs_download(name):
        try:
            tail = int(request.args.get("tail", DEFAULT_TAIL_LINES))
        except ValueError:
            tail = DEFAULT_TAIL_LINES
        tail = max(1, min(5000, tail))
        try:
            container = _require_managed(name)
            data = _tail_logs(container, tail=tail).encode("utf-8")
            return send_file(
                BytesIO(data),
                mimetype="text/plain; charset=utf-8",
                as_attachment=True,
                download_name=f"{name}.log",
            )
        except PermissionError as e:
            return jsonify({"error": str(e)}), 403
        except docker.errors.NotFound:
            return jsonify({"error": "Container not found"}), 404

    @app.post("/api/agents/<path:name>/command")
    def api_command(name):
        body = request.get_json(silent=True) or {}
        command = (body.get("command") or "").strip()
        if not command:
            return jsonify({"error": "command is required"}), 400
        try:
            container = _require_managed(name)
            result = container.exec_run(["/bin/sh", "-lc", command], user=AGENT_RUNTIME_USER, tty=True)
            output = result.output.decode("utf-8", errors="replace") if isinstance(result.output, bytes) else str(result.output)
            return jsonify({"container_name": name, "command": command, "exit_code": int(result.exit_code), "output": output, "executed_at": now_iso()})
        except PermissionError as e:
            return jsonify({"error": str(e)}), 403
        except docker.errors.NotFound:
            return jsonify({"error": "Container not found"}), 404

    @app.post("/api/agents/<path:name>/restart")
    def api_restart_agent(name):
        try:
            container = _require_managed(name)
            container.restart()
            return jsonify({"ok": True, "container_name": name, "restarted_at": now_iso()})
        except PermissionError as e:
            return jsonify({"error": str(e)}), 403
        except docker.errors.NotFound:
            return jsonify({"error": "Container not found"}), 404
        except docker.errors.APIError as e:
            return jsonify({"error": f"Docker API error: {str(e)}"}), 500

    @app.post("/api/agents/<path:name>/recreate")
    def api_recreate_agent(name):
        try:
            container = docker_client_or_default().containers.get(name)
            if not is_managed(container):
                return jsonify({"error": "Only managed agents can be recreated"}), 400
            payload = recreate_agent(name)
            return jsonify(payload)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except docker.errors.NotFound:
            return jsonify({"error": "Container not found"}), 404
        except docker.errors.APIError as e:
            return jsonify({"error": f"Docker API error: {str(e)}"}), 500
        except RuntimeError as e:
            return jsonify({"error": str(e)}), 409

    @app.post("/api/agents/restart")
    def api_restart_all_agents():
        restarted = []
        errors = {}
        for c in managed_containers():
            try:
                c.restart()
                restarted.append(c.name)
            except Exception as e:
                errors[c.name] = str(e)
        return jsonify({"ok": True, "restarted": restarted, "errors": errors, "restarted_at": now_iso()})

    @app.post("/api/agents/recreate")
    def api_recreate_all_agents():
        recreated = []
        errors = {}
        for c in managed_containers():
            try:
                recreated.append(recreate_agent(c.name))
            except Exception as e:
                errors[c.name] = str(e)
        return jsonify({"ok": True, "recreated": recreated, "errors": errors, "recreated_at": now_iso()})

    @app.get("/")
    def index():
        poll_ms = 5000
        html = f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Hermit Control 18080</title>
    <style>
      :root {{
        --bg: #070A10;
        --panel: rgba(255,255,255,0.06);
        --line: rgba(255,255,255,0.14);
        --text: rgba(255,255,255,0.92);
        --muted: rgba(255,255,255,0.62);
        --ok: #3AE374;
        --warn: #FFC048;
        --bad: #FF4D4D;
        --shadow: 0 24px 60px rgba(0, 0, 0, 0.55);
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        color: var(--text);
        background:
          radial-gradient(1200px 700px at 20% -10%, rgba(58, 227, 116, 0.10), transparent 60%),
          radial-gradient(900px 600px at 110% 10%, rgba(255, 192, 72, 0.10), transparent 55%),
          radial-gradient(900px 700px at 55% 120%, rgba(124, 92, 255, 0.13), transparent 55%),
          var(--bg);
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
      }}
      header {{
        position: sticky;
        top: 0;
        z-index: 10;
        background: linear-gradient(to bottom, rgba(7,10,16,0.92), rgba(7,10,16,0.55));
        backdrop-filter: blur(14px);
        border-bottom: 1px solid var(--line);
      }}
      .wrap {{ padding: 16px 18px; max-width: 1440px; margin: 0 auto; }}
      h1 {{ margin: 0; font-size: 18px; }}
      .sub {{ margin-top: 8px; color: var(--muted); font-size: 12px; }}
      .panel {{
        margin-top: 14px;
        border: 1px solid rgba(255,255,255,0.13);
        border-radius: 14px;
        background: linear-gradient(180deg, rgba(255,255,255,0.08), rgba(255,255,255,0.03));
        box-shadow: var(--shadow);
        padding: 14px;
      }}
      .row {{ display:flex; gap:10px; flex-wrap:wrap; align-items:center; }}
      select, input, button {{
        border-radius: 10px;
        border: 1px solid rgba(255,255,255,0.16);
        background: rgba(0,0,0,0.30);
        color: var(--text);
        padding: 10px 12px;
        font-size: 12px;
        font-family: inherit;
      }}
      input {{ min-width: 220px; }}
      button {{ cursor: pointer; background: rgba(255,255,255,0.08); }}
      button:hover {{ background: rgba(255,255,255,0.12); }}
      .grid {{
        margin-top: 16px;
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(460px, 1fr));
        gap: 14px;
      }}
      .card {{
        border: 1px solid rgba(255,255,255,0.13);
        border-radius: 14px;
        overflow: hidden;
        background: linear-gradient(180deg, rgba(255,255,255,0.08), rgba(255,255,255,0.03));
        box-shadow: var(--shadow);
      }}
      .card-head {{
        display: flex;
        justify-content: space-between;
        gap: 10px;
        align-items: center;
        padding: 12px;
        border-bottom: 1px solid rgba(255,255,255,0.11);
      }}
      .meta {{ color: var(--muted); font-size: 11px; }}
      .actions {{ display:flex; gap:8px; padding: 10px 12px; border-bottom: 1px solid rgba(255,255,255,0.08); }}
      .cmd-bar {{
        display: flex;
        gap: 8px;
        padding: 10px 12px;
        border-bottom: 1px solid rgba(255,255,255,0.08);
      }}
      .cmd-mode {{
        width: 110px;
      }}
      .cmd-input {{
        flex: 1;
        min-width: 120px;
      }}
      pre {{
        margin: 0;
        padding: 12px;
        height: calc(20 * 1.35em);
        overflow: auto;
        font-size: 12px;
        line-height: 1.35;
        white-space: pre-wrap;
        word-break: break-word;
      }}
      .status-running {{ color: var(--ok); }}
      .status-other {{ color: var(--warn); }}
      .small {{ color: var(--muted); font-size: 11px; margin-left: 8px; }}
    </style>
  </head>
  <body>
    <header>
      <div class="wrap">
        <h1>容器控制端 18080</h1>
        <div class="sub">创建类型：claude / openclaw@2026.2.9；端口从 18081 递增，容器名格式：端口号-容器名称。</div>
        <div class="panel">
          <div class="row">
            <select id="agentType"></select>
            <input id="agentName" placeholder="输入容器名称（例如 writer）" />
            <button id="createBtn">一键创建</button>
            <span class="small" id="notice"></span>
          </div>
        </div>
      </div>
    </header>
    <main class="wrap">
      <div id="cards" class="grid"></div>
    </main>
    <script>
      const cards = document.getElementById("cards");
      const agentType = document.getElementById("agentType");
      const agentName = document.getElementById("agentName");
      const createBtn = document.getElementById("createBtn");
      const notice = document.getElementById("notice");
      const tail = 20;

      async function loadTypes() {{
        const res = await fetch("/api/agent-types", {{ cache: "no-store" }});
        const data = await res.json();
        agentType.innerHTML = "";
        for (const item of data.items || []) {{
          const op = document.createElement("option");
          op.value = item.value;
          op.textContent = item.label;
          agentType.appendChild(op);
        }}
      }}

      function makeCard(item) {{
        const div = document.createElement("div");
        div.className = "card";
        div.dataset.name = item.container_name;
        const stCls = item.status === "running" ? "status-running" : "status-other";
        const managed = !!item.managed;
        div.innerHTML = `
          <div class="card-head">
            <div>
              <div>${{item.container_name}}</div>
              <div class="meta">${{item.agent_type}} · ${{item.host_port}}:${SERVICE_PORT}</div>
            </div>
            <div class="meta ${{stCls}}">${{item.status}}</div>
          </div>
          <div class="actions">
            <button data-action="refresh">查看日志</button>
            <button data-action="download">下载日志</button>
            <button data-action="recreate">重建</button>
          </div>
          <div class="cmd-bar">
            <select class="cmd-mode" data-role="cmd-mode">
              <option value="chat">对话</option>
              <option value="shell">Shell</option>
            </select>
            <input class="cmd-input" data-role="cmd-input" placeholder="在卡片内输入命令并回车执行（默认 agent 用户）" />
            <button data-action="exec">执行</button>
          </div>
          <pre id="log-${{item.container_name}}">${{item.logs || ""}}</pre>
        `;
        const logBox = div.querySelector("pre");
        const cmdInput = div.querySelector('[data-role="cmd-input"]');
        const cmdMode = div.querySelector('[data-role="cmd-mode"]');
        div.querySelector('button[data-action="refresh"]').onclick = async () => {{
          const r = await fetch(`/api/agents/${{encodeURIComponent(item.container_name)}}/logs?tail=${{tail}}`, {{ cache: "no-store" }});
          const d = await r.json();
          logBox.textContent = d.logs || d.error || "";
        }};
        div.querySelector('button[data-action="download"]').onclick = () => {{
          window.open(`/api/agents/${{encodeURIComponent(item.container_name)}}/logs/download?tail=500`, "_blank");
        }};
        div.querySelector('button[data-action="recreate"]').onclick = async () => {{
          if (!managed) return;
          const r = await fetch(`/api/agents/${{encodeURIComponent(item.container_name)}}/recreate`, {{ method: "POST" }});
          const d = await r.json();
          if (!r.ok) {{
            logBox.textContent += `\\nERROR: ${{d.error || `HTTP ${{r.status}}`}}\\n`;
            return;
          }}
          logBox.textContent += `\\n(recreated) ${{d.container_name}}\\n`;
          await refreshCards();
        }};
        if (item.agent_type === "claude" || item.agent_type === "openclaw@2026.2.9") {{
          cmdMode.value = "shell";
          cmdInput.placeholder = "输入对话内容，或输入 ls/pwd 等命令";
        }} else {{
          cmdMode.value = "shell";
        }}

        // 保存用户在执行过程中的历史命令/输出，避免轮询刷新覆盖
        const cardKey = `card_state_${{item.container_name}}`;
        if (!window.cardStates) window.cardStates = {{}};
        
        const runCommand = async () => {{
          const raw = (cmdInput.value || "").trim();
          if (!raw) return;
          const mode = cmdMode.value || "shell";
          
          let command = raw;
          let execCmd = raw;
          
          // 如果用户只是输入聊天内容（而不是 shell 命令），我们自动帮他包装成 agent 调用
          if (item.agent_type === "claude") {{
             // 过滤掉 ANSI 乱码
             const cleanOutput = (text) => text.replace(/[\u001b\u009b][[()#;?]*(?:[0-9]{1,4}(?:;[0-9]{0,4})*)?[0-9A-ORZcf-nqry=><]/g, '');

             // 如果输入不是以常见 shell 命令开头，认为是一句对话
             if (!raw.match(/^(ls|cd|pwd|cat|echo|claude|rm|mkdir|touch)/)) {{
                const escaped = raw.replaceAll('"', '\\"');
                command = `claude --dangerously-skip-permissions --print "${{escaped}}"`; // 现在要求卡片显示真实的底层命令
                execCmd = `PAGER=cat claude --dangerously-skip-permissions --print "${{escaped}}"`;
             }} else if (raw.startsWith("claude")) {{
                if (raw.trim() === "claude") {{
                    command = `claude --dangerously-skip-permissions -p ""`;
                    execCmd = `PAGER=cat claude --dangerously-skip-permissions -p ""`;
                }} else {{
                    command = raw;
                    execCmd = `PAGER=cat ${{raw}}`;
                }}
             }}
          }} else if (item.agent_type === "openclaw@2026.2.9") {{
             if (!raw.match(/^(ls|cd|pwd|cat|echo|openclaw|rm|mkdir|touch)/)) {{
                const escaped = raw.replaceAll('"', '\\"');
                command = `openclaw agent --session-id "${{item.container_name}}" --json --message "${{escaped}}"`;
                execCmd = command; // 显示并执行真实命令
             }} else if (raw.startsWith("openclaw")) {{
                command = raw;
                execCmd = `PAGER=cat ${{raw}}`;
             }}
          }}

          if (!window.cardStates[item.container_name]) {{
             window.cardStates[item.container_name] = logBox.textContent;
          }}
          window.cardStates[item.container_name] += `\\n$ ${{command}}\\n`;
          logBox.textContent = window.cardStates[item.container_name];
          logBox.scrollTop = logBox.scrollHeight;

          const r = await fetch(`/api/agents/${{encodeURIComponent(item.container_name)}}/command`, {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify({{ command: execCmd }}),
          }});
          const d = await r.json();
          if (!r.ok) {{
            window.cardStates[item.container_name] += `ERROR: ${{d.error || `HTTP ${{r.status}}`}}\\n`;
          }} else {{
            let outText = d.output || "(no output)";
            // Improved ANSI stripping regex
            outText = outText.replace(/\x1b\[[0-9;?]*[a-zA-Z]/g, '');
            outText = outText.replace(/\x1b\][^\x07]*\x07/g, '');
            outText = outText.replace(/\x1b[\(\)][A-Z]/g, ''); // charsets
            outText = outText.replace(/\x1b[=>]/g, ''); // keypad modes
            
            if (item.agent_type === "openclaw@2026.2.9") {{
               if (execCmd.includes("--json")) {{
                  try {{
                     const j = JSON.parse(outText);
                     if (j && j.result && j.result.payloads && j.result.payloads.length > 0) {{
                         outText = j.result.payloads.map(p => p.text).join("\\n");
                     }}
                  }} catch(e){{}}
               }}
               const cleanOutput = (text) => text.replace(/[\u001b\u009b][[()#;?]*(?:[0-9]{1,4}(?:;[0-9]{0,4})*)?[0-9A-ORZcf-nqry=><]/g, '');
               outText = cleanOutput(outText);
            }} else if (item.agent_type === "claude") {{
               const cleanOutput = (text) => text.replace(/[\u001b\u009b][[()#;?]*(?:[0-9]{1,4}(?:;[0-9]{0,4})*)?[0-9A-ORZcf-nqry=><]/g, '');
               outText = cleanOutput(outText);
            }}
            window.cardStates[item.container_name] += outText + "\\n";
          }}
          logBox.textContent = window.cardStates[item.container_name];
          logBox.scrollTop = logBox.scrollHeight;
          cmdInput.value = "";
        }};
        const execBtn = div.querySelector('button[data-action="exec"]');
        execBtn.onclick = runCommand;
        cmdInput.addEventListener("keydown", (e) => {{
          if (e.key === "Enter") {{
            e.preventDefault();
            runCommand();
          }}
        }});
        if (!managed) {{
          cmdInput.disabled = true;
          execBtn.disabled = true;
          cmdMode.disabled = true;
          cmdInput.placeholder = "该容器非18080创建（compose成员），默认只读显示";
          div.querySelector('button[data-action="recreate"]').disabled = true;
        }}
        return div;
      }}

      async function refreshCards() {{
        const res = await fetch(`/api/agents?tail=${{tail}}`, {{ cache: "no-store" }});
        const data = await res.json();
        
        // 避免粗暴清空重绘导致焦点丢失，我们采用替换卡片内容或只追加新卡片
        const existingNames = new Set(Array.from(cards.children).map(c => c.dataset.name));
        const newNames = new Set();

        for (const item of data.items || []) {{
          newNames.add(item.container_name);
          let card = document.querySelector(`.card[data-name="${{item.container_name}}"]`);
          if (!card) {{
            card = makeCard(item);
            card.dataset.name = item.container_name;
            cards.appendChild(card);
          }} else {{
            // 只更新状态和原始日志(如果用户还没交互过)
            const st = card.querySelector('.meta.status-running, .meta.status-other');
            if (st) {{
               st.className = `meta status-${{item.status === 'running' ? 'running' : 'other'}}`;
               st.textContent = item.status;
            }}
            if (!window.cardStates || !window.cardStates[item.container_name]) {{
               const logBox = card.querySelector('pre');
               if (logBox) logBox.textContent = item.logs || "";
            }}
          }}
        }}
        
        // 移除已经不存在的容器
        for (const name of existingNames) {{
           if (!newNames.has(name)) {{
              const card = document.querySelector(`.card[data-name="${{name}}"]`);
              if (card) card.remove();
           }}
        }}
      }}

      createBtn.onclick = async () => {{
        notice.textContent = "创建中...";
        const payload = {{
          type: agentType.value,
          name: agentName.value,
        }};
        const res = await fetch("/api/agents", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify(payload),
        }});
        const data = await res.json();
        if (!res.ok) {{
          notice.textContent = data.error || `HTTP ${{res.status}}`;
          return;
        }}
        notice.textContent = `已创建 ${{data.container_name}}`;
        agentName.value = "";
        await refreshCards();
      }};

      (async () => {{
        await loadTypes();
        await refreshCards();
        setInterval(refreshCards, {poll_ms});
      }})();
    </script>
  </body>
</html>"""
        return make_response(html)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
