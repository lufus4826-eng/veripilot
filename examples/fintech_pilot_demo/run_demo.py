#!/usr/bin/env python3
"""One-command E2E live showcase for VeriPilot (PILOT-1 through PILOT-4).

Demonstrates:
  PILOT-1: Broad Thai pre-submit prompt on payment+receipt branch -> auto-routes veripr -> verisec
           via 3-layer triage + exports single conflict-free LF patch.
  PILOT-2: Mixed prompt ("จูนความเร็ว เช็กช่องโหว่ และตรวจ PR") -> enforces Causal Order
           veripr -> verisec -> veriperf over cumulative S/overlay/ + unified patch.
  PILOT-3: Broken test harness in Stage 1 -> Circuit Breaker trips immediately (HARNESS_BROKEN)
           without burning tokens on downstream stages.
  PILOT-4: Offline 6-platform suite install (Claude, Antigravity, Cursor, Windsurf, Roo Code, Cline)
           + cross-platform `vpilot.py doctor` health check.
"""

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
import textwrap
import time


DEMO_DIR = Path(__file__).resolve().parent
SKILL_ROOT = DEMO_DIR.parents[1]
VPILOT_PY = SKILL_ROOT / "scripts" / "vpilot.py"
SAMPLE_REPORT_PATH = DEMO_DIR / "sample-pilot-report.md"


def _run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"Command failed ({proc.returncode}): {' '.join(cmd)}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc


