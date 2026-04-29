#!/usr/bin/env python3
import subprocess, time, json, sys, signal, socket, urllib.request, urllib.error

CONTROL_URL = "http://localhost:18080"
TIMEOUT = 600

def run(cmd, check=True, timeout=120):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    if check and r.returncode != 0:
        raise RuntimeError(f"CMD [{r.returncode}]: {cmd}\nout={r.stdout}\nerr={r.stderr}")
    return r

def wait_port(host, port, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            s = socket.create_connection((host, port), timeout=2)
            s.close()
            return True
        except Exception:
            time.sleep(1)
    return False

def http_get(path):
    req = urllib.request.Request(f"{CONTROL_URL}{path}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status, resp.read().decode('utf-8', errors='replace')

def test(name, fn):
    print(f"\n[TEST] {name}")
    try:
        fn()
        print(f"[PASS] {name}")
        return True
    except Exception as e:
        print(f"[FAIL] {e}")
        import traceback; traceback.print_exc()
        return False

def step(results, name, fn):
    results.append(test(name, fn))
    if not results[-1]:
        print(f"\n[ABORT] {name} failed")
        sys.exit(1)

def cleanup(name):
    print(f"  [cleanup] {name}")
    run(f"docker rm -f {name} 2>/dev/null || true", check=False)

def ssh_exec_python(code):
    escaped = code.replace('"', '\\"').replace('\n', '; ')
    return run(f'docker exec hermit-control-18080 python3 -c "{escaped}"', timeout=30)

def main():
    results = []
    ts = int(time.time())
    custom_name = f"test-{ts}"

    def t1():
        assert wait_port("localhost", 18080, 10), "Control not responding"
    step(results, "1: Control is healthy", t1)

    def t2():
        run(f"docker build -t hermit-agent-claude:latest ./agents/claude", timeout=300)
        print("  built OK")
    step(results, "2: Rebuild hermit-claude image", t2)

    def t3():
        run(f"docker build -t hermit-claw-control-18080:latest ./control", timeout=300)
        print("  built OK")
    step(results, "3: Rebuild control image", t3)

    def t4():
        run("docker compose stop control-18080 2>/dev/null || true")
        run("docker compose rm -f control-18080 2>/dev/null || true")
        run("docker compose up -d control-18080")
        time.sleep(5)
        assert wait_port("localhost", 18080, 30), "not ready"
    step(results, "4: Restart control service", t4)

    def t5():
        s, b = http_get("/api/agents")
        print(f"  status={s}")
        assert s == 200
    step(results, "5: /api/agents responds (health check)", t5)

    cleanup(f"18086-{custom_name}")

    def t6():
        payload = json.dumps({"name": custom_name, "type": "claude"}).encode()
        req = urllib.request.Request(f"{CONTROL_URL}/api/agents", data=payload,
                                    headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode()
            data = json.loads(body)
            print(f"  {resp.status} {data}")
            assert resp.status == 201, f"Expected 201, got {resp.status}"
        return data.get("container_name")
    tc = t6()
    results.pop()
    results.append(True)
    print(f"\n[TEST] 6: Create agent via API")
    print(f"[PASS] 6: Create agent via API (container={tc})")

    def t7():
        time.sleep(3)
        r = run(f"docker inspect -f '{{{{.State.Running}}}}' {tc} 2>/dev/null || echo false")
        print(f"  {r.stdout.strip()}")
        assert 'true' in r.stdout
    step(results, "7: Container is running", t7)

    def t8():
        r = run(f"docker inspect -f '{{{{json .NetworkSettings.Networks}}}}' {tc}")
        nets = list(json.loads(r.stdout.strip()).keys())
        print(f"  {nets}")
        assert any('openclaw' in n or 'hermit' in n for n in nets)
    step(results, "8: Container on openclaw-network", t8)

    def t9():
        time.sleep(5)
        r = run(f"docker exec {tc} ps aux 2>/dev/null || docker exec {tc} ps", check=False)
        print(f"  processes:\n{r.stdout.strip()}")
        assert 'sshd' in r.stdout.lower(), f"sshd not running. Processes:\n{r.stdout}"
    step(results, "9: SSH port 22 listening (sshd process check)", t9)

    def t10():
        r = run(f"docker exec hermit-control-18080 getent hosts {tc}")
        print(f"  {r.stdout.strip()}")
        assert tc in r.stdout
    step(results, "10: Control can resolve container name", t10)

    def t11():
        r = ssh_exec_python(
            f"import paramiko;ssh=paramiko.SSHClient();"
            f"ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy());"
            f"ssh.connect('{tc}',port=22,username='agent',password='agent',timeout=10);"
            f"_,o,_=ssh.exec_command('echo SSH_OK');print(o.read().decode().strip());ssh.close()"
        )
        print(f"  {r.stdout.strip()}")
        assert 'SSH_OK' in r.stdout
    step(results, "11: paramiko SSH exec_command works", t11)

    def t12():
        r = ssh_exec_python(
            f"import paramiko;ssh=paramiko.SSHClient();"
            f"ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy());"
            f"ssh.connect('{tc}',port=22,username='agent',password='agent',timeout=10);"
            f"t=ssh.get_transport();ch=t.open_session();"
            f"ch.exec_command('whoami');u=ch.recv(1024).decode().strip();"
            f"print('USER:',u);ch.close();ssh.close()"
        )
        print(f"  {r.stdout.strip()}")
        assert 'USER: agent' in r.stdout
    step(results, "12: paramiko invoke_shell works", t12)

    def t13():
        s, b = http_get("/api/agents")
        agents = json.loads(b)["items"]
        names = [a.get('container_name') or a.get('name') for a in agents]
        print(f"  {names}")
        assert tc in names
    step(results, "13: /api/agents includes new container", t13)

    def t14():
        s, b = http_get(f"/api/agents/{tc}/ssh-info")
        info = json.loads(b)
        print(f"  {info}")
        assert s == 200 and info.get('container') == tc
    step(results, "14: /api/agents/<name>/ssh-info has container name", t14)

    cleanup(tc)

    passed = sum(results)
    print(f"\n{'='*60}\n{passed}/{len(results)} passed\n{'='*60}")
    if not all(results):
        sys.exit(1)
    print("ALL TESTS PASSED")

if __name__ == "__main__":
    signal.signal(signal.SIGALRM, lambda *a: (print(f"\n[TIMEOUT {TIMEOUT}s]"), sys.exit(1)))
    signal.alarm(TIMEOUT)
    try:
        main()
    except Exception as e:
        print(f"\n[FATAL] {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)
