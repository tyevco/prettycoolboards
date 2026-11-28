"""bench.py's commands and exit codes."""

import subprocess
import sys

from .conftest import BENCH

CLI = [sys.executable, "-B", str(BENCH / "bench.py")]


def run(*args):
    return subprocess.run([*CLI, *args], capture_output=True, text=True, timeout=120)


def test_faults_list():
    r = run("faults")
    assert r.returncode == 0 and "dead_rail=<rail>" in r.stdout and "short=<rail>:<mA>" in r.stdout


def test_checklist_to_file(tmp_path):
    out = tmp_path / "checklist.md"
    assert run("checklist", "--format", "md", "--out", str(out)).returncode == 0
    assert out.read_text().startswith("# Testbed bring-up")


def test_sim_exit_codes(tmp_path):
    assert run("sim", "--out", str(tmp_path), "--quiet").returncode == 0
    assert run("sim", "--out", str(tmp_path), "--quiet", "--fault", "dead_rail=+3V3_S1").returncode == 1
    assert run("sim", "--out", str(tmp_path), "--quiet", "--fault", "short=+3V3_S1:400").returncode == 2
    assert run("sim", "--out", str(tmp_path), "--quiet", "--slots", "2").returncode == 3
    r = run("sim", "--out", str(tmp_path), "--power", "bench", "--climit", "--coupons", "1=test,4=test")
    assert r.returncode == 0 and "report:" in r.stdout


def test_bad_fault_name():
    r = run("sim", "--fault", "nonsense")
    assert r.returncode != 0 and "unknown fault" in r.stderr


def test_real_run_needs_a_board_serial():
    r = run("run", "--port", "/dev/does-not-exist")
    assert r.returncode == 1 and "--board-serial" in r.stderr


def test_real_run_on_a_missing_port(tmp_path):
    r = run("run", "--port", "/dev/does-not-exist", "--board-serial", "X", "--out", str(tmp_path))
    assert r.returncode == 1
    assert "pyserial" in (r.stderr + r.stdout) or "cannot open" in (r.stderr + r.stdout)


def test_coupon_declaration(tmp_path):
    r = run("sim", "--out", str(tmp_path), "--quiet", "--coupons", "1=test,2=hall", "--inj", "--key-check")
    assert r.returncode == 0, r.stdout + r.stderr
    r = run("sim", "--out", str(tmp_path), "--quiet", "--coupon", "1=coil")
    assert r.returncode != 0 and "A2" in r.stderr


def test_turned_test_from_the_command_line(tmp_path):
    r = run("sim", "--out", str(tmp_path), "--power", "bench", "--turned-test", "2")
    assert r.returncode == 0, r.stdout + r.stderr
    r = run("sim", "--out", str(tmp_path), "--quiet", "--power", "bench", "--turned-test", "2",
            "--fault", "lines_before_desc")
    assert r.returncode == 1