def _kv_parse(stdout: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    key_re = re.compile(r"(?:^|\s)([A-Z][A-Z0-9_]*)=")
    for line in stdout.splitlines():
        matches = list(key_re.finditer(line))
        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(line)
            parsed[m.group(1)] = line[m.end() : end].strip()
    return parsed


def _make_patch(rel_path: str, old_text: str, new_text: str) -> str:
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    diff = "".join(difflib.unified_diff(old_lines, new_lines, fromfile=f"a/{rel_path}", tofile=f"b/{rel_path}", n=3))
    return f"diff --git a/{rel_path} b/{rel_path}\n{diff}"


def _init_fintech_repo(repo_dir: Path, broken_harness: bool = False) -> None:
    repo_dir.mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "-b", "main"], cwd=repo_dir)
    _run(["git", "config", "user.name", "VeriPilot Demo"], cwd=repo_dir)
    _run(["git", "config", "user.email", "demo@verihunt.local"], cwd=repo_dir)

    (repo_dir / "app").mkdir(parents=True, exist_ok=True)
    (repo_dir / "tests").mkdir(parents=True, exist_ok=True)

    payment_base = textwrap.dedent(
        '''\
        """Fintech payment & ledger service."""


        def calculate_fee(amount_cents: int, tier: str = "STD") -> float:
            if tier == "VIP":
                return round(amount_cents * 0.005, 2)
            return round(amount_cents * 0.02, 2)


        def refund_payment(records: dict, payment_id: str, requester_id: str) -> dict:
            rec = records[payment_id]
            if rec["owner_id"] != requester_id:
                raise PermissionError("Unauthorized refund")
            rec["refunded"] = True
            return rec


        def reconcile_ledger_batch(tx_ids: list[str], settled_ids: list[str]) -> list[str]:
            settled = set(settled_ids)
            return [tx for tx in tx_ids if tx not in settled]
        '''
    )
    receipt_base = textwrap.dedent(
        '''\
        """Receipt builder caller (1-hop caller of calculate_fee)."""

        from app.payment_service import calculate_fee


        def build_receipt(amount_cents: int, tier: str = "STD") -> dict:
            fee = calculate_fee(amount_cents, tier)
            net_cents = round(amount_cents - fee, 2)
            return {"amount_cents": amount_cents, "fee": fee, "net_cents": net_cents}
        '''
    )
    test_base = textwrap.dedent(
        '''\
        import unittest
        from app.payment_service import calculate_fee, refund_payment, reconcile_ledger_batch
        from app.receipt_api import build_receipt


        class FintechSuiteTest(unittest.TestCase):
            def test_receipt_std(self):
                res = build_receipt(1000, "STD")
                self.assertEqual(res["net_cents"], 980.0)

            def test_refund_idor_blocked(self):
                records = {"p1": {"owner_id": "alice", "refunded": False}}
                with self.assertRaises(PermissionError):
                    refund_payment(records, "p1", "bob")

            def test_reconcile_missing(self):
                self.assertEqual(reconcile_ledger_batch(["t1", "t2", "t3"], ["t2"]), ["t1", "t3"])


        if __name__ == "__main__":
            unittest.main()
        '''
    )
    (repo_dir / "app" / "__init__.py").write_text("", encoding="utf-8")
    (repo_dir / "app" / "payment_service.py").write_text(payment_base, encoding="utf-8")
    (repo_dir / "app" / "receipt_api.py").write_text(receipt_base, encoding="utf-8")
    (repo_dir / "tests" / "test_fintech.py").write_text(test_base, encoding="utf-8")
    _run(["git", "add", "."], cwd=repo_dir)
    _run(["git", "commit", "-m", "chore: baseline fintech payment service"], cwd=repo_dir)

    # Feature branch introducing: 1-hop None ripple + IDOR missing guard + O(N^2) regression
    _run(["git", "checkout", "-b", "feat/express-refund"], cwd=repo_dir)
    payment_head = textwrap.dedent(
        '''\
        """Fintech payment & ledger service."""


        def calculate_fee(amount_cents: int, tier: str = "STD") -> float:
            if tier == "FREE_PROMO":
                return None  # BUG (PR ripple): breaks arithmetic in build_receipt
            if tier == "VIP":
                return round(amount_cents * 0.005, 2)
            return round(amount_cents * 0.02, 2)


        def refund_payment(records: dict, payment_id: str, requester_id: str) -> dict:
            rec = records[payment_id]
            # BUG (IDOR): removed owner_id != requester_id check
            rec["refunded"] = True
            return rec


        def reconcile_ledger_batch(tx_ids: list[str], settled_ids: list[str]) -> list[str]:
            # BUG (Perf O(N^2)): linear scan on settled_ids per transaction
            missing = []
            for tx in tx_ids:
                found = False
                for s in settled_ids:
                    if tx == s:
                        found = True
                        break
                if not found:
                    missing.append(tx)
            return missing
        '''
    )
    receipt_head = textwrap.dedent(
        '''\
        """Receipt builder caller (1-hop caller of calculate_fee)."""

        from app.payment_service import calculate_fee


        def build_receipt(amount_cents: int, tier: str = "STD") -> dict:
            fee = calculate_fee(amount_cents, tier)
            net_cents = round(amount_cents - fee, 2)
            return {"amount_cents": amount_cents, "fee": fee, "net_cents": net_cents, "tier": tier}
        '''
    )
    (repo_dir / "app" / "payment_service.py").write_text(payment_head, encoding="utf-8")
    (repo_dir / "app" / "receipt_api.py").write_text(receipt_head, encoding="utf-8")
    if broken_harness:
        (repo_dir / "tests" / "test_broken_syntax.py").write_text("def broken(:\n    pass\n", encoding="utf-8")
    _run(["git", "add", "."], cwd=repo_dir)
    _run(["git", "commit", "-m", "feat: add free promo fee tier and express refund"], cwd=repo_dir)


