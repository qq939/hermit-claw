import io
import unittest

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
        return FakeExecResult(exit_code=0, output=b"done\n")

    def remove(self, force=False):
        self._removed = True


class FakeContainers:
    def __init__(self):
        self._items = []
        self.last_run_kwargs = None

    def list(self, all=True):
        return list(self._items)

    def run(self, image, name, detach, tty, stdin_open, labels, ports, volumes, restart_policy, log_config, user=None, environment=None):
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
        }
        host_port = int(ports["8082/tcp"])
        c = FakeContainer(
            name=name,
            status="running",
            port=host_port,
            labels=labels,
            logs_text=f"{name} started",
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
        app = create_app(self.fake_docker)
        app.config["TESTING"] = True
        self.client = app.test_client()

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
        self.assertEqual(run_kwargs["volumes"]["/config/claude"]["bind"], "/agent-config")
        self.assertEqual(run_kwargs["volumes"]["/config/claude"]["mode"], "ro")
        self.assertEqual(run_kwargs["user"], "agent")

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

    def test_send_command_should_exec_in_container(self):
        resp = self.client.post("/api/agents/18081-demo/command", json={"command": "echo ok"})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["exit_code"], 0)
        self.assertIn("done", data["output"])
        target = self.fake_docker.containers.get("18081-demo")
        self.assertEqual(target._last_exec, ["/bin/sh", "-lc", "echo ok"])
        self.assertEqual(target._last_exec_kwargs.get("user"), "agent")
        self.assertTrue(target._last_exec_kwargs.get("tty"))

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


if __name__ == "__main__":
    unittest.main()
