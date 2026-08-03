INITIAL_MESSAGE = "你负责的是完整的开发、测试、发现bug、变更的流程，项目是web app 8082（端口号），web app 8082所在的目录是/home/agent/.{agent}/workspace/project，如果project文件夹有web app，请查看启动脚本是否存在，/home/agent/.{agent}/workspace/project/user_start.sh。如果不存在启动脚本，请立即写好启动脚本user_start.sh，输出日志到当前目录下的logs/start.log。并且整理日志文件logs/agent_tui.log里的主要内容，梳理出项目构建的结构和细节，总结最后3轮对话的内容。项目所有惯例信息都在systemreadme.md中记载，最后更新项目README.md和项目SKILL.md"
# TOOL_INITIAL_MESSAGE: 工具类容器专属初始提示词（FORK为工具功能部署完成后发送）
# 与普通容器不同：部署完成后必须到 18081 注册 doc（通过 /api/tools 接口，规范见 systemreadme.md 第15章）
# 使用位置：create_agent() 初始消息发送逻辑（tool=True 时替代 INITIAL_MESSAGE）
TOOL_INITIAL_MESSAGE = "你负责的是完整的开发、测试、发现bug、变更的流程，项目是web app 8082（端口号），web app 8082所在的目录是/home/agent/.{agent}/workspace/project，如果project文件夹有web app，请查看启动脚本是否存在，/home/agent/.{agent}/workspace/project/user_start.sh。如果不存在启动脚本，请立即写好启动脚本user_start.sh，输出日志到当前目录下的logs/start.log。并且整理日志文件logs/agent_tui.log里的主要内容，梳理出项目构建的结构和细节，总结最后3轮对话的内容。项目所有惯例信息都在systemreadme.md中记载，最后更新项目README.md和项目SKILL.md。与普通容器不同，你部署好以后必须到18081注册doc：调用 POST http://host.docker.internal:18081/api/tools 接口，请求体为JSON格式，包含port字段(填你的宿主机端口)、name字段(工具唯一名称)、display_name(显示名称)、description(简短描述)、doc_md字段(完整Markdown文档，需包含功能概览表格、所有API端点及说明、使用示例)。注册后可调用 GET http://host.docker.internal:18081/api/tools 验证。详细规范见systemreadme.md第十五章（18081 Hub Tools 知识库接口）。"
# TOOL_START_PORT: 工具类容器起始宿主机端口（FORK为工具功能从 18000 开始注册端口）
TOOL_START_PORT = 18000  # 使用位置：find_tool_port() 端口分配、is_tool() 工具容器判断
# TOOL_END_PORT: 工具类容器终止宿主机端口
TOOL_END_PORT = 18079  # 使用位置：find_tool_port() 端口分配上限、is_tool() 工具容器判断
# Used in docker compose volume mount (docker-compose.yml) to bind frpc binary into containers.
FRPC_PATH = "/Users/jimjiang/Downloads/frpc"
import json
import os
import re
import sys
import subprocess
import base64
import tempfile
import uuid
import threading
import time
from datetime import datetime, timezone, timedelta
from io import BytesIO
from urllib.request import urlopen, Request
from urllib.error import URLError

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
COMMIT_HASH_PATTERN = re.compile(r"^[0-9a-fA-F]{4,40}$")
# Used in create_agent (line 132) and api_command (line 247) so container startup and exec run as non-root agent user.
AGENT_RUNTIME_USER = "agent"
# Used in create_app (line 46-50) and create_agent (line 118-130) to translate in-container paths to actual host bind mount paths when creating new containers via Docker socket.
HOST_CONFIG_ROOT_ENV = "HOST_CONFIG_ROOT"
# Used in create_app (line 46-50) and create_agent (line 118-130) to translate in-container paths to actual host bind mount paths when creating new containers via Docker socket.
HOST_WORKSPACES_ROOT_ENV = "HOST_WORKSPACES_ROOT"
# agent_states: 容器卡片状态字典，key=container_name, value="idle"|"thinking"|"done"
# "idle": 空闲（绿色） / "thinking": 思考中（黄色） / "done": 回答完毕（红色+闪烁）
# 由 send-message(L942) 设 thinking，SessionEnd 钩子(L1008) 设 done，reset-state(L1008) 恢复 idle
agent_states = {}

# EMAIL_TRACK_FILE: SessionEnd 邮件通知追踪文件，存储 UUID→track_info 映射
# 用于回复链监控，格式: {"<uuid>": {"container_name":"...", "sent_at":"...", "ttl":"...", "subject_prefix":"...", "reply_chain":[], "last_checked":"..."}}
EMAIL_TRACK_FILE = os.path.join(os.path.dirname(__file__), "..", "logs", "email_tracks.json")
# EMAIL_SERVICE_URL: 远程邮件服务基址（email-sender skill 部署地址）
EMAIL_SERVICE_URL = "http://dimond.top:5030"
# EMAIL_OWNER: 主人邮箱，通知发送目标 + 回复监控源
EMAIL_OWNER = "939342547@qq.com"
# EMAIL_CHECK_INTERVAL: 邮件回复检查间隔（秒），默认 24 小时
EMAIL_CHECK_INTERVAL = 24 * 3600