def _create_skill_bundle_for_ci(bundle_root: Path) -> Path:
    """Create complete 5-skill bundle using local sibling skills when installed, or valid stubs in CI."""
    bundle_root.mkdir(parents=True, exist_ok=True)
    _copy_target = bundle_root / "veripilot"
    shutil.copytree(
        SKILL_ROOT,
        _copy_target,
        ignore=shutil.ignore_patterns(".git", ".bughunt", "__pycache__", ".pytest_cache"),
    )
    real_parent = SKILL_ROOT.parent
    siblings = {
        "veripr": ("scripts/vpr.py", "VeriPR"),
        "verihunt": ("scripts/bh.py", "VeriHunt"),
        "verisec": ("scripts/vs.py", "VeriSec"),
        "veriperf": ("scripts/vp.py", "VeriPerf"),
    }
    for name, (cli_rel, title) in siblings.items():
        real_dir = real_parent / name
        dst = bundle_root / name
        if (real_dir / "SKILL.md").is_file() and (real_dir / cli_rel).is_file():
            shutil.copytree(
                real_dir,
                dst,
                ignore=shutil.ignore_patterns(".git", ".bughunt", "__pycache__", ".pytest_cache"),
            )
        else:
            (dst / "scripts").mkdir(parents=True, exist_ok=True)
            (dst / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {title}\n---\n# {title}\n", encoding="utf-8")
            (dst / cli_rel).write_text(f'"""{title} CLI placeholder for standalone CI."""\nprint("{name} OK")\n', encoding="utf-8")
    return bundle_root


def run_all_pilots() -> dict[str, dict[str, str]]:
    results: dict[str, dict[str, str]] = {}
    with tempfile.TemporaryDirectory(prefix="veripilot_demo_") as tmp:
        tmp_path = Path(tmp)
        skills_bundle = _create_skill_bundle_for_ci(tmp_path / "bundle_skills")

        # ------------------------------------------------------------------
        # PILOT-1: Broad Thai pre-submit prompt -> veripr -> verisec
        # ------------------------------------------------------------------
        repo1 = tmp_path / "repo_pilot1"
        _init_fintech_repo(repo1)
        p1_init = _run([sys.executable, "-B", str(VPILOT_PY), "init", "--root", str(repo1), "--skills-dir", str(skills_bundle)])
        assert len(p1_init.stdout.strip().splitlines()) <= 12
        s1 = Path(_kv_parse(p1_init.stdout)["S"])

        p1_route = _run(
            [
                sys.executable, "-B", str(VPILOT_PY), "route",
                "--root", str(repo1), "--s", str(s1),
                "--skills-dir", str(skills_bundle),
                "--prompt", "ช่วยเช็กโค้ดก่อนส่งให้หน่อย เพิ่งแก้ระบบชำระเงินกับใบเสร็จไป",
            ]
        )
        assert len(p1_route.stdout.strip().splitlines()) <= 12
        kv1_r = _kv_parse(p1_route.stdout)
        assert kv1_r["PLAN"] == "veripr -> verisec", f"Expected veripr -> verisec, got {kv1_r}"
        assert "HIGH" in kv1_r["SEC_RISK"]

        overlay1 = s1 / "overlay"
        pay_file1 = overlay1 / "app" / "payment_service.py"
        orig_text1 = pay_file1.read_text(encoding="utf-8")

        # Stage 1 (veripr): fix FREE_PROMO None ripple while preserving FREE_PROMO tier
        after_pr1 = orig_text1.replace(
            "return None  # BUG (PR ripple): breaks arithmetic in build_receipt",
            "return 0.0  # Fixed PR ripple: numeric fee keeps FREE_PROMO free",
        )
        patch_pr1 = s1 / "tmp" / "pr1.patch"
        patch_pr1.write_text(_make_patch("app/payment_service.py", orig_text1, after_pr1), encoding="utf-8")
        p1_h1 = _run(
            [
                sys.executable, "-B", str(VPILOT_PY), "handoff",
                "--s", str(s1), "--skill", "veripr", "--patch", str(patch_pr1),
                "--status", "PASS", "--findings", "1", "--tests-ran", "4",
                "--summary", "Fixed calculate_fee None return ripple in build_receipt",
            ]
        )
        assert _kv_parse(p1_h1.stdout)["NEXT_SKILL"] == "verisec"

        # Confirm overlay now has Stage 1 fix before Stage 2 runs
        assert "return 0.0" in pay_file1.read_text(encoding="utf-8")

        # Stage 2 (verisec): fix IDOR on top of Stage 1 fix inside S/overlay/
        overlay_after_s1 = pay_file1.read_text(encoding="utf-8")
        after_sec1 = overlay_after_s1.replace(
            '    # BUG (IDOR): removed owner_id != requester_id check',
            '    if rec["owner_id"] != requester_id:\n        raise PermissionError("Unauthorized refund")',
        )
        assert after_sec1 != overlay_after_s1, "IDOR replacement did not match"
        patch_sec1 = s1 / "tmp" / "sec1.patch"
        patch_sec1.write_text(_make_patch("app/payment_service.py", overlay_after_s1, after_sec1), encoding="utf-8")
        _run(
            [
                sys.executable, "-B", str(VPILOT_PY), "handoff",
                "--s", str(s1), "--skill", "verisec", "--patch", str(patch_sec1),
                "--status", "PASS", "--findings", "1", "--tests-ran", "3",
                "--summary", "Restored owner_id != requester_id check in refund_payment",
            ]
        )

        p1_fin = _run(
            [
                sys.executable, "-B", str(VPILOT_PY), "finalize",
                "--s", str(s1), "--clean",
                "--verify-cmd", f"{sys.executable} -B -m unittest discover -s tests",
            ]
        )
        kv1_f = _kv_parse(p1_fin.stdout)
        unified1 = Path(kv1_f["UNIFIED_PATCH"])
        assert "GIT_APPLY=OK" in p1_fin.stdout
        assert "PURE_LF=True" in p1_fin.stdout
        assert "VERIFY_CMD=PASS" in p1_fin.stdout
        assert "CLEAN" in kv1_f["CLEANLINESS"]
        assert b"\r" not in unified1.read_bytes()
        results["PILOT-1"] = {
            "plan": kv1_r["PLAN"],
            "sec_risk": kv1_r["SEC_RISK"].split()[0],
            "git_apply": "OK",
            "verify": "PASS",
            "cleanliness": kv1_f["CLEANLINESS"],
            "patch_bytes": str(unified1.stat().st_size),
        }

        # ------------------------------------------------------------------
        # PILOT-2: Mixed prompt -> Causal reordering veripr -> verisec -> veriperf
        # ------------------------------------------------------------------
        repo2 = tmp_path / "repo_pilot2"
        _init_fintech_repo(repo2)
        p2_init = _run([sys.executable, "-B", str(VPILOT_PY), "init", "--root", str(repo2), "--skills-dir", str(skills_bundle)])
        s2 = Path(_kv_parse(p2_init.stdout)["S"])

        p2_route = _run(
            [
                sys.executable, "-B", str(VPILOT_PY), "route",
                "--root", str(repo2), "--s", str(s2),
                "--skills-dir", str(skills_bundle),
                "--prompt", "อยากจูนความเร็ว เช็กช่องโหว่ และตรวจ PR ในประโยคเดียว",
            ]
        )
        kv2_r = _kv_parse(p2_route.stdout)
        assert kv2_r["PLAN"] == "veripr -> verisec -> veriperf", f"Unexpected plan: {kv2_r}"
        assert "REORDERED=True" in p2_route.stdout

        overlay2 = s2 / "overlay"
        pay_file2 = overlay2 / "app" / "payment_service.py"
        txt0 = pay_file2.read_text(encoding="utf-8")

        # Stage 1: veripr
        txt1 = txt0.replace(
            "return None  # BUG (PR ripple): breaks arithmetic in build_receipt",
            "return 0.0  # Fixed PR ripple: numeric fee keeps FREE_PROMO free",
        )
        (s2 / "tmp" / "s1.patch").write_text(_make_patch("app/payment_service.py", txt0, txt1), encoding="utf-8")
        _run(
            [
                sys.executable, "-B", str(VPILOT_PY), "handoff",
                "--s", str(s2), "--skill", "veripr", "--patch", str(s2 / "tmp" / "s1.patch"),
                "--status", "PASS", "--findings", "1", "--tests-ran", "4",
                "--summary", "Fixed FREE_PROMO None return ripple",
            ]
        )

        # Stage 2: verisec
        txt2 = pay_file2.read_text(encoding="utf-8").replace(
            '    # BUG (IDOR): removed owner_id != requester_id check',
            '    if rec["owner_id"] != requester_id:\n        raise PermissionError("Unauthorized refund")',
        )
        assert txt2 != txt1, "IDOR replacement did not match in PILOT-2"
        (s2 / "tmp" / "s2.patch").write_text(_make_patch("app/payment_service.py", txt1, txt2), encoding="utf-8")
        h2 = _run(
            [
                sys.executable, "-B", str(VPILOT_PY), "handoff",
                "--s", str(s2), "--skill", "verisec", "--patch", str(s2 / "tmp" / "s2.patch"),
                "--status", "PASS", "--findings", "1", "--tests-ran", "3",
                "--summary", "Restored IDOR owner check",
            ]
        )
        assert _kv_parse(h2.stdout)["NEXT_SKILL"] == "veriperf"

        # Stage 3: veriperf (benchmark O(N^2) vs O(N) set lookup directly in overlay)
        t_before_start = time.perf_counter()
        sys.path.insert(0, str(overlay2))
        import importlib
        import app.payment_service as ps_mod
        importlib.reload(ps_mod)
        tx_ids = [f"tx-{i}" for i in range(4000)]
        settled = [f"tx-{i}" for i in range(0, 4000, 2)]
        res_before = ps_mod.reconcile_ledger_batch(tx_ids, settled)
        t_before = time.perf_counter() - t_before_start

        old_perf_block = textwrap.dedent(
            '''\
            def reconcile_ledger_batch(tx_ids: list[str], settled_ids: list[str]) -> list[str]:
                # BUG (Perf O(N^2)): linear scan on settled_ids per transaction
                missing = []
                for tx in tx_ids:
                    found = False
                    for s in settled_ids:
                        if tx == s:
                            found = True
                            break
                    if not found:
                        missing.append(tx)
                return missing'''
        )
        new_perf_block = textwrap.dedent(
            '''\
            def reconcile_ledger_batch(tx_ids: list[str], settled_ids: list[str]) -> list[str]:
                settled = set(settled_ids)
                return [tx for tx in tx_ids if tx not in settled]'''
        )
        txt3 = pay_file2.read_text(encoding="utf-8").replace(old_perf_block, new_perf_block)
        assert txt3 != txt2, "Perf replacement did not match in PILOT-2"
        (s2 / "tmp" / "s3.patch").write_text(_make_patch("app/payment_service.py", txt2, txt3), encoding="utf-8")
        _run(
            [
                sys.executable, "-B", str(VPILOT_PY), "handoff",
                "--s", str(s2), "--skill", "veriperf", "--patch", str(s2 / "tmp" / "s3.patch"),
                "--status", "PASS", "--findings", "1", "--tests-ran", "20",
                "--summary", "Replaced O(N^2) ledger scan with O(N) set lookup",
            ]
        )

        importlib.reload(ps_mod)
        t_after_start = time.perf_counter()
        res_after = ps_mod.reconcile_ledger_batch(tx_ids, settled)
        t_after = max(time.perf_counter() - t_after_start, 1e-6)
        assert res_before == res_after
        sys.path.remove(str(overlay2))
        speedup = round(((t_before - t_after) / max(t_before, 1e-6)) * 100.0, 1)

        p2_fin = _run(
            [
                sys.executable, "-B", str(VPILOT_PY), "finalize",
                "--s", str(s2), "--clean",
                "--verify-cmd", f"{sys.executable} -B -m unittest discover -s tests",
            ]
        )
        kv2_f = _kv_parse(p2_fin.stdout)
        unified2 = Path(kv2_f["UNIFIED_PATCH"])
        assert "GIT_APPLY=OK" in p2_fin.stdout
        assert "PURE_LF=True" in p2_fin.stdout
        # Actually apply the unified 3-stage patch onto repo2 to prove zero conflicts
        _run(["git", "apply", "--ignore-space-change", "--ignore-whitespace", str(unified2)], cwd=repo2)
        _run([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests"], cwd=repo2)

        results["PILOT-2"] = {
            "requested": "veriperf,verisec,veripr",
            "plan": kv2_r["PLAN"],
            "reordered": "True",
            "speedup": f"+{speedup}%",
            "git_apply": "OK (3-stage patch cleanly applied & tested)",
            "cleanliness": kv2_f["CLEANLINESS"],
        }

        # ------------------------------------------------------------------
        # PILOT-3: Circuit Breaker trips on broken test harness
        # ------------------------------------------------------------------
        repo3 = tmp_path / "repo_pilot3"
        _init_fintech_repo(repo3, broken_harness=True)
        p3_init = _run([sys.executable, "-B", str(VPILOT_PY), "init", "--root", str(repo3), "--skills-dir", str(skills_bundle)])
        s3 = Path(_kv_parse(p3_init.stdout)["S"])
        _run(
            [
                sys.executable, "-B", str(VPILOT_PY), "route",
                "--root", str(repo3), "--s", str(s3),
                "--skills-dir", str(skills_bundle),
                "--prompt", "ตรวจ PR, เช็กช่องโหว่, และจูนความเร็ว",
            ]
        )
        p3_hand = _run(
            [
                sys.executable, "-B", str(VPILOT_PY), "handoff",
                "--s", str(s3), "--skill", "veripr",
                "--check-cmd", f"{sys.executable} -B -m unittest discover -s tests",
            ]
        )
        kv3_h = _kv_parse(p3_hand.stdout)
        assert "CIRCUIT_BREAKER=TRIPPED" in p3_hand.stdout
        assert kv3_h["REASON"] == "HARNESS_BROKEN"
        assert kv3_h["NEXT_SKILL"] == "NONE"

        p3_fin = _run([sys.executable, "-B", str(VPILOT_PY), "finalize", "--s", str(s3), "--clean"])
        assert "FINALIZE_STATUS=HALTED" in p3_fin.stdout
        assert "CIRCUIT_BREAKER=TRIPPED" in p3_fin.stdout
        results["PILOT-3"] = {
            "circuit_breaker": "TRIPPED",
            "reason": kv3_h["REASON"],
            "next_skill": kv3_h["NEXT_SKILL"],
            "status": "HALTED_BEFORE_STAGE_2",
        }

        # ------------------------------------------------------------------
        # PILOT-4: Offline 6-platform install + doctor verification
        # ------------------------------------------------------------------
        install_root = tmp_path / "multi_platform_home"
        p4_inst = _run(
            [
                sys.executable, "-B", str(VPILOT_PY), "install",
                "--platform", "all",
                "--target-dir", str(install_root),
                "--offline-from", str(skills_bundle),
            ]
        )
        assert "INSTALL_STATUS=OK" in p4_inst.stdout
        assert "MODE=OFFLINE" in p4_inst.stdout
        platforms = ("claude", "antigravity", "cursor", "windsurf", "roocode", "cline")
        for plat in platforms:
            for sk in ("veripilot", "veripr", "verihunt", "verisec", "veriperf"):
                assert (install_root / plat / sk / "SKILL.md").is_file(), f"Missing {plat}/{sk}"

        p4_doc = _run(
            [
                sys.executable, "-B", str(VPILOT_PY), "doctor",
                "--root", str(repo1),
                "--skills-dir", str(install_root / "antigravity"),
            ]
        )
        assert "DOCTOR_STATUS=HEALTHY" in p4_doc.stdout
        assert len(p4_doc.stdout.strip().splitlines()) <= 12
        results["PILOT-4"] = {
            "install_status": "OK",
            "platforms": "6/6 (claude, antigravity, cursor, windsurf, roocode, cline)",
            "skills_per_platform": "5/5",
            "doctor_status": "HEALTHY",
        }

    # Write showcase sample-pilot-report.md (EN + TH bilingual executive showcase)
    report = f"""# VeriPilot Live Showcase Report (`examples/fintech_pilot_demo`)

> Generated cleanly by `python -B examples/fintech_pilot_demo/run_demo.py` across all 4 required orchestration scenarios (`PILOT-1`..`PILOT-4`).

## 1. Executive Summary Matrix (EN / TH)

| Case ID | Scenario | Observed Routing / Action | Empirical Outcome |
|---|---|---|---|
| **PILOT-1** | Broad TH pre-submit prompt on payment + receipt diff (`ช่วยเช็กโค้ดก่อนส่งให้หน่อย เพิ่งแก้ระบบชำระเงินกับใบเสร็จไป`) | `3-Layer Triage`: `SEC_RISK=HIGH` -> `{results['PILOT-1']['plan']}` | Unified patch `{results['PILOT-1']['patch_bytes']}`B, `GIT_APPLY={results['PILOT-1']['git_apply']}`, `VERIFY={results['PILOT-1']['verify']}`, `{results['PILOT-1']['cleanliness']}` |
| **PILOT-2** | Mixed causal-order prompt (`อยากจูนความเร็ว เช็กช่องโหว่ และตรวจ PR ในประโยคเดียว`) | Requested `{results['PILOT-2']['requested']}` -> Reordered `{results['PILOT-2']['plan']}` (`reordered={results['PILOT-2']['reordered']}`) | 3 cumulative fixes in `S/overlay/` (`{results['PILOT-2']['speedup']}` batch speedup), `{results['PILOT-2']['git_apply']}` |
| **PILOT-3** | Broken test syntax in Stage 1 (`test_broken_syntax.py`) | `handoff --check-cmd` detected `SyntaxError` | `CIRCUIT_BREAKER={results['PILOT-3']['circuit_breaker']}` (`REASON={results['PILOT-3']['reason']}`), `NEXT_SKILL={results['PILOT-3']['next_skill']}` |
| **PILOT-4** | Offline 6-platform install + `doctor` health check | `install --platform all --offline-from` + `doctor` | `INSTALL={results['PILOT-4']['install_status']}` ({results['PILOT-4']['platforms']}), `DOCTOR={results['PILOT-4']['doctor_status']}` |

---

## 2. สรุปผลการสาธิตทั้ง 4 สถานการณ์ (ฉบับภาษาไทย)

1. **`PILOT-1` (Auto-Triage จากสถานะ Git + ความเสี่ยงไฟล์):** ผู้ใช้พิมพ์คำสั่งกว้างๆ ว่าจะเช็กโค้ดก่อนส่งบนสาขาที่แตะ `payment_service.py` และ `receipt_api.py` เอนจินตรวจพบความเสี่ยงด้านสิทธิ์/การเงิน (`SEC_RISK=HIGH`) จึงจัดแผน **`{results['PILOT-1']['plan']}`** อัตโนมัติ แก้ทั้งบัคลูกโซ่ `None` ใน `calculate_fee` และช่องโหว่ IDOR ใน `refund_payment` ซ้อนทับกันจนออกเป็นแพตช์ LF ล้วนแผ่นเดียวที่ `git apply --check -> OK`
2. **`PILOT-2` (Causal Execution Order + Cumulative Overlay):** แม้ผู้ใช้จะขอจูนความเร็วก่อนเช็กช่องโหว่และตรวจ PR เอนจินบังคับจัดเรียงใหม่เป็น **`{results['PILOT-2']['plan']}`** (`REORDERED=True`) ทำให้ด่าน `verisec` ทำงานต่อบนโค้ดที่แก้ ripple แล้ว และด่าน `veriperf` จูน `reconcile_ledger_batch` (`O(N^2)` -> `O(N)`, เร็วขึ้น `{results['PILOT-2']['speedup']}`) ทับบนโค้ดที่มีตัวเช็กสิทธิ์ IDOR แล้วอย่างสมบูรณ์
3. **`PILOT-3` (Circuit Breaker ตัดวงจรเมื่อ Harness พัง):** เมื่อด่านแรกเจอ `SyntaxError` ในไฟล์เทสต์ ตัวตัดวงจรสั่งหยุดทันที (`CIRCUIT_BREAKER=TRIPPED`, `REASON=HARNESS_BROKEN`, `NEXT_SKILL=NONE`) ป้องกันการเผา Token ข้ามไปด่านที่ 2 และ 3
4. **`PILOT-4` (One-Command Suite Installer & Doctor):** ทดสอบติดตั้งทั้ง 5 สกิลแบบออฟไลน์ลงครบทั้ง **6 แพลตฟอร์ม** (`claude`, `antigravity`, `cursor`, `windsurf`, `roocode`, `cline`) พร้อมตรวจด้วย `vpilot.py doctor` ได้สถานะ **`HEALTHY`** ครบทุกตัว
"""
    SAMPLE_REPORT_PATH.write_text(report, encoding="utf-8")

    print("VERIPILOT_DEMO_STATUS=ALL_4_CASES_PASSED")
    for cid, info in results.items():
        print(f"{cid}: " + " ".join(f"{k}={v}" for k, v in info.items()))
    print(f"REPORT={SAMPLE_REPORT_PATH}")
    return results


if __name__ == "__main__":
    run_all_pilots()
