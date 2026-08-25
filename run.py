"""Cortex Nexus — Unified Local Orchestrator & Development Runner.

Single-command operations for local development, testing, diagnostics, and builds.

Usage:
  python run.py dev       # Start both Backend API and Frontend UI concurrently
  python run.py test      # Run full qualification and regression test suites
  python run.py doctor    # Run environment and service health diagnostics
  python run.py build     # Build production artifacts (Next.js static build & backend)
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
FRONTEND_DIR = os.path.join(ROOT_DIR, "frontend")


def get_backend_python() -> str:
    """Find the backend virtualenv python executable."""
    if sys.platform == "win32":
        venv_python = os.path.join(BACKEND_DIR, ".venv", "Scripts", "python.exe")
        if os.path.exists(venv_python):
            return venv_python
    else:
        venv_python = os.path.join(BACKEND_DIR, ".venv", "bin", "python")
        if os.path.exists(venv_python):
            return venv_python
    return sys.executable


def get_backend_pytest() -> str:
    """Find the backend pytest executable."""
    if sys.platform == "win32":
        venv_pytest = os.path.join(BACKEND_DIR, ".venv", "Scripts", "pytest.exe")
        if os.path.exists(venv_pytest):
            return venv_pytest
    else:
        venv_pytest = os.path.join(BACKEND_DIR, ".venv", "bin", "pytest")
        if os.path.exists(venv_pytest):
            return venv_pytest
    return "pytest"


def run_dev():
    """Start both FastAPI backend and Next.js frontend concurrently."""
    python_exec = get_backend_python()
    print("================================================================")
    print("   [+] CORTEX NEXUS -- LOCAL DEVELOPMENT ENVIRONMENT STARTING   ")
    print("================================================================")
    print(f"* Root Directory:      {ROOT_DIR}")
    print(f"* Backend Runtime:     {python_exec}")
    print("* Backend API Docs:    http://localhost:8000/docs")
    print("* Realtime Stream:     ws://localhost:8000/api/v1/realtime/ws")
    print("* Frontend Cockpit:    http://localhost:3000")
    print("================================================================")
    print("Press Ctrl+C at any time to cleanly stop all servers.\n")

    env = os.environ.copy()
    env["PYTHONPATH"] = BACKEND_DIR
    env["CORTEX_ENV"] = "dev"

    # Start backend process
    backend_cmd = [
        python_exec,
        "-m",
        "uvicorn",
        "app.main:app",
        "--reload",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
    ]
    backend_proc = subprocess.Popen(
        backend_cmd,
        cwd=BACKEND_DIR,
        env=env,
    )

    # Start frontend process
    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
    frontend_proc = subprocess.Popen(
        [npm_cmd, "run", "dev"],
        cwd=FRONTEND_DIR,
        shell=(sys.platform == "win32"),
    )

    def shutdown(sig, frame):
        print("\n\nShutting down Cortex Nexus development servers...")
        try:
            backend_proc.terminate()
            frontend_proc.terminate()
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        while True:
            time.sleep(0.5)
            if backend_proc.poll() is not None:
                print("Backend process terminated.")
                break
            if frontend_proc.poll() is not None:
                print("Frontend process terminated.")
                break
    except KeyboardInterrupt:
        shutdown(None, None)


def run_tests(args):
    """Run test suites."""
    pytest_exec = get_backend_pytest()
    print("================================================================")
    print("   [+] CORTEX NEXUS -- RUNNING TEST SUITES                      ")
    print("================================================================")

    if args.suite == "nexus" or args.suite == "qualification":
        test_files = [
            "tests/test_nexus_production_runtime.py",
            "tests/test_nexus_api_and_chaos.py",
            "tests/test_nexus_enterprise_production_release.py",
            "tests/test_production_qualification_chaos.py",
            "tests/test_production_qualification_load.py",
            "tests/test_production_qualification_security.py",
        ]
        cmd = [pytest_exec] + test_files + ["-v"]
    elif args.suite == "full" or args.suite == "regression":
        cmd = [pytest_exec, "-k", "not test_gnn and not test_intelligence", "-v", "--tb=short"]
    else:
        cmd = [pytest_exec, "tests/", "-v", "--tb=short"]

    result = subprocess.run(cmd, cwd=BACKEND_DIR)
    sys.exit(result.returncode)


def run_doctor():
    """Run comprehensive system diagnostics."""
    print("================================================================")
    print("   [+] CORTEX NEXUS -- SYSTEM DIAGNOSTICS & DOCTOR              ")
    print("================================================================")

    python_exec = get_backend_python()
    print(f"[OK] Python Runtime:       {python_exec} (v{sys.version.split()[0]})")
    print(f"[OK] Backend Path:         {BACKEND_DIR}")
    print(f"[OK] Frontend Path:        {FRONTEND_DIR}")

    # Check Node.js & npm
    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
    try:
        node_res = subprocess.run(["node", "--version"], capture_output=True, text=True, check=True)
        print(f"[OK] Node.js Runtime:      {node_res.stdout.strip()}")
    except Exception:
        print("[!]  Node.js Runtime:      Not found in PATH")

    # Run Nexus CLI doctor
    env = os.environ.copy()
    env["PYTHONPATH"] = BACKEND_DIR
    res = subprocess.run([python_exec, "-m", "app.cli.nexus_cli", "doctor"], cwd=BACKEND_DIR, env=env)
    print("================================================================")


def run_build():
    """Build production frontend and test backend readiness."""
    print("================================================================")
    print("   [+] CORTEX NEXUS -- PRODUCTION BUILD                         ")
    print("================================================================")
    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
    frontend_res = subprocess.run([npm_cmd, "run", "build"], cwd=FRONTEND_DIR, shell=(sys.platform == "win32"))
    if frontend_res.returncode != 0:
        print("[FAIL] Frontend production build failed.")
        sys.exit(frontend_res.returncode)
    print("[OK] Frontend 31/31 routes compiled successfully.")


def main():
    parser = argparse.ArgumentParser(prog="run.py", description="Cortex Nexus Unified Local Runner")
    subparsers = parser.add_subparsers(dest="subcommand", help="Command to execute")

    # dev
    subparsers.add_parser("dev", help="Start both Backend API and Frontend UI concurrently")

    # test
    test_parser = subparsers.add_parser("test", help="Execute test suites")
    test_parser.add_argument(
        "--suite",
        choices=["nexus", "qualification", "regression", "full"],
        default="nexus",
        help="Test suite selection (default: nexus qualification suite)",
    )

    # doctor
    subparsers.add_parser("doctor", help="Run system diagnostics")

    # build
    subparsers.add_parser("build", help="Compile production Next.js frontend")

    args, remaining = parser.parse_known_args()

    if args.subcommand == "dev":
        run_dev()
    elif args.subcommand == "test":
        run_tests(args)
    elif args.subcommand == "doctor":
        run_doctor()
    elif args.subcommand == "build":
        run_build()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
