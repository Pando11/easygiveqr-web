#!/usr/bin/env python3
"""
Maverick launch smoke test harness.

Runs a pre-launch checklist with one command:
- Flask route health and upload/payment endpoint smoke checks
- Stripe key readiness checks
- Reminder worker dry-run
- Problem detection worker dry-run
"""

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass
class CheckResult:
    name: str
    passed: bool
    details: str


def _pass(name: str, details: str) -> CheckResult:
    return CheckResult(name=name, passed=True, details=details)


def _fail(name: str, details: str) -> CheckResult:
    return CheckResult(name=name, passed=False, details=details)


def check_env_keys() -> list[CheckResult]:
    results: list[CheckResult] = []
    required = ["STRIPE_SECRET_KEY", "STRIPE_PUBLISHABLE_KEY", "DATABASE_URL"]

    for key in required:
        value = os.getenv(key, "").strip()
        if value:
            redacted = f"{value[:7]}..." if len(value) > 10 else "***"
            results.append(_pass(f"env:{key}", f"set ({redacted})"))
        else:
            results.append(_fail(f"env:{key}", "missing"))
    return results


def check_flask_routes(project_dir: Path) -> list[CheckResult]:
    # Import from local project directory.
    if str(project_dir) not in sys.path:
        sys.path.insert(0, str(project_dir))

    try:
        import app as maverick_app_module  # noqa: WPS433
    except Exception as exc:
        return [_fail("flask:import", f"failed to import app.py ({exc})")]

    app = maverick_app_module.app
    client = app.test_client()
    results: list[CheckResult] = []

    health = client.get("/health")
    if health.status_code == 200:
        results.append(_pass("flask:/health", f"status={health.status_code}"))
    else:
        results.append(_fail("flask:/health", f"unexpected status={health.status_code}"))

    home = client.get("/")
    if home.status_code == 200:
        results.append(_pass("flask:/", "upload page reachable"))
    else:
        results.append(_fail("flask:/", f"unexpected status={home.status_code}"))

    upload_validation = client.post("/upload", data={})
    if upload_validation.status_code in {400, 413}:
        results.append(
            _pass("flask:/upload", f"validation active (status={upload_validation.status_code})")
        )
    else:
        results.append(
            _fail("flask:/upload", f"expected 400/413 validation, got {upload_validation.status_code}")
        )

    pay_invalid_type = client.get("/pay/1/invalid")
    if pay_invalid_type.status_code == 400:
        results.append(_pass("flask:/pay invalid type", "returns 400 as expected"))
    else:
        results.append(
            _fail("flask:/pay invalid type", f"expected 400, got {pay_invalid_type.status_code}")
        )

    pay_missing_txn = client.get("/pay/999999/upfront")
    if pay_missing_txn.status_code in {404, 200}:
        results.append(
            _pass(
                "flask:/pay transaction lookup",
                f"handled missing transaction (status={pay_missing_txn.status_code})",
            )
        )
    else:
        results.append(
            _fail(
                "flask:/pay transaction lookup",
                f"unexpected status={pay_missing_txn.status_code}",
            )
        )

    return results


def run_worker_dry_run(script_name: str, project_dir: Path) -> CheckResult:
    cmd = [sys.executable, script_name, "--dry-run"]
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except Exception as exc:
        return _fail(f"worker:{script_name}", f"failed to execute ({exc})")

    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip()
        return _fail(
            f"worker:{script_name}",
            f"exit={completed.returncode}; {stderr[:220]}",
        )

    first_line = (completed.stdout.strip().splitlines() or ["ok"])[0]
    return _pass(f"worker:{script_name}", first_line[:220])


def print_results(results: list[CheckResult]) -> None:
    print("\nMaverick Launch Checks")
    print("=" * 60)
    for item in results:
        prefix = "PASS" if item.passed else "FAIL"
        print(f"[{prefix}] {item.name} - {item.details}")
    print("=" * 60)

    passed = sum(1 for item in results if item.passed)
    failed = len(results) - passed
    print(f"Summary: {passed} passed, {failed} failed")


def main() -> int:
    project_dir = Path(__file__).resolve().parent
    load_dotenv(project_dir / ".env")

    results: list[CheckResult] = []

    results.extend(check_env_keys())
    results.extend(check_flask_routes(project_dir))
    results.append(run_worker_dry_run("send_reminders.py", project_dir))
    results.append(run_worker_dry_run("check_problems.py", project_dir))

    print_results(results)

    failed = [item for item in results if not item.passed]
    if failed:
        print("\nLaunch checks failed. Fix failing items before go-live.")
        return 1

    print("\nAll launch checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
