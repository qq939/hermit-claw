import io
import os
import unittest
from unittest.mock import patch

from control.app import create_app


class FakeExecResult:
    def __init__(self, exit_code=0, output=b"ok\n"):
        self.exit_code = exit_code
        self.output = output


class FakeContainer:
    def __init__(self, name, status="running", port=None, labels=None, logs_text=""):
        self.name = name
        self.status = status
        self.labels = labels or {}
        self.attrs = {
            "HostConfig": {"PortBindings": {"8082/tcp": [{"HostPort": str(port)}]} if port else {}},
            "Config": {"Labels": self.labels},
        }
        self._logs_text = logs_text
        self._last_exec = None
        self._last_exec_kwargs = None

    def logs(self, tail=20, stdout=True, stderr=True):
        lines = self._logs_text.splitlines()[-tail:]
        return ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")

    def exec_run(self, cmd, **kwargs):
        self._last_exec = cmd
        self._last_exec_kwargs = kwargs
        if isinstance(cmd, list) and len(cmd) > 2:
            log_cmd = cmd[2]
            if "tail" in log_cmd and "agent_tui.log" in log_cmd:
                import re
                match = re.search(r"tail -(\d+)", log_cmd)
                if match:
                    tail_n = int(match.group(1))
                    lines = self._logs_text.splitlines()[-tail_n:]
                    return FakeExecResult(output=("\n".join(lines) + ("\n" if lines else "")).encode("utf-8"))
        return FakeExecResult(exit_code=0, output=b"done\n")

    def remove(self, force=False):
        self._removed = True


class FakeContainers:
    def __init__(self):
        self._items = []
        self.last_run_kwargs = None

    def list(self, all=True):
        return list(self._items)

    def run(self, image, name, detach, tty, stdin_open, labels, ports, volumes, restart_policy, log_config, user=None, environment=None, network=None):
        self.last_run_kwargs = {
            "image": image,
            "name": name,
            "detach": detach,
            "tty": tty,
            "stdin_open": stdin_open,
            "labels": labels,
            "ports": ports,
            "volumes": volumes,
            "restart_policy": restart_policy,
            "log_config": log_config,
            "user": user,
            "network": network,
        }
        host_port = int(ports["8082/tcp"])
        c = FakeContainer(
            name=name,
            status="running",
            port=host_port,
            labels=labels,
            logs_text=f"{name} started\nready\nboot",
        )
        self._items.append(c)
        return c

    def get(self, name):
        for item in self._items:
            if item.name == name:
                return item
        raise KeyError(name)


class FakeDockerClient:
    def __init__(self):
        self.containers = FakeContainers()


class ControlApiTests(unittest.TestCase):
    def setUp(self):
        self.fake_docker = FakeDockerClient()
        self.fake_docker.containers._items.append(
            FakeContainer(
                name="18081-demo",
                port=18081,
                labels={"hermit.managed": "true", "hermit.agent_type": "claude"},
                logs_text="boot\nready",
            )
        )
        self.env_patcher = patch.dict(os.environ, {
            "HOST_CONFIG_ROOT": "/tmp/test_config",
            "HOST_WORKSPACES_ROOT": "/tmp/test_workspaces",
            "HOST_LOGS_ROOT": "/tmp/test_logs",
        })
        self.env_patcher.start()
        app = create_app(self.fake_docker)
        app.config["TESTING"] = True
        self.client = app.test_client()

    def tearDown(self):
        self.env_patcher.stop()

    def test_initial_message_defined_on_line_2(self):
        with open("control/app.py", "r") as f:
            lines = f.readlines()
        self.assertEqual(lines[1].strip().startswith("INITIAL_MESSAGE = "), True)
        self.assertIn("{agent}", lines[1])
        self.assertIn("8082", lines[1])
        self.assertIn("start.sh", lines[1])

    def test_create_agent_should_increment_port_and_name(self):
        resp = self.client.post("/api/agents", json={"type": "claude", "name": "writer"})
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        self.assertEqual(data["host_port"], 18082)
        self.assertEqual(data["service_port"], 8082)
        self.assertEqual(data["container_name"], "18082-writer")

        run_kwargs = self.fake_docker.containers.last_run_kwargs
        self.assertEqual(run_kwargs["ports"]["8082/tcp"], 18082)
        self.assertEqual(run_kwargs["log_config"].config.get("max-size"), "500m")
        self.assertEqual(run_kwargs["log_config"].config.get("max-file"), "2")
        self.assertEqual(run_kwargs["volumes"]["/tmp/test_config/claude"]["bind"], "/agent-config")
        self.assertEqual(run_kwargs["volumes"]["/tmp/test_config/claude"]["mode"], "ro")
        self.assertEqual(run_kwargs["user"], "agent")
        self.assertIn(run_kwargs["network"], [None, "hermit-claw_openclaw-network"])

    def test_list_agents_should_return_logs_for_cards(self):
        resp = self.client.get("/api/agents?tail=5")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["items"][0]["container_name"], "18081-demo")
        self.assertIn("ready", data["items"][0]["logs"])

    def test_download_logs_should_return_attachment(self):
        resp = self.client.get("/api/agents/18081-demo/logs/download?tail=5")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("attachment; filename=", resp.headers.get("Content-Disposition", ""))
        self.assertIn("ready", resp.data.decode("utf-8"))

    def test_recreate_agent_should_remove_and_run_same_name_and_port(self):
        resp = self.client.post("/api/agents/18081-demo/recreate")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["container_name"], "18081-demo")

        old = self.fake_docker.containers.get("18081-demo")
        self.assertTrue(getattr(old, "_removed", False))

        run_kwargs = self.fake_docker.containers.last_run_kwargs
        self.assertEqual(run_kwargs["name"], "18081-demo")
        self.assertEqual(run_kwargs["ports"]["8082/tcp"], 18081)
        self.assertEqual(run_kwargs["user"], "agent")

    def test_textarea_no_enter_keydown_listener(self):
        with open("control/app.py", "r") as f:
            content = f.read()
        self.assertNotIn('cmdInput.addEventListener("keydown"', content)
        self.assertIn('data-action="send"', content)

    def test_send_button_onclick_exists(self):
        with open("control/app.py", "r") as f:
            content = f.read()
        self.assertIn('button[data-action="send"]', content)
        self.assertIn("sendMessage()", content)

    def test_log_refresh_after_send_message(self):
        with open("control/app.py", "r") as f:
            content = f.read()
        self.assertIn("/logs?tail=", content)
        self.assertIn("logData.logs", content)
        self.assertIn("window.cardStates[item.container_name]", content)

    def test_openclaw_agent_no_fallback_to_embedded(self):
        with open("agents/openclaw/Dockerfile", "r") as f:
            content = f.read()
        self.assertIn("delete j.gateway.bind", content)
        self.assertIn("openclaw tui", content)

    def test_agent_script_writes_to_log(self):
        with open("control/app.py", "r") as f:
            content = f.read()
        self.assertIn(">> '{log_path}'", content)
        self.assertIn("openclaw agent", content)


if __name__ == "__main__":
    unittest.main()