def _load_email_tracks():
    try:
        if os.path.isfile(EMAIL_TRACK_FILE):
            with open(EMAIL_TRACK_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_email_tracks(tracks):
    os.makedirs(os.path.dirname(EMAIL_TRACK_FILE), exist_ok=True)
    with open(EMAIL_TRACK_FILE, "w", encoding="utf-8") as f:
        json.dump(tracks, f, ensure_ascii=False, indent=2)

def _send_email_via_service(subject, body):
    """通过远程邮件服务发送邮件，返回 (ok, message)"""
    try:
        data = json.dumps({"to": EMAIL_OWNER, "subject": subject, "body": body}).encode("utf-8")
        req = Request(f"{EMAIL_SERVICE_URL}/send-email/", data=data,
                       headers={"Content-Type": "application/json"})
        resp = urlopen(req, timeout=30)
        result = json.loads(resp.read().decode("utf-8"))
        return result.get("success", False), result.get("message", "")
    except Exception as e:
        return False, str(e)


def _fetch_recent_emails(days=1):
    """从邮件服务拉取最近N天的邮件，返回 [{id, subject, sender, date, body}]"""
    try:
        url = f"{EMAIL_SERVICE_URL}/emails/?limit=50&days={days}"
        resp = urlopen(url, timeout=30)
        return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []


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

    def is_tool(container):
        """18000-18079 工具类容器，不在 control 面板展示"""
        name = getattr(container, "name", "") or ""
        if name.startswith("hermit-tool-"):
            return True
        labels = ((getattr(container, "attrs", {}) or {}).get("Config", {}) or {}).get("Labels", {}) or (getattr(container, "labels", {}) or {})
        if labels.get("hermit.tool") == "true":
            return True
        port = container_host_port(container)
        return port is not None and TOOL_START_PORT <= port <= TOOL_END_PORT

    def display_containers():
        items = []
        for c in all_containers():
            if is_tool(c):
                continue
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
            for attempt in range(1, 16):
                try:
                    ssh.connect(hostname=container_name, port=22, username="agent", password="agent", timeout=15, allow_agent=False, look_for_keys=False)
                    break
                except (socket.timeout, paramiko.ssh_exception.SSHException, OSError) as e:
                    print(f"[scp] attempt {attempt}/15 failed: {e}", flush=True, file=sys.stderr)
                    if attempt == 15:
                        raise
                    import time
                    time.sleep(3)
            sftp = ssh.open_sftp()
            for fname in files:
                src = os.path.join(rules_dir, fname)
                dst = os.path.join(project_path, fname)
                sftp.put(src, dst)
                print(f"[scp] copied {fname} -> {project_path}/", flush=True, file=sys.stderr)
            sftp.close()
            stdin, stdout, stderr = ssh.exec_command(f"chmod -R +x {project_path} 2>/dev/null || true")
            print(f"[scp] chmod -R +x {project_path}", flush=True, file=sys.stderr)
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

    def find_tool_port():
        # 工具类端口分配：遍历 TOOL_START_PORT..TOOL_END_PORT（18000-18079）
        # 遍历全部容器（含 hermit-tool-* 非 managed 容器），避免与既有工具端口冲突
        used = {p for p in [container_host_port(c) for c in all_containers()] if p is not None}
        for port in range(TOOL_START_PORT, TOOL_END_PORT + 1):
            if port not in used:
                return port
        raise RuntimeError("No available tool host port in configured range")

    def project_path_for_agent_type(agent_type):
        if agent_type in ("claude", "ollama"):
            return "/home/agent/.claude/workspace/project"
        return "/home/agent/.openclaw/workspace/project"

    def log_path_for_agent_type(agent_type):
        if agent_type in ("claude", "ollama"):
            return "/home/agent/.claude/workspace/project/logs/agent_tui.log"
        return "/home/agent/.openclaw/workspace/project/logs/agent_tui.log"

    def derive_agent_basename(container_name):
        m = re.match(r"^\d+-(.+)$", container_name or "")
        if m:
            return m.group(1)
        return _safe_name_part(container_name)

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
        log_path = log_path_for_agent_type(agent_type)
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
        log_path = log_path_for_agent_type(agent_type)
        try:
            result = container.exec_run(["/bin/sh", "-lc", f"cat '{log_path}' 2>/dev/null"], user=AGENT_RUNTIME_USER)
            if isinstance(result.output, bytes):
                return result.output.decode("utf-8", errors="replace")
            return str(result.output)
        except Exception:
            return ""

    def _copy_workspace_tree(src_dir, dst_dir):
        import subprocess, shutil
        if not os.path.isdir(src_dir):
            raise FileNotFoundError(f"Source workspace not found: {src_dir}")
        if os.path.exists(dst_dir):
            raise FileExistsError(f"目标工作空间已存在: {dst_dir}，请先删除再试")
        result = subprocess.run(["cp", "-a", src_dir, dst_dir], capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"copy failed: {result.stderr}")
        sessions_dir = os.path.join(dst_dir, "sessions")
        os.makedirs(sessions_dir, exist_ok=True)
        try:
            os.chown(dst_dir, 501, 20)
            os.chown(sessions_dir, 501, 20)
        except Exception:
            pass

    def create_agent(agent_type, custom_name, body=None, tool=False):
        if agent_type not in AGENT_SPECS:
            raise ValueError("Unsupported agent type")
        spec = AGENT_SPECS[agent_type]
        host_port = find_tool_port() if tool else find_next_port()
        normalized_name = _safe_name_part(custom_name)
        container_name = f"{host_port}-{normalized_name}"
        body = body or {}
        labels = {
            MANAGED_LABEL_KEY: MANAGED_LABEL_VALUE,
            "hermit.agent_type": agent_type,
            "hermit.host_port": str(host_port),
            "hermit.service_port": str(SERVICE_PORT),
        }
        if tool:
            labels["hermit.tool"] = "true"
        host_config_root = app.config["HOST_CONFIG_ROOT"]
        host_workspaces_root = app.config["HOST_WORKSPACES_ROOT"]
        host_logs_root = app.config.get("HOST_LOGS_ROOT") or os.path.join(os.path.dirname(app.config["HOST_WORKSPACES_ROOT"]), "logs")
        os.makedirs(f"{host_logs_root}/{container_name}", exist_ok=True)
        os.makedirs(f"{host_workspaces_root}/{container_name}", exist_ok=True)
        os.makedirs(f"{host_workspaces_root}/{container_name}/sessions", exist_ok=True)
        os.chown(f"{host_logs_root}/{container_name}", 501, 20)
        os.chown(f"{host_workspaces_root}/{container_name}", 501, 20)
        os.chown(f"{host_workspaces_root}/{container_name}/sessions", 501, 20)
        if agent_type in ("claude", "ollama"):
            log_bind = "/home/agent/.claude/workspace/project/logs"
        else:
            log_bind = "/home/agent/.openclaw/workspace/project/logs"
        volumes = {
            f"{host_config_root}/{spec['config_subdir']}": {"bind": "/agent-config", "mode": "ro"},
            f"{host_workspaces_root}/{container_name}": {"bind": "/home/agent/.claude/workspace/project", "mode": "rw"},
            f"{host_workspaces_root}/{container_name}/sessions": {"bind": "/home/agent/.claude/projects", "mode": "rw"},
            f"{host_logs_root}/{container_name}": {"bind": log_bind, "mode": "rw"},
            f"{host_config_root}/rules": {"bind": "/home/agent/.claude/workspace/config-rules", "mode": "ro"},
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

        # SessionEnd 钩子需要正确的容器名，Docker 默认 HOSTNAME 是容器 ID
        env_vars["HOSTNAME"] = container_name

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
            mem_limit="16g",
            memswap_limit="16g",
            shm_size="8g",
            device_requests=[docker.types.DeviceRequest(count=-1, capabilities=[["gpu"]])],
        )

        if not body.get("skip_initial_message"):
            # 创建容器后发送初始消息
            import time
            time.sleep(3)
            user_msg = (body.get("message") or "").strip()
            msg_file = "/tmp/send_msg.sh"
            if agent_type in ("claude", "ollama"):
                agent_states[container_name] = "thinking"  # 标记思考中
                default_msg = (TOOL_INITIAL_MESSAGE if tool else INITIAL_MESSAGE).format(agent="claude")
                log_path = "/home/agent/.claude/workspace/project/logs/agent_tui.log"
                msg_to_send = user_msg or default_msg
                escaped_msg = msg_to_send.replace("'", "'\"'\"'")
                msg_b64 = __import__('base64').b64encode(msg_to_send.encode('utf-8')).decode('ascii')
                script = f"CLAUDE_MSG='{msg_b64}' node /home/agent/.claude/workspace/project/run_claude.js >> '{log_path}' 2>&1"
            else:
                default_msg = (TOOL_INITIAL_MESSAGE if tool else INITIAL_MESSAGE).format(agent="openclaw")
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
            f"{host_config_root}/rules": {"bind": "/home/agent/.claude/workspace/config-rules", "mode": "ro"},
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

    def fork_agent(container_name, fork_name=None):
        import shutil, traceback
        debug_log = "/logs/hermit/debug.log"
        with open(debug_log, "a", encoding="utf-8") as f:
            f.write(f"\n=== FORK START: {container_name} ===\n")
        
        container = docker_client_or_default().containers.get(container_name)
        labels = ((getattr(container, "attrs", {}) or {}).get("Config", {}) or {}).get("Labels", {}) or (getattr(container, "labels", {}) or {})
        agent_type = labels.get("hermit.agent_type") or ""
        
        with open(debug_log, "a", encoding="utf-8") as f:
            f.write(f"agent_type: {agent_type}\n")
        
        if agent_type not in AGENT_SPECS:
            raise ValueError(f"Unsupported agent type: {agent_type}")

        new_host_port = find_next_port()
        # 用户自定义名称优先，否则从源容器名派生
        if fork_name and fork_name.strip():
            base_name = _safe_name_part(fork_name.strip())
        else:
            base_name = derive_agent_basename(container_name)
        new_container_name = f"{new_host_port}-{base_name}"

        src_workspace = f"/workspaces/{container_name}"
        dst_workspace = f"/workspaces/{new_container_name}"
        dst_logs = f"/logs/{new_container_name}"

        with open(debug_log, "a", encoding="utf-8") as f:
            f.write(f"src_workspace: {src_workspace}\n")
            f.write(f"dst_workspace: {dst_workspace}\n")

        try:
            with open(debug_log, "a", encoding="utf-8") as f:
                f.write("Step 1: _copy_workspace_tree\n")
            _copy_workspace_tree(src_workspace, dst_workspace)
            
            with open(debug_log, "a", encoding="utf-8") as f:
                f.write("Step 2: makedirs dst_logs\n")
            os.makedirs(dst_logs, exist_ok=True)
            try:
                os.chown(dst_logs, 501, 20)
            except Exception:
                pass

            with open(debug_log, "a", encoding="utf-8") as f:
                f.write("Step 3: create_agent\n")
            body = {"message": ""}  # 不跳过初始消息
            payload = create_agent(agent_type, base_name, body=body)
            
            with open(debug_log, "a", encoding="utf-8") as f:
                f.write(f"created payload: {payload}\n")
            
            created_name = payload["container_name"]
            if created_name != new_container_name:
                created_container = docker_client_or_default().containers.get(created_name)
                created_container.remove(force=True)
                raise RuntimeError(f"Fork expected {new_container_name}, got {created_name}")

            with open(debug_log, "a", encoding="utf-8") as f:
                f.write("Step 4: add_frpc_rule\n")
            add_frpc_rule(payload["host_port"])
            
            with open(debug_log, "a", encoding="utf-8") as f:
                f.write("Step 5: sleep 5\n")
            project_path = project_path_for_agent_type(agent_type)
            import time
            time.sleep(5)
            
            with open(debug_log, "a", encoding="utf-8") as f:
                f.write("Step 6: scp_rules_to_container\n")
            scp_rules_to_container(payload["container_name"], project_path)
            
            with open(debug_log, "a", encoding="utf-8") as f:
                f.write(f"FORK SUCCESS: {payload}\n")
            return payload
        except FileExistsError as e:
            with open(debug_log, "a", encoding="utf-8") as f:
                f.write(f"FORK ERROR: {str(e)}\n")
            raise ValueError(str(e))
        except Exception as e:
            with open(debug_log, "a", encoding="utf-8") as f:
                f.write(f"FORK ERROR: {str(e)}\n")
                f.write(traceback.format_exc())
            shutil.rmtree(dst_workspace, ignore_errors=True)
            shutil.rmtree(dst_logs, ignore_errors=True)
            raise

    def fork_tool_agent(container_name, fork_name=None):
        # FORK为工具：与 fork 相同流程，但端口从 TOOL_START_PORT(18000) 注册，
        # 且 create_agent(tool=True) 发送专属初始提示词（部署后到 18081 注册 doc）
        import shutil, traceback
        debug_log = "/logs/hermit/debug.log"
        with open(debug_log, "a", encoding="utf-8") as f:
            f.write(f"\n=== FORK_TOOL START: {container_name} ===\n")

        container = docker_client_or_default().containers.get(container_name)
        labels = ((getattr(container, "attrs", {}) or {}).get("Config", {}) or {}).get("Labels", {}) or (getattr(container, "labels", {}) or {})
        agent_type = labels.get("hermit.agent_type") or ""
        with open(debug_log, "a", encoding="utf-8") as f:
            f.write(f"agent_type: {agent_type}\n")
        if agent_type not in AGENT_SPECS:
            raise ValueError(f"Unsupported agent type: {agent_type}")

        new_host_port = find_tool_port()
        if fork_name and fork_name.strip():
            base_name = _safe_name_part(fork_name.strip())
        else:
            base_name = derive_agent_basename(container_name)
        new_container_name = f"{new_host_port}-{base_name}"

        src_workspace = f"/workspaces/{container_name}"
        dst_workspace = f"/workspaces/{new_container_name}"
        dst_logs = f"/logs/{new_container_name}"

        with open(debug_log, "a", encoding="utf-8") as f:
            f.write(f"new_host_port: {new_host_port}\n")
            f.write(f"new_container_name: {new_container_name}\n")

        try:
            with open(debug_log, "a", encoding="utf-8") as f:
                f.write("Step 1: _copy_workspace_tree\n")
            _copy_workspace_tree(src_workspace, dst_workspace)

            with open(debug_log, "a", encoding="utf-8") as f:
                f.write("Step 2: makedirs dst_logs\n")
            os.makedirs(dst_logs, exist_ok=True)
            try:
                os.chown(dst_logs, 501, 20)
            except Exception:
                pass

            with open(debug_log, "a", encoding="utf-8") as f:
                f.write("Step 3: create_agent (tool=True)\n")
            body = {"message": ""}  # 不跳过初始消息，发送 TOOL_INITIAL_MESSAGE
            payload = create_agent(agent_type, base_name, body=body, tool=True)

            with open(debug_log, "a", encoding="utf-8") as f:
                f.write(f"created payload: {payload}\n")
            created_name = payload["container_name"]
            if created_name != new_container_name:
                created_container = docker_client_or_default().containers.get(created_name)
                created_container.remove(force=True)
                raise RuntimeError(f"Fork tool expected {new_container_name}, got {created_name}")

            with open(debug_log, "a", encoding="utf-8") as f:
                f.write("Step 4: add_frpc_rule\n")
            add_frpc_rule(payload["host_port"])

            with open(debug_log, "a", encoding="utf-8") as f:
                f.write("Step 5: sleep 5\n")
            project_path = project_path_for_agent_type(agent_type)
            import time
            time.sleep(5)

            with open(debug_log, "a", encoding="utf-8") as f:
                f.write("Step 6: scp_rules_to_container\n")
            scp_rules_to_container(payload["container_name"], project_path)

            with open(debug_log, "a", encoding="utf-8") as f:
                f.write(f"FORK_TOOL SUCCESS: {payload}\n")
            return payload
        except FileExistsError as e:
            with open(debug_log, "a", encoding="utf-8") as f:
                f.write(f"FORK_TOOL ERROR: {str(e)}\n")
            raise ValueError(str(e))
        except Exception as e:
            with open(debug_log, "a", encoding="utf-8") as f:
                f.write(f"FORK_TOOL ERROR: {str(e)}\n")
                f.write(traceback.format_exc())
            shutil.rmtree(dst_workspace, ignore_errors=True)
            shutil.rmtree(dst_logs, ignore_errors=True)
            raise

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
            "state": agent_states.get(container.name, "idle"),
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
            img_base64 = data.get("img")  # 可选，图片base64编码
            if not user_message:
                return jsonify({"error": "message is required"})
            system_prompt = "我问个问题，不需要改任何代码或者文件，参考文档在 config/ 和 control/ 目录（Use Skill: user-rules）里面"
            full_message = f"{system_prompt}\n\n{user_message}"
            log_file = "/logs/hermit/debug.log"
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
                f.write(f"Image present: {'Yes' if img_base64 else 'No'}\n")

            # 如果有图片，保存到临时文件并在消息中引用
            img_path = None
            if img_base64:
                img_path = tempfile.mktemp(suffix=".png", dir="/home/agent/.claude/workspace/project")
                try:
                    img_data = img_base64
                    if ',' in img_data:
                        img_data = img_data.split(',')[1]
                    with open(img_path, "wb") as f:
                        f.write(base64.b64decode(img_data))
                    # 在消息中引用图片
                    with open(tmp_file, "a", encoding="utf-8") as f:
                        f.write(f"\n\n[图片参考: {img_path}]\n")
                except Exception as e:
                    with open(log_file, "a", encoding="utf-8") as f:
                        f.write(f"Image save error: {str(e)}\n")

            # hermit 控制面板只做问答，-p 模式不需要权限参数，root 下正常运行
            result = subprocess.run(
                ["claude", "-p", tmp_file, "--add-dir", "/config"],
                capture_output=True, text=True, timeout=3600,
                env=env
            )
            os.unlink(tmp_file)
            if img_path and os.path.exists(img_path):
                os.unlink(img_path)
            output = result.stdout
            stderr = result.stderr
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"Return code: {result.returncode}\n")
                f.write(f"STDOUT:\n{output}\n")
                f.write(f"STDERR:\n{stderr}\n")
            return jsonify({"response": output or "(无输出)"})
        except subprocess.TimeoutExpired:
            return jsonify({"error": "请求超时（10分钟）"})
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
            
            if agent_type in ("claude", "ollama"):
                agent_states[name] = "thinking"  # 标记思考中（send-message）
                default_msg = INITIAL_MESSAGE.format(agent="claude")
                msg_to_send = message or default_msg
                msg_b64 = __import__('base64').b64encode(msg_to_send.encode('utf-8')).decode('ascii')
                script = f"CLAUDE_PERMISSION_MODE=bypassPermissions CLAUDE_MSG='{msg_b64}' node /home/agent/.claude/workspace/project/run_claude.js"
                try:
                    container.exec_run(["/bin/sh", "-c", f"echo '{script}' > /tmp/send_msg.sh && chmod +x /tmp/send_msg.sh"], user=AGENT_RUNTIME_USER)
                    container.exec_run(["/bin/sh", "-lc", f"nohup /tmp/send_msg.sh >> /home/agent/.claude/workspace/project/logs/agent_tui.log 2>&1 &"], user=AGENT_RUNTIME_USER, detach=True)
                except Exception as e:
                    return jsonify({"error": str(e)}), 500
                return jsonify({"ok": True, "container_name": name, "message": message, "agent_type": agent_type, "sent_at": now_iso()})
            else:
                msg_file = "/tmp/send_msg.sh"
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
                cmd = "rm -f ~/.claude/projects/*/*.jsonl ~/.claude/workspace/project/logs/*.log 2>/dev/null; echo done"
            else:
                cmd = "rm -f ~/.openclaw/projects/*/*.jsonl ~/.openclaw/workspace/project/logs/*.log 2>/dev/null; echo done"
            result = container.exec_run(["/bin/sh", "-lc", cmd], user=AGENT_RUNTIME_USER)
            output = result.output.decode("utf-8", errors="replace").strip()
            return jsonify({"ok": True, "container_name": name, "output": output})
        except PermissionError as e:
            return jsonify({"error": str(e)}), 403
        except docker.errors.NotFound:
            return jsonify({"error": "Container not found"}), 404
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.post("/api/agents/<path:name>/session-end")
    def api_session_end(name):
        """SessionEnd 钩子回调：标记容器回答完毕（红色+闪烁）"""
        agent_states[name] = "done"
        return jsonify({"ok": True})

    @app.post("/api/agents/<path:name>/reset-state")
    def api_reset_state(name):
        """重置容器卡片状态为空闲（绿色）"""
        agent_states[name] = "idle"
        return jsonify({"ok": True})

    @app.post("/api/agents/<path:name>/notify-session-end")
    def api_notify_session_end(name):
        """SessionEnd 邮件通知：生成摘要+UUID，发送邮件，建立追踪"""
        try:
            container = _require_managed(name)
        except Exception:
            return jsonify({"ok": False, "error": "Container not found"}), 404
        try:
            agent_type = ((getattr(container, "labels", {}) or {}).get("hermit.agent_type") or "")
            log_path = log_path_for_agent_type(agent_type)
            result = container.exec_run(
                ["/bin/sh", "-lc", f"tail -c 4000 '{log_path}' 2>/dev/null"], user=AGENT_RUNTIME_USER)
            log_tail = (result.output or b"").decode("utf-8", errors="replace") if isinstance(result.output, bytes) else str(result.output)
        except Exception:
            log_tail = ""

        # 提取最后一段摘要（取最后200字符作为简述）
        summary = log_tail.strip()
        if len(summary) > 200:
            summary = summary[-200:]
        # 取最后一行非空内容作为简述，不超过100字
        lines = [l.strip() for l in summary.splitlines() if l.strip()]
        brief = lines[-1] if lines else "任务完成"
        if len(brief) > 100:
            brief = brief[:97] + "..."

        track_uuid = str(uuid.uuid4())[:8]
        subject = f"[Hermit] {name} #{track_uuid}"
        body = f"容器: {name}\nUUID: {track_uuid}\n摘要: {brief}\n\n---\n此邮件由 Hermit SessionEnd 钩子自动发送。"

        ok, msg = _send_email_via_service(subject, body)

        # 存储追踪信息
        if ok:
            tracks = _load_email_tracks()
            now = datetime.now(timezone.utc).isoformat()
            ttl = (datetime.now(timezone.utc) + timedelta(hours=36)).isoformat()
            tracks[track_uuid] = {
                "container_name": name,
                "sent_at": now,
                "ttl": ttl,
                "subject_prefix": f"[Hermit] {name} #{track_uuid}",
                "reply_chain": [],
                "last_checked": now,
            }
            _save_email_tracks(tracks)

        return jsonify({"ok": ok, "uuid": track_uuid, "message": msg})

    @app.post("/api/agents/<path:name>/switch-model")
    def api_switch_model(name):
        """切换容器模型：写入选定模板的 settings.json 和 config.json，保留 hooks，重启容器"""
        data = request.get_json(silent=True) or {}
        profile = (data.get("profile") or "").strip()
        if not profile:
            return jsonify({"error": "Missing profile name"}), 400
        try:
            container = _require_managed(name)
        except Exception:
            return jsonify({"error": "Container not found"}), 404

        config_dir = os.path.join(app.config.get("CONFIG_ROOT", "/config"), "claude")
        settings_variant = os.path.join(config_dir, f"settings.json.{profile}")
        config_variant = os.path.join(config_dir, f"config.json.{profile}")

        if not os.path.isfile(settings_variant) or not os.path.isfile(config_variant):
            return jsonify({"error": f"Profile '{profile}' variants not found"}), 404

        try:
            with open(settings_variant, "r", encoding="utf-8") as f:
                settings_content = f.read()
            with open(config_variant, "r", encoding="utf-8") as f:
                config_content = f.read()
        except OSError as e:
            return jsonify({"error": str(e)}), 500

        # 替换 hooks 中的 $HOSTNAME 为实际容器名
        settings_content = settings_content.replace("$HOSTNAME", name)

        # 写入容器
        def _write_via_exec(dst_path, content):
            encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
            ec = container.exec_run(
                ["/bin/sh", "-lc", f"echo '{encoded}' | base64 -d > '{dst_path}'"],
                user=AGENT_RUNTIME_USER)
            return ec.exit_code == 0

        if not _write_via_exec("/home/agent/.claude/settings.json", settings_content):
            return jsonify({"error": "Failed to write settings.json"}), 500
        if not _write_via_exec("/home/agent/.claude/config.json", config_content):
            return jsonify({"error": "Failed to write config.json"}), 500

        # 重启容器使配置生效
        try:
            container.restart()
        except Exception as e:
            return jsonify({"ok": True, "profile": profile, "warning": f"Files written but restart failed: {e}"})

        return jsonify({"ok": True, "profile": profile, "restarted": True})

    @app.get("/api/agents/<path:name>/current-model")
    def api_current_model(name):
        """读取容器内 settings.json 的 ANTHROPIC_BASE_URL，判断当前激活的模型"""
        try:
            container = _require_managed(name)
        except Exception:
            return jsonify({"error": "Container not found"}), 404
        try:
            result = container.exec_run(
                ["/bin/sh", "-lc", "cat /home/agent/.claude/settings.json 2>/dev/null"],
                user=AGENT_RUNTIME_USER)
            content = (result.output or b"").decode("utf-8", errors="replace") if isinstance(result.output, bytes) else str(result.output)
            settings = json.loads(content)
            base_url = settings.get("env", {}).get("ANTHROPIC_BASE_URL", "")
        except Exception:
            return jsonify({"model": "unknown", "base_url": ""})

        # 通过 ANTHROPIC_BASE_URL 匹配已知模型
        model_map = {
            "api.deepseek.com": "deepseek",
            "api.minimaxi.com": "minimax",
        }
        model = "unknown"
        for domain, name in model_map.items():
            if domain in base_url:
                model = name
                break
        return jsonify({"model": model, "base_url": base_url})

    def _check_email_replies():
        """检查所有追踪邮件是否被回复，更新 TTL"""
        tracks = _load_email_tracks()
        if not tracks:
            return
        now = datetime.now(timezone.utc)
        today_str = now.strftime("%Y-%m-%d")
        changed = False

        # 拉取最近 2 天的邮件
        emails = _fetch_recent_emails(days=2)

        for tid, track in list(tracks.items()):
            ttl_dt = datetime.fromisoformat(track["ttl"])
            sent_dt = datetime.fromisoformat(track["sent_at"])
            sent_day = sent_dt.strftime("%Y-%m-%d")

            # TTL 过期 → 停止监控
            if now > ttl_dt:
                del tracks[tid]
                changed = True
                continue

            # 当天未回复 → 停止监控（仅限发送当天）
            if sent_day == today_str and now.hour >= 23:
                # 当天还没结束不急着判死，等 TTL 自然过期
                pass

            # 搜索回复：匹配 subject 中包含 UUID 前缀的邮件
            prefix = track.get("subject_prefix", "")
            for em in emails:
                subj = em.get("subject", "")
                body = em.get("body", "")
                sender = em.get("sender", "")
                # 回复的特征：subject 包含 UUID（或原 subject），发件人是主人
                if sender != EMAIL_OWNER:
                    continue
                # 检查是否包含 AI 标识，如果有则跳过（不带 ai 标识的主人回复才计入）
                ai_markers = ["[AI]", "[ai]", "ai-generated", "ai回复", "AI回复"]
                has_ai = any(m.lower() in subj.lower() or m.lower() in body.lower()[:200] for m in ai_markers)
                if has_ai:
                    continue
                # 匹配：邮件主题包含 uuid 或原始 subject_prefix
                matched = False
                if tid in subj or tid in body[:500]:
                    matched = True
                elif prefix and prefix in subj:
                    matched = True

                if matched:
                    reply_id = em.get("id", "")
                    chain = track.get("reply_chain", [])
                    if reply_id and reply_id not in chain:
                        chain.append(reply_id)
                        track["reply_chain"] = chain
                        # 刷新 TTL
                        track["ttl"] = (now + timedelta(hours=36)).isoformat()
                        changed = True

            track["last_checked"] = now.isoformat()
            tracks[tid] = track

        if changed:
            _save_email_tracks(tracks)

    def _email_monitor_loop():
        """后台线程：定期检查邮件回复"""
        while True:
            time.sleep(EMAIL_CHECK_INTERVAL)
            try:
                _check_email_replies()
            except Exception:
                pass

    @app.get("/api/email/tracks")
    def api_email_tracks():
        """查看当前所有邮件追踪记录"""
        return jsonify(_load_email_tracks())

    @app.post("/api/email/check-now")
    def api_email_check_now():
        """手动触发邮件回复检查"""
        _check_email_replies()
        return jsonify({"ok": True})

    @app.get("/api/config/profiles")
    def api_config_profiles():
        """扫描 config/claude/ 下 config.json.[xxx] / settings.json.[xxx] 变体文件"""
        # 优先用容器内路径 /config，否则用 HOST_CONFIG_ROOT
        config_root = app.config.get("CONFIG_ROOT", "/config")
        config_dir = os.path.join(config_root, "claude")
        # 正则匹配 config.json.<xxx> 和 settings.json.<xxx>，提取 <xxx> 后缀
        pattern = re.compile(r"^(?:config|settings)\.json\.(.+)$")
        profiles = set()
        try:
            for f in os.listdir(config_dir):
                m = pattern.match(f)
                if m:
                    profiles.add(m.group(1))
        except OSError:
            pass
        # 检测当前激活的是哪个变体（对比 config.json 和 config.json.xxx 内容是否一致）
        active = "unknown"
        config_path = os.path.join(config_dir, "config.json")
        if os.path.isfile(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    current_content = f.read()
                for p in profiles:
                    variant_path = os.path.join(config_dir, f"config.json.{p}")
                    if os.path.isfile(variant_path):
                        with open(variant_path, "r", encoding="utf-8") as f:
                            if f.read() == current_content:
                                active = p
                                break
            except OSError:
                pass
        return jsonify({"profiles": sorted(profiles), "active": active})

    @app.post("/api/config/switch-profile")
    def api_config_switch_profile():
        """将 config.json.<profile> 和 settings.json.<profile> 复制替换到原文件"""
        data = request.get_json(silent=True) or {}
        profile = (data.get("profile") or "").strip()
        if not profile:
            return jsonify({"error": "Missing profile name"}), 400
        config_root = app.config.get("CONFIG_ROOT", "/config")
        config_dir = os.path.join(config_root, "claude")
        files = [
            ("config.json", f"config.json.{profile}"),
            ("settings.json", f"settings.json.{profile}"),
        ]
        for target, source in files:
            src = os.path.join(config_dir, source)
            dst = os.path.join(config_dir, target)
            if not os.path.isfile(src):
                return jsonify({"error": f"Source not found: {source}"}), 404
            try:
                with open(src, "r", encoding="utf-8") as f:
                    content = f.read()
                with open(dst, "w", encoding="utf-8") as f:
                    f.write(content)
            except OSError as e:
                return jsonify({"error": f"Failed to write {target}: {e}"}), 500
        return jsonify({"ok": True, "profile": profile})

    @app.get("/api/agents/<path:name>/git-commits")
    def api_git_commits(name):
        try:
            container = _require_managed(name)
            labels = ((container.attrs or {}).get("Config", {}) or {}).get("Labels", {}) or {}
            agent_type = labels.get("hermit.agent_type", "")
            project_path = project_path_for_agent_type(agent_type)
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
            
            commits = [{
                "hash": "__FORK__",
                "message": "****FORK****",
                "is_current": "",
            }, {
                "hash": "__FORK_TOOL__",
                "message": "******FORK为工具******",
                "is_current": "",
            }]
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
            hard_reset = bool(data.get("hard"))
            if not commit_hash:
                return jsonify({"error": "commit_hash is required"}), 400
            labels = ((container.attrs or {}).get("Config", {}) or {}).get("Labels", {}) or {}
            agent_type = labels.get("hermit.agent_type", "")
            project_path = project_path_for_agent_type(agent_type)

            if commit_hash == "__FORK__":
                try:
                    fork_name = data.get("fork_name") or None
                    payload = fork_agent(name, fork_name=fork_name)
                except ValueError as e:
                    return jsonify({"error": str(e)}), 400
                return jsonify({
                    "ok": True,
                    "mode": "fork",
                    "container_name": name,
                    "new_container": payload["container_name"],
                    "host_port": payload["host_port"],
                })

            if commit_hash == "__FORK_TOOL__":
                try:
                    fork_name = data.get("fork_name") or None
                    payload = fork_tool_agent(name, fork_name=fork_name)
                except ValueError as e:
                    return jsonify({"error": str(e)}), 400
                return jsonify({
                    "ok": True,
                    "mode": "fork_tool",
                    "container_name": name,
                    "new_container": payload["container_name"],
                    "host_port": payload["host_port"],
                })

            if not COMMIT_HASH_PATTERN.fullmatch(commit_hash):
                return jsonify({"error": "invalid commit hash"}), 400

            git_action = "reset --hard" if hard_reset else "checkout"
            cmd = f"cd {project_path} && git -c safe.directory=* {git_action} {commit_hash} 2>&1 && sleep 5"
            result = container.exec_run(["/bin/sh", "-lc", cmd], user=AGENT_RUNTIME_USER)
            output = result.output.decode("utf-8", errors="replace").strip()
            if result.exit_code != 0:
                return jsonify({"error": output or f"git {git_action} failed"}), 400
            payload = recreate_agent(name)
            add_frpc_rule(payload["host_port"])
            scp_rules_to_container(payload["container_name"], project_path)
            return jsonify({
                "ok": True,
                "mode": "hard_reset" if hard_reset else "checkout",
                "container_name": name,
                "commit_hash": commit_hash,
                "git_output": output,
                "new_container": payload["container_name"],
            })
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
            import time
            time.sleep(8)
            if agent_type in ("claude", "ollama"):
                scp_rules_to_container(payload["container_name"], "/home/agent/.claude/workspace/project")
                project_path = "/home/agent/.claude/workspace/project"
            else:
                scp_rules_to_container(payload["container_name"], "/home/agent/.openclaw/workspace/project")
                project_path = "/home/agent/.openclaw/workspace/project"
            default_msg = INITIAL_MESSAGE.format(agent="claude" if agent_type in ("claude", "ollama") else "openclaw")
            msg_b64 = __import__('base64').b64encode(default_msg.encode('utf-8')).decode('ascii')
            msg_file = "/tmp/send_msg.sh"
            if agent_type in ("claude", "ollama"):
                script = f"CLAUDE_MSG='{msg_b64}' node {project_path}/run_claude.js >> '{project_path}/logs/agent_tui.log' 2>&1"
            else:
                script = f"echo '{msg_b64}' | base64 -d | openclaw agent --session-id main -m \"$(cat)\" >> '{project_path}/logs/agent_tui.log' 2>&1"
            try:
                container_new = docker_client_or_default().containers.get(payload["container_name"])
                container_new.exec_run(["/bin/sh", "-c", f"echo '{script}' > {msg_file} && chmod +x {msg_file}"], user=AGENT_RUNTIME_USER)
                container_new.exec_run(["/bin/sh", "-lc", f"nohup {msg_file} >> '{project_path}/logs/agent_tui.log' 2>&1 &"], user=AGENT_RUNTIME_USER, detach=True)
            except Exception as e:
                print(f"[recreate] send initial message failed: {e}", flush=True, file=sys.stderr)
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
        display: flex;
        flex-direction: column;
        gap: 14px;
      }}
      .card {{
        border: 1px solid rgba(255,255,255,0.13);
        border-radius: 14px;
        overflow: hidden;
        background: linear-gradient(180deg, rgba(255,255,255,0.08), rgba(255,255,255,0.03));
        box-shadow: var(--shadow);
        transition: border-color 0.2s, box-shadow 0.2s;
      }}
      .card:focus-within,
      .card.tab-selected {{
        border-color: #3AE374;
        box-shadow: 0 0 0 2px rgba(58, 227, 116, 0.3), var(--shadow);
        outline: none;
      }}
      @keyframes card-blink {{
        0%, 100% {{ border-color: rgba(255,255,255,0.13); box-shadow: var(--shadow); }}
        50% {{ border-color: #FF6B6B; box-shadow: 0 0 16px rgba(255,107,107,0.6), var(--shadow); }}
      }}
      .card.blink-card {{
        animation: card-blink 1.2s ease-in-out infinite;
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
      .status-light {{
        display: inline-block;
        width: 10px;
        height: 10px;
        border-radius: 50%;
        margin-left: 6px;
        cursor: pointer;
        transition: background 0.3s, box-shadow 0.3s;
        vertical-align: middle;
        flex-shrink: 0;
      }}
      .status-light.idle {{ background: #3AE374; box-shadow: 0 0 6px rgba(58,227,116,0.6); }}
      .status-light.thinking {{ background: #FFD700; box-shadow: 0 0 8px rgba(255,215,0,0.7); animation: pulse-thinking 0.8s ease-in-out infinite; }}
      .status-light.done {{ background: #FF6B6B; box-shadow: 0 0 10px rgba(255,107,107,0.7); }}
      @keyframes pulse-thinking {{
        0%, 100% {{ opacity: 1; }}
        50% {{ opacity: 0.4; }}
      }}
      .meta {{ color: var(--muted); font-size: 11px; }}
      .profile-popup {{
        position: fixed;
        z-index: 9999;
        background: #1a1a2e;
        border: 1px solid rgba(255,255,255,0.2);
        border-radius: 8px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.6);
        min-width: 160px;
        overflow: hidden;
      }}
      .profile-popup div {{
        padding: 8px 14px;
        font-size: 12px;
        cursor: pointer;
        color: #ccc;
        border-bottom: 1px solid rgba(255,255,255,0.08);
      }}
      .profile-popup div:hover {{ background: rgba(58,227,116,0.15); color: #fff; }}
      .profile-popup div.active {{ color: #3AE374; font-weight: 600; }}
      .git-tools {{
        display: none;
        align-items: center;
        gap: 6px;
        flex-wrap: wrap;
        margin-left: 0;
      }}
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
          <h1 id="hermitLogo" style="margin:0;cursor:pointer;user-select:none;" title="点击切换配置模板">HERMIT</h1>
          <span style="flex:1;"></span>
          <div style="display:flex;align-items:center;gap:8px;">
            <input id="claudeQuery" placeholder="问个问题..." style="padding:6px 12px;background:rgba(255,255,255,0.1);border:1px solid rgba(255,255,255,0.2);border-radius:4px;color:#fff;width:150px;" />
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
        const titleSpan = document.createElement("span");
        titleSpan.style.cssText = "font-size:18px;font-weight:bold;color:#fff;";
        titleSpan.textContent = title;
        const copyBtn = document.createElement("button");
        copyBtn.style.cssText = "padding:6px 12px;background:#3AE374;color:#000;border:none;border-radius:4px;cursor:pointer;font-weight:600;font-size:12px;";
        copyBtn.textContent = "复制";
        copyBtn.onclick = () => {{
          navigator.clipboard.writeText(content).then(() => {{
            copyBtn.textContent = "已复制!";
            copyBtn.style.background = "#666";
            setTimeout(() => {{ copyBtn.textContent = "复制"; copyBtn.style.background = "#3AE374"; }}, 1500);
          }});
        }};
        header.appendChild(titleSpan);
        header.appendChild(copyBtn);
        const contentDiv = document.createElement("div");
        contentDiv.style.cssText = "flex:1;overflow:auto;padding:16px;background:#0d0d1a;border-radius:8px;border:1px solid rgba(255,255,255,0.1);white-space:pre-wrap;word-break:break-word;max-height:60vh;font-size:13px;line-height:1.5;color:#e0e0e0;";
        contentDiv.textContent = content;
        box.appendChild(header);
        box.appendChild(contentDiv);
        overlay.appendChild(box);
        document.body.appendChild(overlay);
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

      let profileData = {{ profiles: [], active: "" }};

      function showProfilePopup() {{
        // 移除已有 popup
        const old = document.querySelector(".profile-popup");
        if (old) {{ old.remove(); return; }}

        const h1 = document.getElementById("hermitLogo");
        const rect = h1.getBoundingClientRect();
        const popup = document.createElement("div");
        popup.className = "profile-popup";
        popup.style.top = (rect.bottom + 4) + "px";
        popup.style.left = rect.left + "px";

        if (profileData.profiles.length === 0) {{
          const d = document.createElement("div");
          d.textContent = "无配置模板";
          d.style.cursor = "default";
          d.onclick = (e) => e.stopPropagation();
          popup.appendChild(d);
        }} else {{
          for (const p of profileData.profiles) {{
            const d = document.createElement("div");
            d.textContent = p + (p === profileData.active ? " [当前]" : "");
            if (p === profileData.active) d.className = "active";
            d.onclick = async (e) => {{
              e.stopPropagation();
              popup.remove();
              if (p === profileData.active) return;
              const confirmed = confirm(`切换配置文件为 "${{p}}"，将替换 config.json 和 settings.json，确定？`);
              if (!confirmed) return;
              try {{
                const res = await fetch("/api/config/switch-profile", {{
                  method: "POST",
                  headers: {{ "Content-Type": "application/json" }},
                  body: JSON.stringify({{ profile: p }})
                }});
                const data = await res.json();
                if (data.ok) {{ location.reload(); }}
                else {{ alert("切换失败: " + (data.error || "未知错误")); }}
              }} catch(err) {{ alert("请求失败: " + err.message); }}
            }};
            popup.appendChild(d);
          }}
        }}

        document.body.appendChild(popup);

        // 点击其他地方关闭
        const close = (e) => {{
          if (!popup.contains(e.target) && e.target !== h1) {{
            popup.remove();
            document.removeEventListener("click", close);
          }}
        }};
        setTimeout(() => document.addEventListener("click", close), 0);
      }}

      document.getElementById("hermitLogo").onclick = (e) => {{
        e.stopPropagation();
        showProfilePopup();
      }};

      function makeCard(item) {{
        const div = document.createElement("div");
        div.className = "card collapsed";
        div.dataset.name = item.container_name;
        div.setAttribute("tabindex", "-1");
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
                  <div class="git-tools">
                    <select class="git-mode-select" data-action="git-mode" style="padding:2px 4px;font-size:11px;max-width:120px;">
                      <option value="checkout">git checkout</option>
                      <option value="reset-hard">git reset --hard</option>
                    </select>
                    <select class="git-select" data-action="git-select" style="padding:2px 4px;font-size:11px;max-width:220px;">
                      <option value="">加载中...</option>
                    </select>
                  </div>
                </div>
                <div class="meta">${{item.agent_type}} · ${{item.host_port}}:{SERVICE_PORT} · SSH:${{item.ssh_port}}</div>
              </div>
            </div>
            <div class="meta ${{stCls}}" data-status="${{item.status}}" data-port="${{item.host_port}}" style="display:flex;align-items:center;gap:6px;">
              <span>${{item.status}}</span>
              <span class="status-light ${{item.state || 'idle'}}" data-action="reset-state" title="点击恢复空闲状态" style="display:inline-block;"></span>
            </div>
          </div>
          <div class="card-body">
          <div class="actions">
            <button data-action="ssh">SSH终端</button>
            <button data-action="switch-model">切换模型</button>
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
          <iframe id="ssh-${{item.container_name}}" class="ssh-view" style="display:none; width:100%; height:400px; border:1px solid #ccc;" src="" allow="fullscreen"></iframe>
          </div>
        `;
        if (item.state === 'done') {{
          div.classList.add("blink-card");
        }}
        const collapseBtn = div.querySelector('.collapse-btn');
        const cardBody = div.querySelector('.card-body');
        collapseBtn.onclick = (e) => {{
          e.stopPropagation();
          const wasCollapsed = div.classList.contains("collapsed");
          div.classList.toggle("collapsed");
          collapseBtn.textContent = div.classList.contains("collapsed") ? "▶" : "▼";
          
          // 仅在重新打开（折叠→展开）时消除闪烁、红灯→绿灯
          if (wasCollapsed) {{
            div.classList.remove("blink-card");
            const light = div.querySelector('.status-light');
            if (light) {{
              light.className = 'status-light idle';
              fetch(`/api/agents/${{encodeURIComponent(item.container_name)}}/reset-state`, {{ method: 'POST' }});
            }}
          }}
        }};
        
        // 状态灯点击：恢复空闲状态
        const statusLight = div.querySelector('.status-light');
        if (statusLight) {{
          statusLight.onclick = (e) => {{
            e.stopPropagation();
            statusLight.className = 'status-light idle';
            div.classList.remove("blink-card");
            fetch(`/api/agents/${{encodeURIComponent(item.container_name)}}/reset-state`, {{ method: 'POST' }});
          }};
        }}
        const logBox = div.querySelector("pre");
        const sshIframe = div.querySelector("iframe");
        const sshBtn = div.querySelector('button[data-action="ssh"]');
        const cmdInput = div.querySelector('[data-role="cmd-input"]');
        let sshActive = false;
        let lastEnterTime = 0;
        cmdInput.addEventListener('keydown', (e) => {{
          if (e.key === 'Enter') {{
            const now = Date.now();
            if (now - lastEnterTime < 600) {{
              e.preventDefault();
              sendMessage();
              lastEnterTime = 0;
            }} else {{
              lastEnterTime = now;
            }}
          }}
        }});
        sshBtn.onclick = () => {{
          sshActive = !sshActive;
          sshBtn.style.fontWeight = sshActive ? "bold" : "";
          sshBtn.style.background = sshActive ? "#4caf50" : "";
          console.log('SSH button clicked, active:', sshActive, 'container:', item.container_name);
          if (sshActive) {{
            const url = `/api/agents/${{encodeURIComponent(item.container_name)}}/ssh-terminal`;
            console.log('Setting iframe src to:', url);
            sshIframe.style.display = "block";
            sshIframe.style.visibility = "visible";
            sshIframe.src = url;
            logBox.style.display = "none";
          }} else {{
            sshIframe.src = "";
            sshIframe.style.display = "none";
            sshIframe.style.visibility = "hidden";
            logBox.style.display = "block";
          }}
        }};
        div.querySelector('button[data-action="refresh"]').onclick = async () => {{
          const r = await fetch(`/api/agents/${{encodeURIComponent(item.container_name)}}/logs?tail=200`, {{ cache: "no-store" }});
          const d = await r.json();
          logBox.textContent = d.logs || d.error || "";
          logBox.scrollTop = logBox.scrollHeight;
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
        div.querySelector('button[data-action="switch-model"]').onclick = async (e) => {{
          e.stopPropagation();
          const btn = e.currentTarget;
          const old = document.querySelector(".model-popup");
          if (old) {{ old.remove(); return; }}

          btn.textContent = "检测中...";
          let currentModel = "unknown";
          try {{
            const r = await fetch(`/api/agents/${{encodeURIComponent(item.container_name)}}/current-model`);
            const d = await r.json();
            currentModel = d.model || "unknown";
          }} catch(err) {{}}
          btn.textContent = "切换模型";

          const rect = btn.getBoundingClientRect();
          const popup = document.createElement("div");
          popup.className = "profile-popup model-popup";
          popup.style.top = (rect.bottom + 4) + "px";
          popup.style.left = rect.left + "px";

          const profiles = profileData.profiles || [];
          if (profiles.length === 0) {{
            const d = document.createElement("div");
            d.textContent = "无可用模型";
            d.style.cursor = "default";
            popup.appendChild(d);
          }} else {{
            for (const p of profiles) {{
              const d = document.createElement("div");
              d.textContent = p + (p === currentModel ? " [当前]" : "");
              if (p === currentModel) d.className = "active";
              d.onclick = async (e2) => {{
                e2.stopPropagation();
                popup.remove();
                if (p === currentModel) return;
                const confirmed = confirm(`切换 "${{item.container_name}}" 模型为 "${{p}}" 并重启容器，确定？`);
                if (!confirmed) return;
                logBox.textContent += `\n[切换模型 -> ${{p}}] 执行中...\n`;
                try {{
                  const r = await fetch(`/api/agents/${{encodeURIComponent(item.container_name)}}/switch-model`, {{
                    method: "POST",
                    headers: {{ "Content-Type": "application/json" }},
                    body: JSON.stringify({{ profile: p }})
                  }});
                  const data = await r.json();
                  if (data.ok) {{
                    logBox.textContent += `[完成] 已切换为 ${{p}}，容器已重启\n`;
                  }} else {{
                    logBox.textContent += `ERROR: ${{data.error || "未知错误"}}\n`;
                  }}
                }} catch(err) {{
                  logBox.textContent += `ERROR: ${{err.message}}\n`;
                }}
                await refreshCards();
              }};
              popup.appendChild(d);
            }}
          }}

          document.body.appendChild(popup);

          const close = (e2) => {{
            if (!popup.contains(e2.target) && e2.target !== btn) {{
              popup.remove();
              document.removeEventListener("click", close);
            }}
          }};
          setTimeout(() => document.addEventListener("click", close), 0);
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
        const gitTools = div.querySelector('.git-tools');
        const gitModeSelect = div.querySelector('.git-mode-select');
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
          if (gitTools.style.display === "none" || !gitTools.style.display) {{
            gitTools.style.display = "inline-flex";
            if (gitSelect.options.length <= 1) loadGitCommits();
          }} else {{
            gitTools.style.display = "none";
          }}
        }};
        
        gitSelect.onchange = async () => {{
          const hash = gitSelect.value;
          if (!hash) return;
          gitTools.style.display = "none";
          const isFork = hash === "__FORK__";
          const isForkTool = hash === "__FORK_TOOL__";
          const gitMode = gitModeSelect ? gitModeSelect.value : "checkout";
          const opLabel = isFork ? "fork" : (isForkTool ? "fork为工具" : (gitMode === "reset-hard" ? "git reset --hard" : "git checkout"));
          const targetLabel = (isFork || isForkTool) ? item.container_name : hash.substring(0,7);
          
          // Fork / Fork为工具 时弹出命名对话框
          let forkName = null;
          if (isFork || isForkTool) {{
            const defaultName = item.container_name.replace(/^\\d+-/, '');
            const input = prompt("请输入新容器名称：", defaultName);
            if (input === null || !input.trim()) {{
              gitSelect.value = "";
              return;
            }}
            forkName = input.trim();
          }}
          
          logBox.textContent += `\n[${{opLabel}} ${{targetLabel}}] 执行中...\n`;
          const body = (isFork || isForkTool) ? {{ commit_hash: hash, fork_name: forkName }} : {{ commit_hash: hash, hard: gitMode === "reset-hard" }};
          const r = await fetch(`/api/agents/${{encodeURIComponent(item.container_name)}}/git-reset`, {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify(body),
          }});
          const d = await r.json();
          if (!r.ok) {{
            logBox.textContent += `ERROR: ${{d.error || `HTTP ${{r.status}}`}}\n`;
            gitSelect.value = "";
            return;
          }}
          if (d.mode === "fork") {{
            logBox.textContent += `[fork 完成] 新容器: ${{d.new_container}}\n`;
          }} else if (d.mode === "fork_tool") {{
            logBox.textContent += `[fork为工具 完成] 新容器: ${{d.new_container}}\n`;
          }} else {{
            const doneLabel = d.mode === "hard_reset" ? "git reset --hard 完成" : "git checkout 完成";
            logBox.textContent += `[${{doneLabel}}] ${{d.git_output || ""}}\n[容器重建中] ${{d.new_container}}\n`;
          }}
          gitSelect.value = "";
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
                stDiv.querySelector('span').innerHTML = `<a href="http://dimond.top:${{port}}" target="_blank" style="color:inherit;text-decoration:underline;" onclick="event.stopPropagation()">running</a>`;
            }}
          }} else {{
            // 更新状态和状态灯
            const st = card.querySelector('.meta[data-status]') || card.querySelector('.meta.status-running, .meta.status-other');
            if (st) {{
               st.className = `meta status-${{item.status === 'running' ? 'running' : 'other'}}`;
               st.dataset.status = item.status;
               st.dataset.port = item.host_port;
               const stSpan = st.querySelector('span');
               if (stSpan) {{
                 if (item.status === 'running') {{
                   stSpan.innerHTML = `<a href="http://dimond.top:${{item.host_port}}" target="_blank" style="color:inherit;text-decoration:underline;" onclick="event.stopPropagation()">running</a>`;
                 }} else {{
                   stSpan.textContent = item.status;
                 }}
               }}
            }}
            // 仅折叠卡片更新状态灯；已展开卡片保持不变，需重新打开才变绿
            const isCollapsed = card.classList.contains("collapsed");
            if (isCollapsed) {{
              const light = card.querySelector('.status-light');
              if (light) {{
                const newState = item.state || 'idle';
                if (!light.classList.contains(newState)) {{
                  light.className = 'status-light ' + newState;
                }}
              }}
            }}
            if (item.state === 'done') {{
              card.classList.add("blink-card");
            }} else if (!isCollapsed) {{
              // 展开状态不自动移除闪烁，等重新打开时清除
            }} else {{
              card.classList.remove("blink-card");
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
        try {{
          const res = await fetch("/api/config/profiles", {{ cache: "no-store" }});
          profileData = await res.json();
        }} catch(err) {{}}
        await refreshCards();
        setInterval(refreshCards, {poll_ms});
        
        let tabIndex = 0;
        document.addEventListener('keydown', (e) => {{
          if (e.key === 'Tab') {{
            e.preventDefault();
            const cardEls = Array.from(document.querySelectorAll('.card[data-name]'));
            if (!cardEls.length) return;
            
            const nextIndex = (tabIndex + 1) % cardEls.length;
            
            cardEls.forEach((card, i) => {{
              if (i !== nextIndex) {{
                card.classList.add('collapsed');
                card.classList.remove('tab-selected');
                const btn = card.querySelector('.collapse-btn');
                if (btn) btn.textContent = '▶';
              }}
            }});
            
            tabIndex = nextIndex;
            const selected = cardEls[tabIndex];
            selected.classList.remove('collapsed');
            selected.classList.add('tab-selected');
            const btn = selected.querySelector('.collapse-btn');
            if (btn) btn.textContent = '▼';
            
            setTimeout(() => {{
              const msgInput = selected.querySelector('.cmd-input');
              if (msgInput) {{
                msgInput.focus();
                msgInput.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
              }}
            }}, 100);
          }}
        }});
        document.addEventListener('click', (e) => {{
          const card = e.target.closest('.card[data-name]');
          if (!card) return;
          const cardEls = Array.from(document.querySelectorAll('.card[data-name]'));
          const clickedIndex = cardEls.indexOf(card);
          if (clickedIndex < 0) return;
          tabIndex = clickedIndex;
          cardEls.forEach((c, i) => {{
            if (i !== clickedIndex) {{
              c.classList.add('collapsed');
              c.classList.remove('tab-selected');
              const btn = c.querySelector('.collapse-btn');
              if (btn) btn.textContent = '▶';
            }}
          }});
          card.classList.remove('collapsed');
          card.classList.add('tab-selected');
          const btn = card.querySelector('.collapse-btn');
          if (btn) btn.textContent = '▼';
        }});
      }})();
    </script>
  </body>
</html>"""
        return make_response(html)

    # 启动邮件回复监控后台线程
    monitor_thread = threading.Thread(target=_email_monitor_loop, daemon=True)
    monitor_thread.start()

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
