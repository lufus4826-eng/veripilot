#!/usr/bin/env python3
"""12-suite cross-platform unit & integration tests for VeriPilot CLI (scripts/vpilot.py)."""

from __future__ import annotations

import difflib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


SKILL_ROOT = Path(__file__).resolve().parents[1]
VPILOT_PY = SKILL_ROOT / "scripts" / "vpilot.py"
SKILL_MD = SKILL_ROOT / "SKILL.md"


def _run_cli(args: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run(
        [sys.executable, "-B", str(VPILOT_PY), *args],
        cwd=str(cwd) if cwd else None,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    if check and proc.returncode != 0:
        raise AssertionError(
            f"vpilot.py failed ({proc.returncode}): {' '.join(args)}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc


def _run_git(cwd: Path, git_args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *git_args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=True,
    )


def _kv(stdout: str) -> dict[str, str]:
    res: dict[str, str] = {}
    key_re = re.compile(r"(?:^|\s)([A-Z][A-Z0-9_]*)=")
    for line in stdout.splitlines():
        matches = list(key_re.finditer(line))
        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(line)
            res[m.group(1)] = line[m.end() : end].strip()
    return res


def _make_patch(rel_path: str, old_text: str, new_text: str) -> str:
    diff = "".join(
        difflib.unified_diff(
            old_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=f"a/{rel_path}",
            tofile=f"b/{rel_path}",
            n=3,
        )
    )
    return f"diff --git a/{rel_path} b/{rel_path}\n{diff}"


def _build_stub_skills(skills_dir: Path, skip: set[str] | None = None) -> Path:
    skip = skip or set()
    skills_dir.mkdir(parents=True, exist_ok=True)
    mapping = {
        "veripilot": "scripts/vpilot.py",
        "veripr": "scripts/vpr.py",
        "verihunt": "scripts/bh.py",
        "verisec": "scripts/vs.py",
        "veriperf": "scripts/vp.py",
    }
    for sk, cli_rel in mapping.items():
        if sk in skip:
            continue
        dst = skills_dir / sk
        if sk == "veripilot":
            shutil.copytree(
                SKILL_ROOT,
                dst,
                ignore=shutil.ignore_patterns(".git", ".bughunt", "__pycache__", ".pytest_cache"),
            )
            continue
        (dst / "scripts").mkdir(parents=True, exist_ok=True)
        (dst / "SKILL.md").write_text(f"---\nname: {sk}\ndescription: {sk}\n---\n# {sk}\n", encoding="utf-8")
        (dst / cli_rel).write_text(f'print("{sk} ok")\n', encoding="utf-8")
    return skills_dir


def _init_git_repo(repo_dir: Path, files: dict[str, str], crlf: bool = False) -> None:
    repo_dir.mkdir(parents=True, exist_ok=True)
    _run_git(repo_dir, ["init", "-b", "main"])
    _run_git(repo_dir, ["config", "user.name", "VeriPilot Test"])
    _run_git(repo_dir, ["config", "user.email", "test@verihunt.local"])
    for rel, content in files.items():
        fp = repo_dir / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        raw = content.replace("\r\n", "\n")
        if crlf:
            raw = raw.replace("\n", "\r\n")
        fp.write_bytes(raw.encode("utf-8"))
    _run_git(repo_dir, ["add", "."])
    _run_git(repo_dir, ["commit", "-m", "initial commit"])


class VeriPilotCliTestSuite(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="vp_test_")
        self.tmp = Path(self._tmp.name)
        self.skills_dir = _build_stub_skills(self.tmp / "skills_bundle")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_01_init_session_git_exclude_and_skill_discovery(self) -> None:
        repo = self.tmp / "repo1"
        _init_git_repo(repo, {"app.py": "def ok():\n    return 1\n"})
        p1 = _run_cli(["init", "--root", str(repo), "--skills-dir", str(self.skills_dir)])
        lines = p1.stdout.strip().splitlines()
        self.assertLessEqual(len(lines), 12)
        kv = _kv(p1.stdout)
        s_dir = Path(kv["S"])
        self.assertTrue((s_dir / "baseline" / "app.py").is_file())
        self.assertTrue((s_dir / "overlay" / "app.py").is_file())
        self.assertEqual(kv["SKILLS_MISSING"], "none")
        excl = (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")
        self.assertIn(".bughunt/", excl)
        # Re-run init should report ALREADY_PRESENT and never duplicate entry
        p2 = _run_cli(["init", "--root", str(repo), "--skills-dir", str(self.skills_dir)])
        self.assertIn("EXCLUDE=ALREADY_PRESENT", p2.stdout)
        self.assertEqual(excl.count(".bughunt/"), 1)

    def test_02_route_thai_bilingual_intent_and_word_boundaries(self) -> None:
        repo = self.tmp / "repo2"
        _init_git_repo(repo, {"core.py": "def run():\n    return True\n"})
        # Clean repo + words containing 'pr' or 'sec' inside longer tokens ("product", "second") should NOT misroute
        p_clean = _run_cli([
            "route", "--root", str(repo), "--skills-dir", str(self.skills_dir),
            "--prompt", "Help optimize product latency in the second step",
        ])
        kv_clean = _kv(p_clean.stdout)
        self.assertEqual(kv_clean["PLAN"], "veriperf")

        # Thai + English correctness/security triggers
        p_th = _run_cli([
            "route", "--root", str(repo), "--skills-dir", str(self.skills_dir),
            "--prompt", "ช่วยหาบัคและเช็กสิทธิ์รั่วในโมดูลนี้หน่อย",
        ])
        self.assertEqual(_kv(p_th.stdout)["PLAN"], "verihunt -> verisec")

    def test_03_route_git_diff_and_risk_auto_sec(self) -> None:
        repo = self.tmp / "repo3"
        _init_git_repo(repo, {
            "payment_service.py": "def refund(owner_id, requester_id):\n    return owner_id == requester_id\n",
            "receipt_api.py": "def receipt(x):\n    return x\n",
        })
        _run_git(repo, ["checkout", "-b", "feat/pay"])
        (repo / "payment_service.py").write_text(
            "def refund(owner_id, requester_id):\n    return True\n", encoding="utf-8"
        )
        _run_git(repo, ["add", "."])
        _run_git(repo, ["commit", "-m", "feat: update payment refund"])

        s_dir = Path(_kv(_run_cli(["init", "--root", str(repo), "--skills-dir", str(self.skills_dir)]).stdout)["S"])
        p_route = _run_cli([
            "route", "--root", str(repo), "--s", str(s_dir), "--skills-dir", str(self.skills_dir),
            "--prompt", "ช่วยเช็กโค้ดก่อนส่งให้หน่อย เพิ่งแก้ระบบชำระเงินกับใบเสร็จไป",
        ])
        kv = _kv(p_route.stdout)
        self.assertEqual(kv["PLAN"], "veripr -> verisec")
        self.assertEqual(kv["SEC_RISK"], "HIGH")
        self.assertEqual(kv["AUTO_SEC"], "True")
        self.assertEqual(kv["BUDGET_GATE"], "AUTO_PROCEED")
        expected_overlay = str((s_dir / "overlay").resolve())
        self.assertEqual(kv["NEXT_TARGET_ROOT"], expected_overlay)
        self.assertEqual(kv["NEXT_STAGE_ARGS"], f'--root "{expected_overlay}"')

    def test_04_route_causal_reordering_enforced(self) -> None:
        repo = self.tmp / "repo4"
        _init_git_repo(repo, {"util.py": "def f(x):\n    return x\n"})
        p_mix = _run_cli([
            "route", "--root", str(repo), "--skills-dir", str(self.skills_dir),
            "--prompt", "optimize speed, hunt bugs, check idor, and review PR diff",
        ])
        kv = _kv(p_mix.stdout)
        self.assertEqual(kv["PLAN"], "veripr -> verihunt -> verisec -> veriperf")
        self.assertEqual(kv["REORDERED"], "True")
        self.assertEqual(kv["BUDGET_GATE"], "CONFIRM_OVER_2_SKILLS")

    def test_05_cumulative_overlay_handoff_no_conflict(self) -> None:
        repo = self.tmp / "repo5"
        orig = "def fee(x):\n    return None\n\ndef refund(owner, req):\n    return True\n"
        _init_git_repo(repo, {"pay.py": orig})
        s_dir = Path(_kv(_run_cli(["init", "--root", str(repo), "--skills-dir", str(self.skills_dir)]).stdout)["S"])
        _run_cli([
            "route", "--root", str(repo), "--s", str(s_dir), "--skills-dir", str(self.skills_dir),
            "--prompt", "review PR and check security",
        ])

        step1 = "def fee(x):\n    return 0.0\n\ndef refund(owner, req):\n    return True\n"
        p1 = s_dir / "tmp" / "s1.patch"
        p1.write_text(_make_patch("pay.py", orig, step1), encoding="utf-8")
        h1 = _run_cli(["handoff", "--s", str(s_dir), "--skill", "veripr", "--patch", str(p1), "--findings", "1"])
        kv_h1 = _kv(h1.stdout)
        self.assertEqual(kv_h1["NEXT_SKILL"], "verisec")
        expected_overlay = str((s_dir / "overlay").resolve())
        self.assertEqual(kv_h1["NEXT_TARGET_ROOT"], expected_overlay)
        self.assertEqual(kv_h1["NEXT_STAGE_ARGS"], f'--root "{expected_overlay}"')
        self.assertIn("return 0.0", (s_dir / "overlay" / "pay.py").read_text(encoding="utf-8"))

        step2 = "def fee(x):\n    return 0.0\n\ndef refund(owner, req):\n    return owner == req\n"
        p2 = s_dir / "tmp" / "s2.patch"
        p2.write_text(_make_patch("pay.py", step1, step2), encoding="utf-8")
        h2 = _run_cli(["handoff", "--s", str(s_dir), "--skill", "verisec", "--patch", str(p2), "--findings", "1"])
        kv_h2 = _kv(h2.stdout)
        self.assertEqual(kv_h2["NEXT_SKILL"], "NONE")
        self.assertEqual(kv_h2["NEXT_TARGET_ROOT"], "NONE")
        self.assertEqual(kv_h2["NEXT_STAGE_ARGS"], "NONE")
        final_overlay = (s_dir / "overlay" / "pay.py").read_text(encoding="utf-8")
        self.assertIn("return 0.0", final_overlay)
        self.assertIn("owner == req", final_overlay)

    def test_06_handoff_from_dir_and_direct_overlay_edits(self) -> None:
        repo = self.tmp / "repo6"
        _init_git_repo(repo, {"mod.py": "def val():\n    return 1\n"})
        s_dir = Path(_kv(_run_cli(["init", "--root", str(repo), "--skills-dir", str(self.skills_dir)]).stdout)["S"])
        _run_cli([
            "route", "--root", str(repo), "--s", str(s_dir), "--skills-dir", str(self.skills_dir),
            "--prompt", "hunt bugs and check security",
        ])
        from_dir = self.tmp / "stage1_fix"
        from_dir.mkdir()
        (from_dir / "mod.py").write_text("def val():\n    return 2\n", encoding="utf-8")
        h1 = _run_cli(["handoff", "--s", str(s_dir), "--skill", "verihunt", "--from-dir", str(from_dir)])
        self.assertEqual(_kv(h1.stdout)["FILES_UPDATED"], "mod.py")
        # Direct edit in S/overlay/ for Stage 2
        (s_dir / "overlay" / "mod.py").write_text("def val():\n    return 3\n", encoding="utf-8")
        h2 = _run_cli(["handoff", "--s", str(s_dir), "--skill", "verisec"])
        self.assertEqual(_kv(h2.stdout)["FILES_UPDATED"], "mod.py")
        self.assertTrue((s_dir / "patches" / "stage_2_verisec.patch").is_file())

    def test_07_circuit_breaker_broken_harness_and_status(self) -> None:
        repo = self.tmp / "repo7"
        _init_git_repo(repo, {"broken_test.py": "def bad(:\n    pass\n"})
        s_dir = Path(_kv(_run_cli(["init", "--root", str(repo), "--skills-dir", str(self.skills_dir)]).stdout)["S"])
        _run_cli([
            "route", "--root", str(repo), "--s", str(s_dir), "--skills-dir", str(self.skills_dir),
            "--prompt", "review pr, check security, optimize perf",
        ])
        h_cmd = _run_cli([
            "handoff", "--s", str(s_dir), "--skill", "veripr",
            "--check-cmd", f"{sys.executable} -m py_compile broken_test.py",
        ])
        kv = _kv(h_cmd.stdout)
        self.assertEqual(kv["CIRCUIT_BREAKER"], "TRIPPED")
        self.assertEqual(kv["REASON"], "HARNESS_BROKEN")
        self.assertEqual(kv["NEXT_SKILL"], "NONE")

        # Also check explicit ENV_BROKEN status
        s_dir2 = Path(_kv(_run_cli(["init", "--root", str(repo), "--skills-dir", str(self.skills_dir)]).stdout)["S"])
        h_stat = _run_cli(["handoff", "--s", str(s_dir2), "--skill", "veripr", "--status", "ENV_BROKEN"])
        self.assertEqual(_kv(h_stat.stdout)["REASON"], "ENV_BROKEN")

    def test_08_circuit_breaker_over_2_skill_budget_gate(self) -> None:
        repo = self.tmp / "repo8"
        _init_git_repo(repo, {"svc.py": "def f():\n    return 1\n"})
        s_dir = Path(_kv(_run_cli(["init", "--root", str(repo), "--skills-dir", str(self.skills_dir)]).stdout)["S"])
        _run_cli([
            "route", "--root", str(repo), "--s", str(s_dir), "--skills-dir", str(self.skills_dir),
            "--prompt", "check pr, check sec, optimize perf",
        ])
        _run_cli(["handoff", "--s", str(s_dir), "--skill", "veripr", "--enforce-budget"])
        h2 = _run_cli(["handoff", "--s", str(s_dir), "--skill", "verisec", "--enforce-budget"])
        kv2 = _kv(h2.stdout)
        self.assertEqual(kv2["CIRCUIT_BREAKER"], "TRIPPED")
        self.assertEqual(kv2["REASON"], "BUDGET_EXCEEDED_2_SKILLS")

    def test_09_finalize_pure_lf_patch_and_crlf_host_git_apply(self) -> None:
        repo = self.tmp / "repo9"
        orig = "def calc(x):\n    return None\n"
        _init_git_repo(repo, {"calc.py": orig}, crlf=True)
        s_dir = Path(_kv(_run_cli(["init", "--root", str(repo), "--skills-dir", str(self.skills_dir)]).stdout)["S"])
        _run_cli([
            "route", "--root", str(repo), "--s", str(s_dir), "--skills-dir", str(self.skills_dir),
            "--prompt", "review PR",
        ])
        fixed = "def calc(x):\n    return 0\n"
        p1 = s_dir / "tmp" / "fix.patch"
        p1.write_text(_make_patch("calc.py", orig, fixed), encoding="utf-8")
        _run_cli(["handoff", "--s", str(s_dir), "--skill", "veripr", "--patch", str(p1)])

        fin = _run_cli(["finalize", "--s", str(s_dir), "--clean"])
        kv = _kv(fin.stdout)
        patch_path = Path(kv["UNIFIED_PATCH"])
        raw = patch_path.read_bytes()
        self.assertNotIn(b"\r", raw)
        self.assertEqual(kv["PURE_LF"], "True")
        self.assertEqual(kv["GIT_APPLY"], "OK")
        _run_git(repo, ["apply", "--ignore-space-change", "--ignore-whitespace", str(patch_path)])
        self.assertIn("return 0", (repo / "calc.py").read_text(encoding="utf-8"))

    def test_10_finalize_clean_host_isolation_and_stray_sweep(self) -> None:
        repo = self.tmp / "repo10"
        _init_git_repo(repo, {"app.py": "def hi():\n    return 'ok'\n"})
        s_dir = Path(_kv(_run_cli(["init", "--root", str(repo), "--skills-dir", str(self.skills_dir)]).stdout)["S"])
        # Simulate stray __pycache__ created on host during testing
        stray_cache = repo / "__pycache__"
        stray_cache.mkdir()
        (stray_cache / "app.cpython-312.pyc").write_bytes(b"pyc")
        fin = _run_cli(["finalize", "--s", str(s_dir), "--clean"])
        self.assertIn("CLEAN (0 stray files outside .bughunt/)", fin.stdout)
        self.assertFalse(stray_cache.exists())
        self.assertFalse((s_dir / "overlay").exists())
        self.assertFalse((s_dir / "baseline").exists())
        self.assertFalse((s_dir / "checkpoints").exists())

    def test_11_offline_install_all_6_platforms_and_doctor(self) -> None:
        dest = self.tmp / "installed_all"
        p_inst = _run_cli([
            "install", "--platform", "all",
            "--target-dir", str(dest),
            "--offline-from", str(self.skills_dir),
        ])
        self.assertIn("INSTALL_STATUS=OK", p_inst.stdout)
        for plat in ("claude", "antigravity", "cursor", "windsurf", "roocode", "cline"):
            for sk in ("veripilot", "veripr", "verihunt", "verisec", "veriperf"):
                self.assertTrue((dest / plat / sk / "SKILL.md").is_file(), f"Missing {plat}/{sk}")

        p_doc_ok = _run_cli(["doctor", "--root", str(self.tmp), "--skills-dir", str(dest / "claude")])
        self.assertIn("DOCTOR_STATUS=HEALTHY", p_doc_ok.stdout)

        # Missing skill should make doctor report DEGRADED with install remedy
        partial_dir = _build_stub_skills(self.tmp / "partial_skills", skip={"verisec"})
        p_doc_bad = _run_cli(
            ["doctor", "--root", str(self.tmp), "--skills-dir", str(partial_dir)],
            check=False,
        )
        self.assertEqual(p_doc_bad.returncode, 1)
        self.assertIn("DOCTOR_STATUS=DEGRADED", p_doc_bad.stdout)
        self.assertIn("SKILL_VERISEC=MISSING", p_doc_bad.stdout)

        # Verify --latest resolves highest semver tag (v1.10.0 > v1.2.0 > v1.0.0) via local Git bare repo
        src_repo = self.tmp / "src_veripr"
        _init_git_repo(src_repo, {"SKILL.md": "# v1.0.0\n", "scripts/vpr.py": "print('1.0.0')\n"})
        _run_git(src_repo, ["tag", "v1.0.0"])
        (src_repo / "SKILL.md").write_text("# v1.2.0\n", encoding="utf-8")
        _run_git(src_repo, ["add", "."])
        _run_git(src_repo, ["commit", "-m", "v1.2.0"])
        _run_git(src_repo, ["tag", "v1.2.0"])
        (src_repo / "SKILL.md").write_text("# v1.10.0\n", encoding="utf-8")
        _run_git(src_repo, ["add", "."])
        _run_git(src_repo, ["commit", "-m", "v1.10.0"])
        _run_git(src_repo, ["tag", "v1.10.0"])

        latest_dest = self.tmp / "latest_install"
        p_latest = _run_cli([
            "install", "--platform", "antigravity",
            "--target-dir", str(latest_dest),
            "--skills", "veripr",
            "--latest",
            "--repo-override", f"veripr={src_repo.as_uri()}",
        ])
        self.assertIn("VERSION_POLICY=LATEST", p_latest.stdout)
        self.assertIn("veripr@v1.10.0", p_latest.stdout)
        self.assertIn("# v1.10.0", (latest_dest / "veripr" / "SKILL.md").read_text(encoding="utf-8"))

    def test_12_stdout_12_line_cap_and_skill_md_budget(self) -> None:
        skill_lines = SKILL_MD.read_text(encoding="utf-8").splitlines()
        self.assertLessEqual(len(skill_lines), 120, f"SKILL.md has {len(skill_lines)} lines (>120)")

        repo = self.tmp / "repo12"
        _init_git_repo(repo, {"a.py": "x = 1\n"})
        init_p = _run_cli(["init", "--root", str(repo), "--skills-dir", str(self.skills_dir)])
        s_dir = Path(_kv(init_p.stdout)["S"])
        cmds = [
            init_p,
            _run_cli(["doctor", "--root", str(repo), "--skills-dir", str(self.skills_dir)]),
            _run_cli(["route", "--root", str(repo), "--s", str(s_dir), "--skills-dir", str(self.skills_dir), "--prompt", "check pr, sec, perf, bug"]),
            _run_cli(["log", "--s", str(s_dir), "--status", "Testing", "--entry", "Line check"]),
            _run_cli(["handoff", "--s", str(s_dir), "--skill", "veripr"]),
            _run_cli(["finalize", "--s", str(s_dir), "--clean"]),
            _run_cli(["install", "--platform", "all", "--target-dir", str(self.tmp / "inst12"), "--offline-from", str(self.skills_dir)]),
        ]
        for proc in cmds:
            out_lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
            self.assertLessEqual(len(out_lines), 12, f"Exceeded 12-line cap ({len(out_lines)}):\n{proc.stdout}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
