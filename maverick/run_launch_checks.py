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

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover - optional runtime dependency
    def load_dotenv(_path=None):
        return False


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
    stripe_secret = os.getenv("STRIPE_SECRET_KEY", "").strip()
    stripe_publishable = os.getenv("STRIPE_PUBLISHABLE_KEY", "").strip()
    stripe_webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
    database_url = os.getenv("DATABASE_URL", "").strip()

    if stripe_secret.startswith("sk_"):
        results.append(_pass("env:STRIPE_SECRET_KEY", f"set ({stripe_secret[:7]}...)"))
    elif stripe_secret:
        results.append(_fail("env:STRIPE_SECRET_KEY", "present but invalid format (expected sk_*)"))
    else:
        results.append(_fail("env:STRIPE_SECRET_KEY", "missing"))

    if stripe_publishable.startswith("pk_"):
        results.append(
            _pass("env:STRIPE_PUBLISHABLE_KEY", f"set ({stripe_publishable[:7]}...)")
        )
    elif stripe_publishable:
        results.append(
            _fail(
                "env:STRIPE_PUBLISHABLE_KEY",
                "present but invalid format (expected pk_*)",
            )
        )
    else:
        results.append(_fail("env:STRIPE_PUBLISHABLE_KEY", "missing"))

    if stripe_webhook_secret.startswith("whsec_"):
        results.append(
            _pass("env:STRIPE_WEBHOOK_SECRET", f"set ({stripe_webhook_secret[:8]}...)")
        )
    elif stripe_webhook_secret:
        results.append(
            _fail(
                "env:STRIPE_WEBHOOK_SECRET",
                "present but invalid format (expected whsec_*)",
            )
        )
    else:
        results.append(_fail("env:STRIPE_WEBHOOK_SECRET", "missing"))

    placeholder_markers = ("user:pass@host:port/dbname", "postgres:...@containers-")
    if not database_url:
        results.append(_fail("env:DATABASE_URL", "missing"))
    elif any(marker in database_url for marker in placeholder_markers):
        results.append(_fail("env:DATABASE_URL", "placeholder value detected"))
    elif database_url.startswith("postgresql://") or database_url.startswith("postgres://"):
        results.append(_pass("env:DATABASE_URL", f"set ({database_url[:8]}...)"))
    else:
        results.append(_fail("env:DATABASE_URL", "invalid format (expected postgres URL)"))
    return results


def check_flask_routes(project_dir: Path) -> list[CheckResult]:
    # Import from local project directory.
    if str(project_dir) not in sys.path:
        sys.path.insert(0, str(project_dir))

    try:
        import app as maverick_app_module  # noqa: WPS433
    except Exception as exc:
        return [_fail("flask:import", f"failed to import app.py ({exc})")]

    # Monkeypatch DB query calls during smoke tests to keep checks side-effect free.
    def fake_execute_query(_query, _params=None, fetch=False):
        return [] if fetch else True

    maverick_app_module.execute_query = fake_execute_query

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

    stripe_webhook_smoke = client.post("/stripe/webhook", data=b"{}", headers={})
    if stripe_webhook_smoke.status_code in {400, 500}:
        results.append(
            _pass(
                "flask:/stripe/webhook",
                f"endpoint reachable (status={stripe_webhook_smoke.status_code})",
            )
        )
    else:
        results.append(
            _fail(
                "flask:/stripe/webhook",
                f"unexpected status={stripe_webhook_smoke.status_code}",
            )
        )

    return results


def run_worker_dry_run(script_name: str, project_dir: Path, extra_args: list[str] | None = None) -> CheckResult:
    cmd = [sys.executable, script_name]
    if extra_args:
        cmd.extend(extra_args)
    cmd.append("--dry-run")
    env = os.environ.copy()
    if "user:pass@host:port/dbname" in env.get("DATABASE_URL", ""):
        env["DATABASE_URL"] = ""

    try:
        completed = subprocess.run(
            cmd,
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
            env=env,
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
    results.append(run_worker_dry_run("run_stripe_minions.py", project_dir, extra_args=["--all"]))

    print_results(results)

    failed = [item for item in results if not item.passed]
    if failed:
        print("\nLaunch checks failed. Fix failing items before go-live.")
        return 1

    print("\nAll launch checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
