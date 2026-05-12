INITIAL_MESSAGE = "你负责的是完整的开发、测试、发现bug、变更的流程，项目是web app 8082（端口号），web app 8082所在的目录是/home/agent/.{agent}/workspace/project，如果project文件夹有web app，请查看启动脚本是否存在，/home/agent/.{agent}/workspace/project/user_start.sh。如果不存在启动脚本，请立即写好启动脚本user_start.sh，输出日志到当前目录下的logs/start.log。并且整理日志文件logs/agent_tui.log里的主要内容，梳理出项目构建的结构和细节，总结最后3轮对话的内容。项目所有惯例信息都在systemreadme.md中记载，最后更新项目README.md和项目SKILL.md"
# Used in docker compose volume mount (docker-compose.yml) to bind frpc binary into containers.
FRPC_PATH = "/Users/jimjiang/Downloads/frpc"
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from io import BytesIO

import docker
from docker.types import LogConfig
from flask import Flask, jsonify, make_response, request, send_file
from flask_sock import Sock

# GLOBAL PARAMETERS
# Used in find_next_port (line 76) as the first generated agent host port.
START_HOST_PORT = 18081
# Used in find_next_port (line 76) as the upper bound for generated host ports.
END_HOST_PORT = 18999
# Used in create_agent (line 123) and API responses to enforce fixed in-container service port.
SERVICE_PORT = 8082
# Used in helper filters (line 52, 67) to identify containers created by this control plane.
MANAGED_LABEL_KEY = "hermit.managed"
# Used in create_agent (line 139) to mark new containers as managed by this control plane.
MANAGED_LABEL_VALUE = "true"
# Used in create_agent (line 127, 144) and validation to map UI type to image/config directory.
AGENT_SPECS = {
    "claude": {"image": "hermit-agent-claude:latest", "config_subdir": "claude"},
    "ollama": {"image": "hermit-agent-ollama:latest", "config_subdir": "ollama"},
    "openclaw@2026.2.9": {"image": "hermit-agent-openclaw-2026.2.9:latest", "config_subdir": "openclaw"},
}
# Used in API handlers (line 259, 300, 310) as default line count shown in each card.
DEFAULT_TAIL_LINES = 200
# Used in _safe_name_part (line 92) to sanitize user-provided agent names.
NAME_SANITIZE_PATTERN = re.compile(r"[^a-zA-Z0-9_-]+")
# Used in create_agent (line 132) and api_command (line 247) so container startup and exec run as non-root agent user.
AGENT_RUNTIME_USER = "agent"
# Used in create_app (line 46-50) and create_agent (line 118-130) to translate in-container paths to actual host bind mount paths when creating new containers via Docker socket.
HOST_CONFIG_ROOT_ENV = "HOST_CONFIG_ROOT"
# Used in create_app (line 46-50) and create_agent (line 118-130) to translate in-container paths to actual host bind mount paths when creating new containers via Docker socket.
HOST_WORKSPACES_ROOT_ENV = "HOST_WORKSPACES_ROOT"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def create_app(docker_client=None):
    app = Flask(__name__)
    sock = Sock(app)
    app.config["DOCKER_CLIENT"] = docker_client
    app.config["CONFIG_ROOT"] = "/config"
    app.config["WORKSPACES_ROOT"] = "/workspaces"
    app.config["HOST_CONFIG_ROOT"] = os.environ.get(HOST_CONFIG_ROOT_ENV) or app.config["CONFIG_ROOT"]
    # 容器内将 host.docker.internal 替换为宿主机实际路径（如果是相对路径 ./config）
    host_cfg = app.config["HOST_CONFIG_ROOT"]
    if host_cfg.startswith("./"):
        import subprocess
        try:
            pwd = subprocess.check_output(["sh", "-c", "echo $PWD"], text=True).strip()
            host_cfg = pwd + host_cfg[1:]
        except:
            pass
        app.config["HOST_CONFIG_ROOT"] = host_cfg
    app.config["HOST_WORKSPACES_ROOT"] = os.environ.get(HOST_WORKSPACES_ROOT_ENV) or app.config["WORKSPACES_ROOT"]
    # 处理相对路径 logs
    host_ws = app.config["HOST_WORKSPACES_ROOT"]
    if host_ws.startswith("./"):
        import subprocess
        try:
            pwd = subprocess.check_output(["sh", "-c", "echo $PWD"], text=True).strip()
            host_ws = pwd + host_ws[1:]
        except:
            pass
        app.config["HOST_WORKSPACES_ROOT"] = host_ws
    app.config["HOST_LOGS_ROOT"] = os.path.join(os.path.dirname(host_ws), "logs")

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
            if is_compose_member(c) and c.name not in ("hermit-control-18080", "hermit-ssh-gateway", "openclaw-gateway") and c.name.startswith("hermit-agent-"):
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

    FRPC_CONFIG_PATH = os.path.join(FRPC_PATH, "frpc.ini")

    def add_frpc_rule(port):
        section = f"mac{port}"
        entry = (
            f"\n[{section}]\n"
            f"type = tcp\n"
            f"local_ip = 0.0.0.0\n"
            f"local_port = {port}\n"
            f"remote_port = {port}\n"
        )
        try:
            with open(FRPC_CONFIG_PATH, "r", encoding="utf-8") as f:
                content = f.read()
            if f"[{section}]" in content:
                print(f"[frpc] port {port} already configured, skipping", flush=True, file=sys.stderr)
                return
            with open(FRPC_CONFIG_PATH, "a", encoding="utf-8") as f:
                f.write(entry)
            print(f"[frpc] added rule for port {port}, restarting frpc via docker-py...", flush=True, file=sys.stderr)
            try:
                client = docker_client_or_default()
                client.containers.get("frpc").restart()
                print(f"[frpc] frpc restarted successfully", flush=True, file=sys.stderr)
            except Exception as re:
                print(f"[frpc] WARNING: docker restart frpc failed: {re}", flush=True, file=sys.stderr)
        except Exception as e:
            print(f"[frpc] ERROR: {e}", flush=True, file=sys.stderr)

    def scp_rules_to_container(container_name, project_path):
        rules_dir = "/config/rules"
        if not os.path.exists(rules_dir):
            print(f"[scp] {rules_dir} does not exist, skipping", flush=True, file=sys.stderr)
            return
        files = [f for f in os.listdir(rules_dir) if os.path.isfile(os.path.join(rules_dir, f))]
        if not files:
            print(f"[scp] no files in {rules_dir}, skipping", flush=True, file=sys.stderr)
            return
        try:
            import paramiko, socket
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            print(f"[scp] waiting for SSH on {container_name}...", flush=True, file=sys.stderr)
            for attempt in range(1, 11):
                try:
                    ssh.connect(hostname=container_name, port=22, username="agent", password="agent", timeout=10, allow_agent=False, look_for_keys=False)
                    break
                except (socket.timeout, paramiko.ssh_exception.SSHException, OSError) as e:
                    print(f"[scp] attempt {attempt}/10 failed: {e}", flush=True, file=sys.stderr)
                    if attempt == 10:
                        raise
                    import time
                    time.sleep(2)
            sftp = ssh.open_sftp()
            for fname in files:
                src = os.path.join(rules_dir, fname)
                dst = os.path.join(project_path, fname)
                sftp.put(src, dst)
                print(f"[scp] copied {fname} -> {project_path}/", flush=True, file=sys.stderr)
            sftp.close()
            ssh.close()
            print(f"[scp] done, {len(files)} files copied", flush=True, file=sys.stderr)
        except Exception as e:
            print(f"[scp] ERROR: {e}", flush=True, file=sys.stderr)

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
        labels = ((getattr(container, "attrs", {}) or {}).get("Config", {}) or {}).get("Labels", {}) or (getattr(container, "labels", {}) or {})
        agent_type = labels.get("hermit.agent_type", "")
        if agent_type in ("claude", "ollama"):
            log_path = "/home/agent/.claude/workspace/project/logs/agent_tui.log"
        else:
            log_path = "/home/agent/.openclaw/workspace/project/logs/agent_tui.log"
        try:
            result = container.exec_run(["/bin/sh", "-lc", f"tail -{tail} '{log_path}' 2>/dev/null"], user=AGENT_RUNTIME_USER)
            if isinstance(result.output, bytes):
                return result.output.decode("utf-8", errors="replace")
            return str(result.output)
        except Exception:
            return ""

    def _full_logs(container):
        labels = ((getattr(container, "attrs", {}) or {}).get("Config", {}) or {}).get("Labels", {}) or (getattr(container, "labels", {}) or {})
        agent_type = labels.get("hermit.agent_type", "")
        if agent_type in ("claude", "ollama"):
            log_path = "/home/agent/.claude/workspace/project/logs/agent_tui.log"
        else:
            log_path = "/home/agent/.openclaw/workspace/project/logs/agent_tui.log"
        try:
            result = container.exec_run(["/bin/sh", "-lc", f"cat '{log_path}' 2>/dev/null"], user=AGENT_RUNTIME_USER)
            if isinstance(result.output, bytes):
                return result.output.decode("utf-8", errors="replace")
            return str(result.output)
        except Exception:
            return ""

    def create_agent(agent_type, custom_name, body=None):
        if agent_type not in AGENT_SPECS:
            raise ValueError("Unsupported agent type")
        spec = AGENT_SPECS[agent_type]
        host_port = find_next_port()
        normalized_name = _safe_name_part(custom_name)
        container_name = f"{host_port}-{normalized_name}"
        body = body or {}
        labels = {
            MANAGED_LABEL_KEY: MANAGED_LABEL_VALUE,
            "hermit.agent_type": agent_type,
            "hermit.host_port": str(host_port),
            "hermit.service_port": str(SERVICE_PORT),
        }
        host_config_root = app.config["HOST_CONFIG_ROOT"]
        host_workspaces_root = app.config["HOST_WORKSPACES_ROOT"]
        host_logs_root = app.config.get("HOST_LOGS_ROOT") or os.path.join(os.path.dirname(app.config["HOST_WORKSPACES_ROOT"]), "logs")
        os.makedirs(f"{host_logs_root}/{container_name}", exist_ok=True)
        os.makedirs(f"{host_workspaces_root}/{container_name}", exist_ok=True)
        os.chown(f"{host_logs_root}/{container_name}", 501, 20)
        os.chown(f"{host_workspaces_root}/{container_name}", 501, 20)
        if agent_type in ("claude", "ollama"):
            log_bind = "/home/agent/.claude/workspace/project/logs"
        else:
            log_bind = "/home/agent/.openclaw/workspace/project/logs"
        volumes = {
            f"{host_config_root}/{spec['config_subdir']}": {"bind": "/agent-config", "mode": "ro"},
            f"{host_workspaces_root}/{container_name}": {"bind": "/home/agent/.claude/workspace/project", "mode": "rw"},
            f"{host_workspaces_root}/{container_name}/sessions": {"bind": "/home/agent/.claude/projects", "mode": "rw"},
            f"{host_logs_root}/{container_name}": {"bind": log_bind, "mode": "rw"},
        }
        log_config = LogConfig(type=LogConfig.types.JSON, config={"max-size": "500m", "max-file": "2"})

        env_vars = {}
        if agent_type in ("claude", "ollama"):
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
            env_vars["OPENCLAW_GATEWAY_HOST"] = "172.30.0.10"
            env_vars["OPENCLAW_GATEWAY_PORT"] = "18790"

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
            network="hermit-claw_openclaw-network",
            extra_hosts=["host.docker.internal:host-gateway"],
        )

        # 创建容器后发送初始消息
        import time
        time.sleep(3)
        user_msg = (body.get("message") or "").strip()
        msg_file = "/tmp/send_msg.sh"
        if agent_type in ("claude", "ollama"):
            default_msg = INITIAL_MESSAGE.format(agent="claude")
            log_path = "/home/agent/.claude/workspace/project/logs/agent_tui.log"
            msg_to_send = user_msg or default_msg
            escaped_msg = msg_to_send.replace("'", "'\"'\"'")
            msg_b64 = __import__('base64').b64encode(msg_to_send.encode('utf-8')).decode('ascii')
            script = f"CLAUDE_MSG='{msg_b64}' node /home/agent/.claude/run_claude.js >> '{log_path}' 2>&1"
        else:
            default_msg = INITIAL_MESSAGE.format(agent="openclaw")
            log_path = "/home/agent/.openclaw/workspace/project/logs/agent_tui.log"
            msg_to_send = user_msg or default_msg
            escaped_msg = msg_to_send.replace("'", "'\"'\"'")
            msg_b64 = __import__('base64').b64encode(msg_to_send.encode('utf-8')).decode('ascii')
            script = f"node -e 'const fs=require(\"fs\"); const p=process.env.HOME+\"/.openclaw/openclaw.json\"; const j=JSON.parse(fs.readFileSync(p,\"utf8\")); delete j.gateway.bind; delete j.gateway.mode; fs.writeFileSync(p,JSON.stringify(j));'; echo '{msg_b64}' | base64 -d | openclaw agent --session-id main -m \"$(cat)\" >> '{log_path}' 2>&1"
        try:
            ts = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
            container.exec_run(["/bin/sh", "-c", f"echo '[{ts}] $ {escaped_msg}' >> '{log_path}'"], user=AGENT_RUNTIME_USER)
            container.exec_run(["/bin/sh", "-c", f"echo '{script}' > {msg_file} && chmod +x {msg_file}"], user=AGENT_RUNTIME_USER)
            container.exec_run(["/bin/sh", "-lc", f"nohup {msg_file} >> '{log_path}' 2>&1 &"], user=AGENT_RUNTIME_USER, detach=True)
        except Exception:
            pass

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
        host_logs_root = app.config.get("HOST_LOGS_ROOT") or os.path.join(os.path.dirname(host_workspaces_root), "logs")
        os.makedirs(f"{host_logs_root}/{container_name}", exist_ok=True)
        os.makedirs(f"{host_workspaces_root}/{container_name}", exist_ok=True)
        os.chown(f"{host_logs_root}/{container_name}", 501, 20)
        os.chown(f"{host_workspaces_root}/{container_name}", 501, 20)
        if agent_type in ("claude", "ollama"):
            log_bind = "/home/agent/.claude/workspace/project/logs"
        else:
            log_bind = "/home/agent/.openclaw/workspace/project/logs"
        volumes = {
            f"{host_config_root}/{spec['config_subdir']}": {"bind": "/agent-config", "mode": "ro"},
            f"{host_workspaces_root}/{container_name}": {"bind": "/home/agent/.claude/workspace/project", "mode": "rw"},
            f"{host_workspaces_root}/{container_name}/sessions": {"bind": "/home/agent/.claude/projects", "mode": "rw"},
            f"{host_logs_root}/{container_name}": {"bind": log_bind, "mode": "rw"},
        }
        log_config = LogConfig(type=LogConfig.types.JSON, config={"max-size": "500m", "max-file": "2"})
        container.remove(force=True)

        try:
            docker_client_or_default().images.pull(spec["image"])
        except Exception:
            pass

        env_vars = {}
        if agent_type in ("claude", "ollama"):
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
            network="hermit-claw_openclaw-network",
            extra_hosts=["host.docker.internal:host-gateway"],
        )
        return {"container_name": new_container.name, "agent_type": agent_type, "host_port": host_port, "ssh_port": host_port - 10000, "service_port": SERVICE_PORT, "recreated_at": now_iso()}

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
            "ssh_port": port - 10000 if port else None,
            "service_port": SERVICE_PORT,
            "managed": is_managed(container),
            "logs": _tail_logs(container, tail=200),
        }
        return item

    @app.get("/api/agents/<path:name>/ssh-info")
    def api_agent_ssh_info(name):
        try:
            container = docker_client_or_default().containers.get(name)
            return jsonify({
                "host": "localhost",
                "port": 22,
                "user": "agent",
                "password": "agent",
                "container": container.name,
            })
        except docker.errors.NotFound:
            return jsonify({"error": "Container not found"}), 404

    @app.get("/api/agents/<path:name>/ssh-terminal")
    def api_agent_ssh_terminal(name):
        try:
            container = docker_client_or_default().containers.get(name)
            container_name = container.name
            html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Terminal - {name}</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.css"/>
  <script src="https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/xterm-addon-fit@0.8.0/lib/xterm-addon-fit.js"></script>
  <style>
    body {{ margin: 0; padding: 4px; background: #1e1e1e; overflow: hidden; }}
    #terminal {{ width: 100%; height: 100vh; }}
  </style>
</head>
<body>
  <div id="terminal"></div>
  <script>
    const term = new Terminal({{ cursorBlink: true, fontSize: 14, fontFamily: 'Menlo, Monaco, "Courier New", monospace' }});
    const fitAddon = new FitAddon.FitAddon();
    term.loadAddon(fitAddon);
    term.open(document.getElementById('terminal'));
    fitAddon.fit();

    const wsProtocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = wsProtocol + '//' + location.host + '/ws/ssh?container={container_name}';
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {{
      term.write('\\x1b[32mConnected to {container_name} via SSH\\x1b[0m\\r\\n');
      term.onData(data => ws.send(data));
    }};

    ws.onmessage = (event) => {{
      term.write(event.data);
    }};

    ws.onclose = () => {{
      term.write('\\r\\n\\x1b[31m[Connection Closed]\\x1b[0m\\r\\n');
    }};

    ws.onerror = (err) => {{
      term.write('\\r\\n\\x1b[31m[WebSocket Error]\\x1b[0m\\r\\n');
    }};

    window.addEventListener('resize', () => fitAddon.fit());
  </script>
</body>
</html>"""
            return html, 200, {"Content-Type": "text/html"}
        except docker.errors.NotFound:
            return "Container not found", 404

    @sock.route("/ws/ssh")
    def ws_ssh(ws):
        import threading
        container_name = request.args.get("container")
        if not container_name:
            ws.close()
            return

        try:
            client = docker_client_or_default()
            try:
                container = client.containers.get(container_name)
            except Exception:
                ws.close()
                return
            labels = ((container.attrs or {}).get("Config", {}) or {}).get("Labels", {}) or {}
            agent_type = labels.get("hermit.agent_type", "")
            if agent_type in ("claude", "ollama"):
                project_path = "/home/agent/.claude/workspace/project"
            else:
                project_path = "/home/agent/.openclaw/workspace/project"

            import paramiko
        except ImportError:
            ws.send("paramiko not installed\r\n")
            ws.close()
            return

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            ssh.connect(
                hostname=container_name,
                port=22,
                username="agent",
                password="agent",
                timeout=10,
                allow_agent=False,
                look_for_keys=False,
            )
            transport = ssh.get_transport()
            if not transport:
                ws.close()
                return
            transport.set_keepalive(10)

            chan = ssh.invoke_shell(term="xterm-256color", width=80, height=24)
            chan.settimeout(0.1)

            chan.send(f"cd {project_path}\r")
            chan.send("clear\r")

            def pump():
                try:
                    while True:
                        if chan.exit_status_ready():
                            break
                        try:
                            data = chan.recv(65536)
                            if data:
                                ws.send(data.decode('utf-8', errors='replace'))
                            else:
                                break
                        except Exception:
                            pass
                except Exception:
                    pass
                finally:
                    try:
                        chan.close()
                    except Exception:
                        pass
                    ws.close()
                    ssh.close()

            t = threading.Thread(target=pump, daemon=True)
            t.start()

            while True:
                try:
                    msg = ws.receive(timeout=0.05)
                    if msg:
                        chan.send(msg)
                except Exception:
                    break

        except Exception as e:
            try:
                ws.send(f"\r\n[SSH Error: {e}]\r\n")
            except Exception:
                pass
            ws.close()
        finally:
            try:
                ssh.close()
            except Exception:
                pass

    @app.get("/api/agent-types")
    def api_agent_types():
        return jsonify({"items": [{"value": k, "label": k} for k in AGENT_SPECS]})

    @app.post("/api/claude-ask")
    def api_claude_ask():
        try:
            data = request.get_json() or {}
            user_message = data.get("message", "").strip()
            if not user_message:
                return jsonify({"error": "message is required"})
            system_prompt = "我问个问题，不需要改任何代码或者文件，参考文档在 config/ 目录（Use Skill: user-rules）里面"
            full_message = f"{system_prompt}\n\n{user_message}"
            log_file = "/logs/hermit/debug.log"
            import tempfile, os, json
            tmp_file = tempfile.mktemp(suffix=".txt", dir="/app")
            with open(tmp_file, "w", encoding="utf-8") as f:
                f.write(full_message)
            
            # 尝试从 config.json 提取 API Key
            env = os.environ.copy()
            config_path = "/config/claude/config.json"
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        cfg_data = json.load(f)
                        providers = (cfg_data.get("claude", {}).get("providers", {}).values())
                        for provider in providers:
                            env_cfg = provider.get("settingsConfig", {}).get("env", {})
                            auth_token = env_cfg.get("ANTHROPIC_AUTH_TOKEN")
                            if auth_token:
                                env["ANTHROPIC_API_KEY"] = str(auth_token)
                                break
                except Exception as e:
                    with open(log_file, "a", encoding="utf-8") as f:
                        f.write(f"Error loading config.json: {str(e)}\n")

            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"\n=== {now_iso()} ===\n")
                f.write(f"User message: {user_message}\n")
                f.write(f"Full message:\n{full_message}\n")
                f.write(f"Temp file: {tmp_file}\n")
                f.write(f"API Key present: {'Yes' if 'ANTHROPIC_API_KEY' in env else 'No'}\n")

            import subprocess
            # 移除 --dangerously-skip-permissions，确保在 root 下也能运行（如果配置了 config.json）
            # 增加 --add-dir /config 以允许访问配置目录
            result = subprocess.run(
                ["claude", "--continue", "-p", tmp_file, "--add-dir", "/config"],
                capture_output=True, text=True, timeout=120,
                env=env
            )
            os.unlink(tmp_file)
            output = result.stdout
            stderr = result.stderr
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"Return code: {result.returncode}\n")
                f.write(f"STDOUT:\n{output}\n")
                f.write(f"STDERR:\n{stderr}\n")
            return jsonify({"response": output or "(无输出)"})
        except subprocess.TimeoutExpired:
            return jsonify({"error": "请求超时（120秒）"})
        except Exception as e:
            return jsonify({"error": str(e)})

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
            payload = create_agent(agent_type, name, body)
            add_frpc_rule(payload["host_port"])
            if agent_type in ("claude", "ollama"):
                scp_rules_to_container(payload["container_name"], "/home/agent/.claude/workspace/project")
            else:
                scp_rules_to_container(payload["container_name"], "/home/agent/.openclaw/workspace/project")
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
            container = _require_managed(name)
            data = _full_logs(container).encode("utf-8")
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

    @app.post("/api/agents/<path:name>/send-message")
    def api_send_message(name):
        body = request.get_json(silent=True) or {}
        message = (body.get("message") or "").strip()
        try:
            container = _require_managed(name)
            labels = ((getattr(container, "attrs", {}) or {}).get("Config", {}) or {}).get("Labels", {}) or (getattr(container, "labels", {}) or {})
            agent_type = labels.get("hermit.agent_type", "")
            msg_file = "/tmp/send_msg.sh"
            if agent_type in ("claude", "ollama"):
                default_msg = INITIAL_MESSAGE.format(agent="claude")
                log_path = "/home/agent/.claude/workspace/project/logs/agent_tui.log"
                msg_to_send = message or default_msg
                escaped_msg = msg_to_send.replace("'", "'\"'\"'")
                msg_b64 = __import__('base64').b64encode(msg_to_send.encode('utf-8')).decode('ascii')
                script = f"CLAUDE_MSG='{msg_b64}' node /home/agent/.claude/run_claude.js >> '{log_path}' 2>&1"
            else:
                default_msg = INITIAL_MESSAGE.format(agent="openclaw")
                log_path = "/home/agent/.openclaw/workspace/project/logs/agent_tui.log"
                msg_to_send = message or default_msg
                escaped_msg = msg_to_send.replace("'", "'\"'\"'")
                msg_b64 = __import__('base64').b64encode(msg_to_send.encode('utf-8')).decode('ascii')
                script = f"node -e 'const fs=require(\"fs\"); const p=process.env.HOME+\"/.openclaw/openclaw.json\"; const j=JSON.parse(fs.readFileSync(p,\"utf8\")); delete j.gateway.bind; delete j.gateway.mode; fs.writeFileSync(p,JSON.stringify(j));'; echo '{msg_b64}' | base64 -d | openclaw agent --session-id main -m \"$(cat)\" >> '{log_path}' 2>&1"
            try:
                ts = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                container.exec_run(["/bin/sh", "-c", f"echo '[{ts}] $ {escaped_msg}' >> '{log_path}'"], user=AGENT_RUNTIME_USER)
                container.exec_run(["/bin/sh", "-c", f"echo '{script}' > {msg_file} && chmod +x {msg_file}"], user=AGENT_RUNTIME_USER)
                container.exec_run(["/bin/sh", "-lc", f"nohup {msg_file} >> '{log_path}' 2>&1 &"], user=AGENT_RUNTIME_USER, detach=True)
            except Exception as e:
                return jsonify({"error": str(e)}), 500
            return jsonify({"ok": True, "container_name": name, "message": message, "agent_type": agent_type, "sent_at": now_iso()})
        except PermissionError as e:
            return jsonify({"error": str(e)}), 403
        except docker.errors.NotFound:
            return jsonify({"error": "Container not found"}), 404
        except Exception as e:
            return jsonify({"error": str(e)}), 500

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

    @app.post("/api/agents/<path:name>/cleanup-context")
    def api_cleanup_context(name):
        try:
            container = _require_managed(name)
            labels = ((container.attrs or {}).get("Config", {}) or {}).get("Labels", {}) or {}
            agent_type = labels.get("hermit.agent_type", "")
            if agent_type in ("claude", "ollama"):
                cmd = "rm -f ~/.claude/projects/*/*.jsonl 2>/dev/null; echo done"
            else:
                cmd = "rm -f ~/.openclaw/projects/*/*.jsonl 2>/dev/null; echo done"
            result = container.exec_run(["/bin/sh", "-lc", cmd], user=AGENT_RUNTIME_USER)
            output = result.output.decode("utf-8", errors="replace").strip()
            return jsonify({"ok": True, "container_name": name, "output": output})
        except PermissionError as e:
            return jsonify({"error": str(e)}), 403
        except docker.errors.NotFound:
            return jsonify({"error": "Container not found"}), 404
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.get("/api/agents/<path:name>/git-commits")
    def api_git_commits(name):
        try:
            container = _require_managed(name)
            labels = ((container.attrs or {}).get("Config", {}) or {}).get("Labels", {}) or {}
            agent_type = labels.get("hermit.agent_type", "")
            if agent_type in ("claude", "ollama"):
                project_path = "/home/agent/.claude/workspace/project"
            else:
                project_path = "/home/agent/.openclaw/workspace/project"
            cmd = f'cd {project_path} && git -c safe.directory=* rev-parse --short HEAD && git -c safe.directory=* log --format="%h %ad %s" --date=short -20'
            result = container.exec_run(["/bin/sh", "-lc", cmd], user=AGENT_RUNTIME_USER)
            output = result.output.decode("utf-8", errors="replace").strip()
            
            debug_log = "/logs/hermit/debug.log"
            with open(debug_log, "a", encoding="utf-8") as f:
                f.write(f"\n=== GIT COMMITS DEBUG ===\n")
                f.write(f"container: {name}\n")
                f.write(f"cmd: {cmd}\n")
                f.write(f"exit_code: {result.exit_code}\n")
                f.write(f"output:\n{output}\n")

            if result.exit_code != 0:
                return jsonify({"error": "项目不是 git 仓库"})
            
            lines = output.split("\n")
            current_commit = lines[0].strip()
            log_lines = lines[1:]
            
            commits = []
            for line in log_lines:
                if line.strip() and len(line) >= 10:
                    parts = line.split(" ", 2)
                    if len(parts) >= 2:
                        commit_hash = parts[0]
                        date_str = parts[1]
                        message = parts[2] if len(parts) > 2 else ""
                        is_current = "✓" if commit_hash == current_commit else ""
                        commits.append({
                            "hash": commit_hash, 
                            "message": f"[{date_str}] {message}", 
                            "is_current": is_current
                        })
            return jsonify({"commits": commits})
        except PermissionError as e:
            return jsonify({"error": str(e)}), 403
        except docker.errors.NotFound:
            return jsonify({"error": "Container not found"}), 404
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.post("/api/agents/<path:name>/git-reset")
    def api_git_reset(name):
        try:
            container = _require_managed(name)
            data = request.get_json() or {}
            commit_hash = data.get("commit_hash", "")
            if not commit_hash:
                return jsonify({"error": "commit_hash is required"}), 400
            labels = ((container.attrs or {}).get("Config", {}) or {}).get("Labels", {}) or {}
            agent_type = labels.get("hermit.agent_type", "")
            if agent_type in ("claude", "ollama"):
                project_path = "/home/agent/.claude/workspace/project"
            else:
                project_path = "/home/agent/.openclaw/workspace/project"
            cmd = f"cd {project_path} && git -c safe.directory=* checkout {commit_hash} 2>&1 && sleep 5"
            result = container.exec_run(["/bin/sh", "-lc", cmd], user=AGENT_RUNTIME_USER)
            output = result.output.decode("utf-8", errors="replace").strip()
            payload = recreate_agent(name)
            add_frpc_rule(payload["host_port"])
            if agent_type in ("claude", "ollama"):
                scp_rules_to_container(payload["container_name"], "/home/agent/.claude/workspace/project")
            else:
                scp_rules_to_container(payload["container_name"], "/home/agent/.openclaw/workspace/project")
            return jsonify({"ok": True, "container_name": name, "commit_hash": commit_hash, "git_output": output, "new_container": payload["container_name"]})
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except PermissionError as e:
            return jsonify({"error": str(e)}), 403
        except docker.errors.NotFound:
            return jsonify({"error": "Container not found"}), 404
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.post("/api/agents/<path:name>/recreate")
    def api_recreate_agent(name):
        try:
            container = docker_client_or_default().containers.get(name)
            if not is_managed(container):
                return jsonify({"error": "Only managed agents can be recreated"}), 400
            labels = ((container.attrs or {}).get("Config", {}) or {}).get("Labels", {}) or {}
            agent_type = labels.get("hermit.agent_type", "")
            payload = recreate_agent(name)
            add_frpc_rule(payload["host_port"])
            if agent_type in ("claude", "ollama"):
                scp_rules_to_container(payload["container_name"], "/home/agent/.claude/workspace/project")
            else:
                scp_rules_to_container(payload["container_name"], "/home/agent/.openclaw/workspace/project")
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
                labels = ((c.attrs or {}).get("Config", {}) or {}).get("Labels", {}) or {}
                agent_type = labels.get("hermit.agent_type", "")
                payload = recreate_agent(c.name)
                add_frpc_rule(payload["host_port"])
                if agent_type in ("claude", "ollama"):
                    scp_rules_to_container(payload["container_name"], "/home/agent/.claude/workspace/project")
                else:
                    scp_rules_to_container(payload["container_name"], "/home/agent/.openclaw/workspace/project")
                recreated.append(payload)
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
      .card.collapsed .card-body {{ display: none; }}
      .collapse-btn {{ background: none; border: none; color: #888; cursor: pointer; font-size: 12px; padding: 4px; }}
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
        <div style="display:flex;align-items:center;gap:20px;margin-bottom:12px;">
          <h1 style="margin:0;">HERMIT</h1>
          <div style="display:flex;align-items:center;gap:8px;">
            <input id="claudeQuery" placeholder="问个问题..." style="padding:6px 12px;background:rgba(255,255,255,0.1);border:1px solid rgba(255,255,255,0.2);border-radius:4px;color:#fff;width:300px;" />
            <button id="claudeAsk" style="padding:6px 12px;background:#3AE374;color:#000;border:none;border-radius:4px;cursor:pointer;font-weight:600;">询问</button>
          </div>
        </div>
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
      const claudeQuery = document.getElementById("claudeQuery");
      const claudeAsk = document.getElementById("claudeAsk");
      const tail = 20;

      claudeAsk.onclick = async () => {{
        const q = claudeQuery.value.trim();
        if (!q) return;
        claudeAsk.disabled = true;
        claudeAsk.textContent = "处理中...";
        try {{
          const res = await fetch("/api/claude-ask", {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify({{ message: q }}),
          }});
          const data = await res.json();
          if (data.error) {{
            showModal("错误", data.error);
          }} else {{
            showModal("HERMIT 回答", data.response);
          }}
        }} catch(e) {{
          showModal("请求失败", e.message);
        }} finally {{
          claudeAsk.disabled = false;
          claudeAsk.textContent = "询问";
        }}
      }};
      claudeQuery.onkeydown = (e) => {{
        if (e.key === "Enter") claudeAsk.click();
      }};

      function showModal(title, content) {{
        const overlay = document.createElement("div");
        overlay.style.cssText = "position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.75);z-index:1000;display:flex;align-items:center;justify-content:center;";
        const box = document.createElement("div");
        box.style.cssText = "background:#1a1a2e;border:1px solid rgba(255,255,255,0.2);border-radius:12px;padding:24px;max-width:700px;width:90%;max-height:80vh;display:flex;flex-direction:column;";
        const header = document.createElement("div");
        header.style.cssText = "display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;";
        header.innerHTML = `<span style="font-size:18px;font-weight:bold;color:#fff;">${title}</span><button id="copyBtn" style="padding:6px 12px;background:#3AE374;color:#000;border:none;border-radius:4px;cursor:pointer;font-weight:600;font-size:12px;">复制</button>`;
        const contentDiv = document.createElement("div");
        contentDiv.style.cssText = "flex:1;overflow:auto;padding:16px;background:#0d0d1a;border-radius:8px;border:1px solid rgba(255,255,255,0.1);white-space:pre-wrap;word-break:break-word;max-height:60vh;font-size:13px;line-height:1.5;color:#e0e0e0;";
        contentDiv.textContent = content;
        box.appendChild(header);
        box.appendChild(contentDiv);
        overlay.appendChild(box);
        document.body.appendChild(overlay);
        document.getElementById("copyBtn").onclick = () => {{
          navigator.clipboard.writeText(content).then(() => {{
            const btn = document.getElementById("copyBtn");
            btn.textContent = "已复制!";
            btn.style.background = "#666";
            setTimeout(() => {{ btn.textContent = "复制"; btn.style.background = "#3AE374"; }}, 1500);
          }});
        }};
        overlay.onclick = (e) => {{ if (e.target === overlay) overlay.remove(); }};
      }};

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
        div.className = "card collapsed";
        div.dataset.name = item.container_name;
        const stCls = item.status === "running" ? "status-running" : "status-other";
        const managed = !!item.managed;
        const sshPort = item.ssh_port;
        div.innerHTML = `
          <div class="card-head">
            <div style="display:flex;align-items:center;gap:8px;">
              <button class="collapse-btn" data-action="collapse">▶</button>
              <div style="display:flex;flex-direction:column;gap:2px;">
                <div style="display:flex;align-items:center;gap:8px;">
                  <span class="card-title" data-action="git-dropdown" style="cursor:pointer;color:#2196F3;font-weight:500;">${{item.container_name}}</span>
                  <select class="git-select" data-action="git-select" style="display:none;padding:2px 4px;font-size:11px;max-width:200px;">
                    <option value="">加载中...</option>
                  </select>
                </div>
                <div class="meta">${{item.agent_type}} · ${{item.host_port}}:{SERVICE_PORT} · SSH:${{item.ssh_port}}</div>
              </div>
            </div>
            <div class="meta ${{stCls}}" data-status="${{item.status}}" data-port="${{item.host_port}}">${{item.status}}</div>
          </div>
          <div class="card-body">
          <div class="actions">
            <button data-action="ssh">SSH终端</button>
            <button data-action="refresh">刷新日志</button>
            <button data-action="download">下载日志</button>
            <button data-action="recreate">重建</button>
            <button data-action="cleanup-context">清理上下文</button>
            <button data-action="init">发送初始消息</button>
          </div>
          <div class="cmd-bar">
            <textarea class="cmd-input" data-role="cmd-input" placeholder="输入对话内容" style="flex:1; resize:vertical; min-height:60px;"></textarea>
            <button data-action="send">发送</button>
          </div>
          <pre id="log-${{item.container_name}}" class="log-view">${{item.logs || ""}}</pre>
          <iframe id="ssh-${{item.container_name}}" class="ssh-view" style="display:none; width:100%; height:400px; border:1px solid #ccc;" src=""></iframe>
          </div>
        `;
        const collapseBtn = div.querySelector('.collapse-btn');
        const cardBody = div.querySelector('.card-body');
        collapseBtn.onclick = () => {{
          div.classList.toggle("collapsed");
          collapseBtn.textContent = div.classList.contains("collapsed") ? "▶" : "▼";
        }};
        const logBox = div.querySelector("pre");
        const sshIframe = div.querySelector("iframe");
        const sshBtn = div.querySelector('button[data-action="ssh"]');
        const cmdInput = div.querySelector('[data-role="cmd-input"]');
        let sshActive = false;
        sshBtn.onclick = () => {{
          sshActive = !sshActive;
          sshBtn.style.fontWeight = sshActive ? "bold" : "";
          sshBtn.style.background = sshActive ? "#4caf50" : "";
          if (sshActive) {{
            sshIframe.src = `/api/agents/${{encodeURIComponent(item.container_name)}}/ssh-terminal`;
            logBox.style.display = "none";
            sshIframe.style.display = "block";
          }} else {{
            sshIframe.src = "";
            sshIframe.style.display = "none";
            logBox.style.display = "block";
          }}
        }};
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
        div.querySelector('button[data-action="init"]').onclick = async () => {{
          const r = await fetch(`/api/agents/${{encodeURIComponent(item.container_name)}}/send-message`, {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify({{ message: "" }}),
          }});
          if (!r.ok) {{
            const d = await r.json();
            logBox.textContent += `\\nERROR: ${{d.error || `HTTP ${{r.status}}`}}\\n`;
            return;
          }}
          logBox.textContent += `\n(已发送初始消息)\n`;
        }};
        div.querySelector('button[data-action="cleanup-context"]').onclick = async () => {{
          const r = await fetch(`/api/agents/${{encodeURIComponent(item.container_name)}}/cleanup-context`, {{ method: "POST" }});
          if (!r.ok) {{
            const d = await r.json();
            logBox.textContent += `\nERROR: ${{d.error || `HTTP ${{r.status}}`}}\n`;
            return;
          }}
          const d = await r.json();
          logBox.textContent += `\n(上下文已清理) ${{d.output || ""}}\n`;
        }};
        
        const cardTitle = div.querySelector('.card-title');
        const gitSelect = div.querySelector('.git-select');
        const loadGitCommits = async () => {{
          try {{
            const r = await fetch(`/api/agents/${{encodeURIComponent(item.container_name)}}/git-commits`);
            const d = await r.json();
            if (d.error) {{
              gitSelect.innerHTML = '<option value="">非Git项目</option>';
              return;
            }}
            gitSelect.innerHTML = '<option value="">选择版本...</option>';
            (d.commits || []).forEach(c => {{
              const opt = document.createElement("option");
              opt.value = c.hash;
              opt.textContent = (c.is_current ? "✓ " : "") + c.message;
              gitSelect.appendChild(opt);
            }});
          }} catch(e) {{
            console.error("Failed to load git commits:", e);
          }}
        }};
        
        cardTitle.onclick = () => {{
          if (gitSelect.style.display === "none") {{
            gitSelect.style.display = "inline-block";
            if (gitSelect.options.length <= 1) loadGitCommits();
          }} else {{
            gitSelect.style.display = "none";
          }}
        }};
        
        gitSelect.onchange = async () => {{
          const hash = gitSelect.value;
          if (!hash) return;
          if (!managed) return;
          gitSelect.style.display = "none";
          logBox.textContent += `\n[git checkout ${{hash.substring(0,7)}}] 执行中...\n`;
          const r = await fetch(`/api/agents/${{encodeURIComponent(item.container_name)}}/git-reset`, {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify({{ commit_hash: hash }}),
          }});
          const d = await r.json();
          if (!r.ok) {{
            logBox.textContent += `ERROR: ${{d.error || `HTTP ${{r.status}}`}}\n`;
            return;
          }}
          logBox.textContent += `[git checkout 完成] ${{d.git_output || ""}}\n[容器重建中] ${{d.new_container}}\n`;
          await refreshCards();
        }};
        
        div.querySelector('button[data-action="send"]').onclick = () => sendMessage();
        
        const cardKey = `card_${{item.container_name}}`;
        if (!window.cardStates) window.cardStates = {{}};
        
        const formatTime = () => {{
          const d = new Date();
          return d.getFullYear() + "-" + String(d.getMonth()+1).padStart(2,"0") + "-" + String(d.getDate()).padStart(2,"0") + " " + String(d.getHours()).padStart(2,"0") + ":" + String(d.getMinutes()).padStart(2,"0") + ":" + String(d.getSeconds()).padStart(2,"0");
        }};
        
        const sendMessage = async () => {{
          const msg = (cmdInput.value || "").trim();
          if (!msg) return;
          window.cardStates[item.container_name] = logBox.textContent;
          window.cardStates[item.container_name] += "\\n" + formatTime() + " $ " + msg + "\\n";
          logBox.textContent = window.cardStates[item.container_name];
          logBox.scrollTop = logBox.scrollHeight;
          cmdInput.value = "";
          
          const r = await fetch(`/api/agents/${{encodeURIComponent(item.container_name)}}/send-message`, {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify({{ message: msg }}),
          }});
          if (!r.ok) {{
            const d = await r.json();
            window.cardStates[item.container_name] += `ERROR: ${{d.error || `HTTP ${{r.status}}`}}\\n`;
          }}
          logBox.textContent = window.cardStates[item.container_name];
          logBox.scrollTop = logBox.scrollHeight;
          
          await new Promise(resolve => setTimeout(resolve, 3000));
          const logResp = await fetch(`/api/agents/${{encodeURIComponent(item.container_name)}}/logs?tail=500`, {{ cache: "no-store" }});
          if (logResp.ok) {{
            const logData = await logResp.json();
            if (logData.logs) {{
              window.cardStates[item.container_name] = logData.logs;
              logBox.textContent = window.cardStates[item.container_name];
              logBox.scrollTop = logBox.scrollHeight;
            }}
          }}
        }};
        if (!managed) {{
          cmdInput.disabled = true;
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
            const stDiv = card.querySelector('.meta[data-status]');
            if (stDiv && stDiv.dataset.status === 'running') {{
                const port = stDiv.dataset.port;
                stDiv.innerHTML = `<a href="http://dimond.top:${{port}}" target="_blank" style="color:inherit;text-decoration:underline;" onclick="event.stopPropagation()">running</a>`;
            }}
          }} else {{
            // 只更新状态和原始日志(如果用户还没交互过)
            const st = card.querySelector('.meta[data-status]') || card.querySelector('.meta.status-running, .meta.status-other');
            if (st) {{
               st.className = `meta status-${{item.status === 'running' ? 'running' : 'other'}}`;
               st.textContent = item.status;
               if (item.status === 'running') {{
                   st.innerHTML = `<a href="http://dimond.top:${{item.host_port}}" target="_blank" style="color:inherit;text-decoration:underline;" onclick="event.stopPropagation()">running</a>`;
               }}
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
