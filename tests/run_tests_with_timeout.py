import subprocess
import sys


def main():
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/test_control_api.py", "-q"],
            timeout=90,
            check=False,
        )
        return result.returncode
    except subprocess.TimeoutExpired:
        print("Test execution timed out after 90 seconds.")
        return 124


if __name__ == "__main__":
    raise SystemExit(main())
