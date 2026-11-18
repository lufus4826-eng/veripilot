#!/usr/bin/env python3
"""Deterministic Smart Router, Cumulative Overlay Orchestrator & Suite Installer for VeriPilot (stdlib only).

Subcommands (every command strictly emits <= 12 stdout lines):
  init      Create .bughunt/pilot-<ts>/ session, update .git/info/exclude, discover suite skills, prep overlay
  route     Run 3-layer triage (TH/EN intent + Git state + touched file risk) and enforce Causal Order
  handoff   Verify Circuit Breaker, apply stage patch/edits onto S/overlay/, checkpoint, return next skill
  finalize  Export pure-LF veripilot-unified.patch, verify git apply --check, clean temps, summarize
  install   Install or update all 5 VeriHunt suite skills across 6 agent platforms (online or offline)
  doctor    Verify Python, Git, all 5 suite skill engines, .git/info/exclude, and .bughunt/ temp health
  log       Atomically update Status and append timestamped entry to S/worklog.md
"""

from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import difflib
import gc
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple


if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


VPILOT_VERSION = "1.0.0"

SUITE_REGISTRY: Dict[str, Dict[str, str]] = {
    "veripilot": {
        "repo": "https://github.com/lufus4826-eng/veripilot.git",
        "tag": "v1.0.0",
        "cli": "scripts/vpilot.py",
        "role": "orchestrator",
    },
    "veripr": {
        "repo": "https://github.com/lufus4826-eng/veripr.git",
        "tag": "v1.1.0",
        "cli": "scripts/vpr.py",
        "role": "correctness_pr",
    },
    "verihunt": {
        "repo": "https://github.com/lufus4826-eng/verihunt.git",
        "tag": "v2.1.0",
        "cli": "scripts/bh.py",
        "role": "correctness_hunt",
    },
    "verisec": {
        "repo": "https://github.com/lufus4826-eng/verisec.git",
        "tag": "v1.1.0",
        "cli": "scripts/vs.py",
        "role": "security",
    },
    "veriperf": {
        "repo": "https://github.com/lufus4826-eng/veriperf.git",
        "tag": "v1.1.1",
        "cli": "scripts/vp.py",
        "role": "performance",
    },
}

CAUSAL_PRIORITY: Dict[str, int] = {
    "veripr": 1,
    "verihunt": 2,
    "verisec": 3,
    "veriperf": 4,
}

ALL_PLATFORMS = ("claude", "antigravity", "cursor", "windsurf", "roocode", "cline")
PLATFORM_ALIASES = {"gemini": "antigravity", "gemini-cli": "antigravity", "roo": "roocode"}

EXCLUDE_DIRS = frozenset(
    {
        ".git",
        ".bughunt",
        "node_modules",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        ".nox",
        ".vs",
        ".idea",
        ".gradle",
        "TestResults",
    }
)

SNAPSHOT_SKIP_DIRS = frozenset({".bughunt", ".git", "node_modules"})

BINARY_EXTS = frozenset(
    {
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".tar",
        ".gz", ".bz2", ".xz", ".7z", ".whl", ".exe", ".dll", ".so", ".dylib",
        ".class", ".jar", ".pyc", ".pyo", ".o", ".a", ".wasm", ".ttf", ".woff",
        ".woff2", ".db", ".sqlite", ".sqlite3",
    }
)

_TRUNK_BRANCH_NAMES = frozenset({"main", "master", "develop", "trunk", "HEAD", ""})
_TRUNK_CANDIDATES = ("main", "master", "origin/main", "origin/master", "develop", "origin/develop")

# Layer 1 Bilingual Intent Triggers
INTENT_PATTERNS: Dict[str, Tuple[Sequence[str], Sequence[str]]] = {
    "veripr": (
        (
            r"\bpr\b", r"\bpre[- ]commit\b", r"\bcommit\b", r"\bdiff\b", r"\bripple\b",
            r"\bcontract\b", r"\bschema\b", r"\bcaller\b", r"\bpull request\b",
        ),
        (
            "รีวิว", "พร้อมส่ง", "กระทบ", "ก่อนส่ง", "ก่อนคอมมิต", "ลูกโซ่",
            "เช็กโค้ดก่อนส่ง", "ตรวจโค้ดก่อนส่ง", "ส่งงาน", "เช็กก่อนส่ง", "ตรวจ diff",
        ),
    ),
    "verihunt": (
        (
            r"\bbug\b", r"\bbugs\b", r"\bhunt\b", r"\bcrash\b", r"\bstability\b",
            r"\bedge[- ]case\b", r"\bqa\b", r"\bexception\b", r"\brace\b", r"\baudit\b",
        ),
        ("หาบัค", "ไล่บัค", "พัง", "รวน", "เสถียร", "จับผิด", "บัค", "ตรวจบัค", "แก้บัค"),
    ),
    "verisec": (
        (
            r"\bsec\b", r"\bsecurity\b", r"\bidor\b", r"\bbola\b", r"\bauth\b",
            r"\bauthorization\b", r"\bauthz\b", r"\bvulnerability\b", r"\bvuln\b",
            r"\bmass[- ]assignment\b", r"\bdouble[- ]spend\b", r"\bbypass\b", r"\bexploit\b",
        ),
        ("ช่องโหว่", "สิทธิ์รั่ว", "ข้ามสิทธิ์", "ความปลอดภัย", "หลุดสิทธิ์", "เช็กสิทธิ์", "ตรวจสิทธิ์", "แฮก"),
    ),
    "veriperf": (
        (
            r"\bperf\b", r"\bperformance\b", r"\blatency\b", r"\boptimize\b",
            r"\bspeed\b", r"\bslow\b", r"\bmemory\b", r"\bbottleneck\b",
            r"\bn\+1\b", r"\bbenchmark\b", r"\bprofile\b", r"\bspeedup\b",
        ),
        ("ช้า", "อืด", "กินแรม", "จูนความเร็ว", "ความเร็ว", "ประสิทธิภาพ", "คอขวด", "เร็วขึ้น", "ลดแรม"),
    ),
}

BROAD_REVIEW_HINTS = (
    "เช็กโค้ด", "ตรวจโค้ด", "เช็กงาน", "ตรวจงาน", "check code", "review code", "check my changes",
)

# Layer 3 Security-sensitive path and code risk signals
SEC_PATH_KEYWORDS = (
    "payment", "pay", "auth", "login", "token", "jwt", "session", "receipt",
    "invoice", "vault", "wallet", "account", "user", "role", "perm",
    "permission", "admin", "checkout", "refund", "transfer", "billing", "order",
)
SEC_CODE_PATTERN = re.compile(
    r"\b(requester_id|owner_id|user_id|account_id|is_admin|authorize|permission|"
    r"refund|transfer|withdraw|verify_token|jwt|secret_key|api_key)\b|"
    r"\b(SELECT|UPDATE|DELETE|INSERT)\s+.{0,40}\b(FROM|INTO|SET|WHERE)\b",
    re.IGNORECASE,
)

HARNESS_BROKEN_PATTERN = re.compile(
    r"(SyntaxError|IndentationError|ModuleNotFoundError|ImportError|No module named|"
    r"Cannot find module|collection error|collected 0 items|ran 0 tests|"
    r"0 tests ran|ENOENT|No such file or directory|can't open file|compilation failed|failed to compile|"
    r"is not recognized as an internal or external command|command not found)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Generic & Cross-Platform Utilities
# ---------------------------------------------------------------------------


def _emit_lines(lines: Sequence[str], max_lines: int = 12) -> None:
    """Print deterministic single-line records guaranteed never to exceed max_lines."""
    cleaned: List[str] = []
    for raw in lines:
        single = " ".join(str(raw).replace("\r", " ").replace("\n", " ").split())
        if single:
            cleaned.append(single)
    if len(cleaned) > max_lines:
        kept = cleaned[: max_lines - 1]
        kept.append(f"...TRUNCATED ({len(cleaned) - (max_lines - 1)} more lines; see S/logs/)")
        cleaned = kept
    sys.stdout.write("\n".join(cleaned) + "\n")


def _trunc(text: str, limit: int = 120) -> str:
    single = " ".join(text.replace("\r", " ").replace("\n", " ").split())
    return single if len(single) <= limit else single[: limit - 3] + "..."


def _write_lf_file(path: Path, text: str) -> None:
    """Write UTF-8 text with strict LF (\\n) line endings across Windows/POSIX."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(normalized.encode("utf-8"))


def _remove_readonly_and_rmtree(path: Path) -> None:
    def _onerror(func: Any, p: str, _exc: Any) -> None:
        try:
            os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
            func(p)
        except OSError:
            pass

    if not path.exists():
        return
    gc.collect()
    for attempt in range(3):
        try:
            shutil.rmtree(path, onerror=_onerror)
            if not path.exists():
                return
        except OSError:
            if attempt < 2:
                time.sleep(0.15)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run_git(root: Path, git_args: Sequence[str], timeout_s: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", "core.quotepath=false", "-C", str(root), *git_args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_s,
    )


def _is_git_repo(root: Path) -> bool:
    if not shutil.which("git"):
        return False
    try:
        proc = _run_git(root, ["rev-parse", "--is-inside-work-tree"], timeout_s=10)
        return proc.returncode == 0 and proc.stdout.strip().lower() == "true"
    except (OSError, subprocess.SubprocessError):
        return False


def _is_bughunt_git_line(line: str) -> bool:
    path_part = line[3:].strip() if len(line) > 3 else line.strip()
    if " -> " in path_part:
        path_part = path_part.split(" -> ")[-1].strip()
    path_part = path_part.strip('"').replace("\\", "/")
    return ".bughunt" in [p for p in path_part.split("/") if p]


def _ensure_git_info_exclude(root: Path) -> str:
    if not _is_git_repo(root):
        return "NON_GIT"
    proc = _run_git(root, ["rev-parse", "--git-path", "info/exclude"], timeout_s=10)
    if proc.returncode != 0 or not proc.stdout.strip():
        return "SKIP_PATH_ERR"
    raw_path = Path(proc.stdout.strip())
    exclude_path = raw_path if raw_path.is_absolute() else (root / raw_path)
    exclude_path.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude_path.read_text(encoding="utf-8", errors="replace") if exclude_path.exists() else ""
    lines = [ln.strip() for ln in existing.splitlines()]
    if ".bughunt/" in lines or ".bughunt" in lines:
        return "ALREADY_PRESENT"
    prefix = "" if (not existing or existing.endswith("\n")) else "\n"
    _write_lf_file(exclude_path, existing + prefix + ".bughunt/\n")
    return "ADDED"


def _take_snapshot(root: Path) -> Tuple[str, List[str]]:
    if _is_git_repo(root):
        proc = _run_git(root, ["status", "--porcelain", "--ignored", "--", "."], timeout_s=30)
        if proc.returncode == 0:
            lines = [ln.rstrip("\r\n") for ln in proc.stdout.splitlines() if ln.strip()]
            return "git", lines
    entries: List[str] = []
    root_res = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root_res):
        dirnames[:] = sorted(d for d in dirnames if d not in SNAPSHOT_SKIP_DIRS)
        dp = Path(dirpath)
        for fname in sorted(filenames):
            fp = dp / fname
            try:
                st = fp.lstat()
            except OSError:
                continue
            rel = fp.relative_to(root_res).as_posix()
            mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()
            entries.append(f"{rel}\t{mtime}")
    entries.sort()
    return "fs", entries


def _diff_snapshots(before_lines: List[str], after_lines: List[str], mode: str) -> Dict[str, List[str]]:
    if mode == "git":
        b_filt = [ln for ln in before_lines if not _is_bughunt_git_line(ln)]
        a_filt = [ln for ln in after_lines if not _is_bughunt_git_line(ln)]
        b_set, a_set = set(b_filt), set(a_filt)
        return {
            "new_or_changed": [ln for ln in a_filt if ln not in b_set],
            "resolved": [ln for ln in b_filt if ln not in a_set],
        }

    def _parse(lines: Iterable[str]) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for ln in lines:
            if "\t" in ln:
                p, ts = ln.split("\t", 1)
                if not p.startswith(".bughunt/"):
                    out[p] = ts
        return out

    b_map = _parse(before_lines)
    a_map = _parse(after_lines)
    return {
        "new_or_changed": [
            *[f"A {p}" for p in sorted(a_map) if p not in b_map],
            *[f"M {p}" for p in sorted(a_map) if p in b_map and a_map[p] != b_map[p]],
            *[f"D {p}" for p in sorted(b_map) if p not in a_map],
        ],
        "resolved": [],
    }


def _clean_new_agent_caches(root: Path, diff: Dict[str, List[str]]) -> None:
    for ln in diff.get("new_or_changed", []):
        rel_s = ln[3:].strip().strip('"').replace("\\", "/") if len(ln) > 3 and ln[2:3] == " " else ln[2:].strip()
        parts = [p for p in rel_s.split("/") if p]
        if ".bughunt" in parts:
            continue
        idx = next((i for i, p in enumerate(parts) if p in ("__pycache__", ".pytest_cache")), None)
        if idx is None:
            continue
        target = root / Path(*parts[: idx + 1])
        if target.is_dir():
            _remove_readonly_and_rmtree(target)
        elif target.exists():
            target.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Workspace Discovery & Overlay Helpers
# ---------------------------------------------------------------------------


def _list_workspace_relpaths(root: Path) -> List[str]:
    """Return tracked + untracked non-ignored POSIX relative file paths."""
    root_res = root.resolve()
    if _is_git_repo(root_res):
        proc = _run_git(root_res, ["ls-files", "-z", "--cached", "--others", "--exclude-standard"], timeout_s=20)
        if proc.returncode == 0:
            out: List[str] = []
            for raw in proc.stdout.split("\0"):
                rel = raw.strip().replace("\\", "/")
                if not rel or rel.startswith(".bughunt/") or "/.bughunt/" in rel:
                    continue
                parts = rel.split("/")
                if any(p in EXCLUDE_DIRS for p in parts):
                    continue
                fp = root_res / rel
                if fp.is_file():
                    out.append(rel)
            return sorted(set(out))

    out = []
    for dirpath, dirnames, filenames in os.walk(root_res):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_DIRS)
        dp = Path(dirpath)
        for fname in sorted(filenames):
            fp = dp / fname
            if fp.is_file():
                rel = fp.relative_to(root_res).as_posix()
                if not rel.startswith(".bughunt/"):
                    out.append(rel)
    return sorted(set(out))


def _copy_workspace_tree(src_root: Path, dst_root: Path) -> int:
    _remove_readonly_and_rmtree(dst_root)
    dst_root.mkdir(parents=True, exist_ok=True)
    relpaths = _list_workspace_relpaths(src_root)
    copied = 0
    for rel in relpaths:
        src = src_root / rel
        dst = dst_root / rel
        if not src.is_file():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied += 1
    return copied


def _copy_overlay_tree(src_root: Path, dst_root: Path) -> int:
    """Copy workspace tree directly without running git inside .bughunt/ subdirectories."""
    _remove_readonly_and_rmtree(dst_root)
    dst_root.mkdir(parents=True, exist_ok=True)
    relpaths = _walk_overlay_relpaths(src_root)
    copied = 0
    for rel in relpaths:
        src = src_root / rel
        dst = dst_root / rel
        if not src.is_file():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied += 1
    return copied


def _snapshot_overlay_dir(src_overlay: Path, dst_checkpoint: Path) -> int:
    return _copy_overlay_tree(src_overlay, dst_checkpoint)


def _walk_overlay_relpaths(dir_root: Path) -> List[str]:
    if not dir_root.is_dir():
        return []
    out: List[str] = []
    root_res = dir_root.resolve()
    for dirpath, dirnames, filenames in os.walk(root_res):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_DIRS)
        dp = Path(dirpath)
        for fname in sorted(filenames):
            fp = dp / fname
            if fp.is_file():
                out.append(fp.relative_to(root_res).as_posix())
    return sorted(out)


def _generate_tree_diff(base_dir: Path, target_dir: Path) -> Tuple[str, List[str]]:
    """Generate deterministic pure-LF unified diff between two workspace trees."""
    base_files = set(_walk_overlay_relpaths(base_dir))
    targ_files = set(_walk_overlay_relpaths(target_dir))
    all_rels = sorted(base_files | targ_files)
    chunks: List[str] = []
    modified: List[str] = []

    for rel in all_rels:
        bf = base_dir / rel
        tf = target_dir / rel
        ext = Path(rel).suffix.lower()
        if ext in BINARY_EXTS:
            continue
        b_bytes = bf.read_bytes() if bf.is_file() else None
        t_bytes = tf.read_bytes() if tf.is_file() else None
        if b_bytes == t_bytes:
            continue
        if (b_bytes and b"\0" in b_bytes[:4096]) or (t_bytes and b"\0" in t_bytes[:4096]):
            continue

        b_text = (b_bytes.decode("utf-8", errors="replace") if b_bytes is not None else "").replace("\r\n", "\n").replace("\r", "\n")
        t_text = (t_bytes.decode("utf-8", errors="replace") if t_bytes is not None else "").replace("\r\n", "\n").replace("\r", "\n")
        if b_text == t_text:
            continue

        b_lines = b_text.splitlines(keepends=True) if b_text else []
        t_lines = t_text.splitlines(keepends=True) if t_text else []
        # Ensure trailing newline consistency inside diff hunks
        if b_lines and not b_lines[-1].endswith("\n"):
            b_lines[-1] = b_lines[-1] + "\n"
        if t_lines and not t_lines[-1].endswith("\n"):
            t_lines[-1] = t_lines[-1] + "\n"

        fromfile = "/dev/null" if b_bytes is None else f"a/{rel}"
        tofile = "/dev/null" if t_bytes is None else f"b/{rel}"
        diff_lines = list(difflib.unified_diff(b_lines, t_lines, fromfile=fromfile, tofile=tofile, n=3))
        if diff_lines:
            modified.append(rel)
            chunks.append(f"diff --git a/{rel} b/{rel}\n" + "".join(diff_lines))

    patch_text = "".join(chunks).replace("\r\n", "\n").replace("\r", "\n")
    return patch_text, modified


_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _strip_patch_prefix(raw_path: str) -> str:
    cleaned = raw_path.strip().split("\t")[0].strip().strip('"').replace("\\", "/")
    if cleaned in ("/dev/null", "dev/null"):
        return "/dev/null"
    if cleaned.startswith("a/") or cleaned.startswith("b/"):
        cleaned = cleaned[2:]
    return cleaned.lstrip("./")


def _apply_unified_patch_to_dir(overlay_dir: Path, patch_text: str) -> List[str]:
    """Pure-Python deterministic unified diff applier safe inside nested .git trees."""
    norm = patch_text.replace("\r\n", "\n").replace("\r", "\n")
    if not norm.strip():
        return []
    lines = norm.splitlines(keepends=True)
    idx = 0
    touched: List[str] = []

    while idx < len(lines):
        line = lines[idx]
        if line.startswith("diff --git ") or line.startswith("index ") or line.startswith("new file") or line.startswith("deleted file"):
            idx += 1
            continue
        if not line.startswith("--- "):
            idx += 1
            continue
        if idx + 1 >= len(lines) or not lines[idx + 1].startswith("+++ "):
            raise ValueError(f"Malformed patch header near line {idx + 1}")

        old_rel = _strip_patch_prefix(lines[idx][4:])
        new_rel = _strip_patch_prefix(lines[idx + 1][4:])
        idx += 2
        rel = new_rel if new_rel != "/dev/null" else old_rel
        target_path = (overlay_dir / rel).resolve()
        if not str(target_path).startswith(str(overlay_dir.resolve())):
            raise ValueError(f"Unsafe patch path outside overlay: {rel}")

        hunks: List[Tuple[int, int, List[str]]] = []
        while idx < len(lines) and not lines[idx].startswith("diff --git ") and not lines[idx].startswith("--- "):
            m = _HUNK_HEADER_RE.match(lines[idx])
            if not m:
                idx += 1
                continue
            old_start = int(m.group(1))
            old_count = int(m.group(2)) if m.group(2) is not None else 1
            idx += 1
            hunk_body: List[str] = []
            while idx < len(lines):
                cur = lines[idx]
                if cur.startswith("@@ ") or cur.startswith("diff --git ") or cur.startswith("--- "):
                    break
                if cur.startswith("\\ No newline at end of file"):
                    idx += 1
                    continue
                if cur[:1] in (" ", "+", "-"):
                    hunk_body.append(cur)
                idx += 1
            hunks.append((old_start, old_count, hunk_body))

        if new_rel == "/dev/null":
            if target_path.exists():
                target_path.unlink()
            touched.append(rel)
            continue

        orig_bytes = target_path.read_bytes() if target_path.is_file() else b""
        newline_style = "\r\n" if b"\r\n" in orig_bytes else "\n"
        orig_text = orig_bytes.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
        src_lines = orig_text.splitlines(keepends=True)
        if src_lines and not src_lines[-1].endswith("\n"):
            src_lines[-1] += "\n"

        out_lines = list(src_lines)
        offset = 0
        for old_start, _old_count, hunk_body in hunks:
            expected_old = [hb[1:] for hb in hunk_body if hb[:1] in (" ", "-")]
            replacement_new = [hb[1:] for hb in hunk_body if hb[:1] in (" ", "+")]
            pos = max(0, (old_start - 1) + offset) if expected_old else 0

            def _matches_at(start_idx: int) -> bool:
                if start_idx < 0 or start_idx + len(expected_old) > len(out_lines):
                    return False
                for k, exp in enumerate(expected_old):
                    if out_lines[start_idx + k].rstrip("\n") != exp.rstrip("\n"):
                        return False
                return True

            if expected_old and not _matches_at(pos):
                found_pos = None
                for delta in range(1, max(25, len(out_lines) + 1)):
                    for cand in (pos - delta, pos + delta):
                        if _matches_at(cand):
                            found_pos = cand
                            break
                    if found_pos is not None:
                        break
                if found_pos is None:
                    raise ValueError(f"PATCH_CONFLICT in {rel} near line {old_start}")
                pos = found_pos

            out_lines[pos : pos + len(expected_old)] = replacement_new
            offset += len(replacement_new) - len(expected_old)

        target_path.parent.mkdir(parents=True, exist_ok=True)
        final_text = "".join(out_lines)
        if newline_style == "\r\n":
            final_text = final_text.replace("\n", "\r\n")
        target_path.write_bytes(final_text.encode("utf-8"))
        touched.append(rel)

    return sorted(set(touched))


def _sync_from_dir_to_overlay(from_dir: Path, overlay_dir: Path) -> List[str]:
    from_res = from_dir.resolve()
    changed: List[str] = []
    for rel in _walk_overlay_relpaths(from_res):
        src = from_res / rel
        dst = overlay_dir / rel
        if not src.is_file():
            continue
        if not dst.is_file() or src.read_bytes() != dst.read_bytes():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            changed.append(rel)
    return changed


# ---------------------------------------------------------------------------
# Skill Discovery & State Persistence
# ---------------------------------------------------------------------------


def _candidate_skill_roots(root: Path, explicit_skills_dir: Optional[str]) -> List[Path]:
    if explicit_skills_dir:
        return [Path(explicit_skills_dir).expanduser().resolve()]
    cands: List[Path] = []
    env_dir = os.environ.get("VPILOT_SKILLS_DIR")
    if env_dir:
        cands.append(Path(env_dir).expanduser().resolve())
    script_parent = Path(__file__).resolve().parents[2]
    cands.append(script_parent)
    home = Path.home()
    cands.extend(
        [
            home / ".gemini" / "config" / "skills",
            home / ".claude" / "skills",
            root.resolve() / ".claude" / "skills",
            root.resolve() / ".agents" / "skills",
            root.resolve() / ".cursor" / "skills",
            root.resolve() / ".windsurf" / "skills",
            root.resolve() / ".roo" / "skills",
            root.resolve() / ".cline" / "skills",
        ]
    )
    dedup: List[Path] = []
    seen: Set[str] = set()
    for p in cands:
        key = str(p)
        if key not in seen:
            seen.add(key)
            dedup.append(p)
    return dedup


def discover_skills(root: Path, explicit_skills_dir: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    roots = _candidate_skill_roots(root, explicit_skills_dir)
    found: Dict[str, Dict[str, Any]] = {}
    for sk, meta in SUITE_REGISTRY.items():
        info: Dict[str, Any] = {
            "installed": False,
            "path": "",
            "skill_md": "",
            "cli_path": "",
            "version": meta["tag"],
            "cli_rel": meta["cli"],
        }
        for base in roots:
            cand = base / sk
            skill_md = cand / "SKILL.md"
            cli_path = cand / meta["cli"]
            if cand.is_dir() and skill_md.is_file() and cli_path.is_file():
                ver = meta["tag"]
                if _is_git_repo(cand):
                    tp = _run_git(cand, ["describe", "--tags", "--always"], timeout_s=10)
                    if tp.returncode == 0 and tp.stdout.strip():
                        ver = tp.stdout.strip()
                info.update(
                    {
                        "installed": True,
                        "path": str(cand.resolve()),
                        "skill_md": str(skill_md.resolve()),
                        "cli_path": str(cli_path.resolve()),
                        "version": ver,
                    }
                )
                break
        found[sk] = info
    return found


def _load_state(s_dir: Path) -> Dict[str, Any]:
    sp = s_dir / "logs" / "state.json"
    if not sp.is_file():
        return {}
    return json.loads(sp.read_text(encoding="utf-8"))


def _save_state(s_dir: Path, state: Dict[str, Any]) -> None:
    sp = s_dir / "logs" / "state.json"
    _write_lf_file(sp, json.dumps(state, indent=2, ensure_ascii=False) + "\n")


def _append_worklog(s_dir: Path, status: Optional[str], entries: Sequence[str]) -> str:
    wl = s_dir / "worklog.md"
    if not wl.is_file():
        _write_lf_file(wl, f"# VeriPilot Worklog\nStatus: {status or 'Initialized'}\n\n")
    lines = wl.read_text(encoding="utf-8", errors="replace").splitlines()
    if status:
        replaced = False
        for i, ln in enumerate(lines):
            if ln.startswith("Status:"):
                lines[i] = f"Status: {status}"
                replaced = True
                break
        if not replaced:
            lines.insert(1 if lines else 0, f"Status: {status}")
    ts = _now_iso()
    for ent in entries:
        clean = " ".join(ent.replace("\r", " ").replace("\n", " ").split())
        if clean:
            lines.append(f"- [{ts}] {clean}")
    _write_lf_file(wl, "\n".join(lines).rstrip("\n") + "\n")
    return status or next((ln[7:].strip() for ln in lines if ln.startswith("Status:")), "OK")


# ---------------------------------------------------------------------------
# Subcommand: init
# ---------------------------------------------------------------------------


def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if not root.is_dir():
        _emit_lines([f"ERROR=Root not found: {root}"])
        return 1

    bh_root = root / ".bughunt"
    cache_dir = bh_root / ".cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    s_dir = bh_root / f"pilot-{ts}"
    suffix = 1
    while s_dir.exists():
        s_dir = bh_root / f"pilot-{ts}-{suffix}"
        suffix += 1

    for sub in ("patches", "logs", "tmp", "checkpoints", "baseline", "overlay"):
        (s_dir / sub).mkdir(parents=True, exist_ok=True)

    exclude_status = _ensure_git_info_exclude(root)
    snap_mode, snap_lines = _take_snapshot(root)
    _write_lf_file(s_dir / "logs" / "fs-before.txt", "\n".join(snap_lines) + ("\n" if snap_lines else ""))
    (s_dir / "logs" / "fs-mode.txt").write_text(snap_mode, encoding="utf-8")

    baseline_count = _copy_workspace_tree(root, s_dir / "baseline")
    overlay_count = _copy_overlay_tree(s_dir / "baseline", s_dir / "overlay")
    skills = discover_skills(root, getattr(args, "skills_dir", None))

    installed_names = [sk for sk, info in skills.items() if info["installed"]]
    missing_names = [sk for sk, info in skills.items() if not info["installed"]]

    state: Dict[str, Any] = {
        "version": VPILOT_VERSION,
        "root": str(root),
        "s_dir": str(s_dir),
        "s_name": s_dir.name,
        "created_at": _now_iso(),
        "is_git": _is_git_repo(root),
        "exclude_status": exclude_status,
        "snap_mode": snap_mode,
        "skills": skills,
        "route_plan": None,
        "stage_index": 0,
        "completed_stages": [],
        "circuit_breaker": {"tripped": False, "reason": "NONE", "detail": ""},
    }
    _save_state(s_dir, state)
    _append_worklog(
        s_dir,
        "Phase 0 - Initialized",
        [f"Session {s_dir.name} initialized; baseline_files={baseline_count}; installed={','.join(installed_names)}"],
    )

    _emit_lines(
        [
            f"S={s_dir}",
            f"SNAME={s_dir.name}",
            f"ROOT={root}",
            f"GIT={state['is_git']} EXCLUDE={exclude_status}",
            f"BASELINE={s_dir / 'baseline'} ({baseline_count} files)",
            f"OVERLAY={s_dir / 'overlay'} ({overlay_count} files)",
            f"SKILLS_READY={','.join(installed_names) or 'none'}",
            f"SKILLS_MISSING={','.join(missing_names) or 'none'}",
        ]
    )
    return 0


# ---------------------------------------------------------------------------
# Subcommand: route (3-Layer Deterministic Triage)
# ---------------------------------------------------------------------------


def _detect_git_changes(root: Path) -> Dict[str, Any]:
    if not _is_git_repo(root):
        return {"dirty": False, "ahead": False, "base_ref": "", "touched": []}
    dirty_files: Set[str] = set()
    st_proc = _run_git(root, ["status", "--porcelain", "--", "."], timeout_s=15)
    if st_proc.returncode == 0:
        for ln in st_proc.stdout.splitlines():
            if not ln.strip() or _is_bughunt_git_line(ln):
                continue
            path_part = ln[3:].strip()
            if " -> " in path_part:
                path_part = path_part.split(" -> ")[-1].strip()
            rel = path_part.strip('"').replace("\\", "/")
            if rel and (root / rel).exists():
                dirty_files.add(rel)

    untracked_proc = _run_git(root, ["ls-files", "--others", "--exclude-standard"], timeout_s=15)
    if untracked_proc.returncode == 0:
        for raw in untracked_proc.stdout.splitlines():
            rel = raw.strip().strip('"').replace("\\", "/")
            if rel and not rel.startswith(".bughunt/") and (root / rel).is_file():
                dirty_files.add(rel)

    ahead = False
    base_ref = ""
    commit_files: Set[str] = set()
    has_head = _run_git(root, ["rev-parse", "--verify", "HEAD"], timeout_s=10).returncode == 0
    if has_head:
        br_proc = _run_git(root, ["symbolic-ref", "--short", "-q", "HEAD"], timeout_s=10)
        curr_branch = br_proc.stdout.strip() if br_proc.returncode == 0 else ""
        head_sha = _run_git(root, ["rev-parse", "HEAD"], timeout_s=10).stdout.strip()
        if curr_branch and curr_branch not in _TRUNK_BRANCH_NAMES and head_sha:
            for trunk in _TRUNK_CANDIDATES:
                if _run_git(root, ["rev-parse", "--verify", trunk], timeout_s=10).returncode != 0:
                    continue
                mb_proc = _run_git(root, ["merge-base", trunk, "HEAD"], timeout_s=10)
                mb_sha = mb_proc.stdout.strip() if mb_proc.returncode == 0 else ""
                if mb_sha and mb_sha != head_sha:
                    ahead = True
                    base_ref = trunk
                    df = _run_git(root, ["diff", "--name-only", mb_sha, "HEAD"], timeout_s=15)
                    if df.returncode == 0:
                        for raw in df.stdout.splitlines():
                            rel = raw.strip().strip('"').replace("\\", "/")
                            if rel and not rel.startswith(".bughunt/"):
                                commit_files.add(rel)
                break

    touched = sorted(dirty_files | commit_files)
    return {
        "dirty": bool(dirty_files),
        "ahead": ahead,
        "base_ref": base_ref,
        "touched": touched,
    }


def _scan_touched_file_risks(root: Path, touched_files: Sequence[str]) -> Dict[str, Any]:
    flagged_files: List[str] = []
    matched_tokens: Set[str] = set()

    for rel in touched_files:
        norm_rel = rel.replace("\\", "/").lower()
        path_hits = [kw for kw in SEC_PATH_KEYWORDS if kw in norm_rel]
        file_tokens: List[str] = []
        fp = root / rel
        if fp.is_file() and fp.suffix.lower() not in BINARY_EXTS:
            try:
                content = fp.read_text(encoding="utf-8", errors="replace")[:32768]
                for m in SEC_CODE_PATTERN.finditer(content):
                    tok = m.group(1) or m.group(2)
                    if tok:
                        file_tokens.append(tok)
            except OSError:
                pass
        if path_hits or file_tokens:
            flagged_files.append(rel)
            matched_tokens.update(path_hits)
            matched_tokens.update(file_tokens)

    return {
        "sec_risk": "HIGH" if flagged_files else "LOW",
        "flagged_files": sorted(set(flagged_files)),
        "tokens": sorted(matched_tokens)[:8],
    }


def cmd_route(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    prompt = (args.prompt or "").strip()
    prompt_lower = prompt.lower()

    # Layer 1: Bilingual Intent Signals + Request Order Tracking
    first_pos: Dict[str, int] = {}
    matched_keywords: Dict[str, List[str]] = {}
    for sk, (en_regexes, th_subs) in INTENT_PATTERNS.items():
        hits: List[str] = []
        earliest: Optional[int] = None
        for pat in en_regexes:
            m = re.search(pat, prompt_lower)
            if m:
                hits.append(m.group(0))
                earliest = m.start() if earliest is None else min(earliest, m.start())
        for sub in th_subs:
            idx = prompt_lower.find(sub.lower())
            if idx != -1:
                hits.append(sub)
                earliest = idx if earliest is None else min(earliest, idx)
        if hits and earliest is not None:
            first_pos[sk] = earliest
            matched_keywords[sk] = hits

    requested_order = [sk for sk, _ in sorted(first_pos.items(), key=lambda kv: kv[1])]

    # Layer 2: Real Git State Signal
    git_info = _detect_git_changes(root)
    touched_files = list(git_info["touched"])
    if args.changed_files:
        extra = [f.strip().replace("\\", "/") for f in args.changed_files.split(",") if f.strip()]
        touched_files = sorted(set(touched_files) | set(extra))

    selected: Set[str] = set(requested_order)
    broad_review = any(h in prompt_lower for h in BROAD_REVIEW_HINTS)
    if (git_info["dirty"] or git_info["ahead"] or touched_files) and (not selected or broad_review):
        if "veripr" not in selected:
            selected.add("veripr")
            requested_order.append("veripr")

    # Layer 3: Touched File Risk Scan
    risk_info = _scan_touched_file_risks(root, touched_files)
    sec_auto_added = False
    if risk_info["sec_risk"] == "HIGH" and ("veripr" in selected or "verihunt" in selected or not selected):
        if "verisec" not in selected:
            selected.add("verisec")
            requested_order.append("verisec")
            sec_auto_added = True

    if not selected:
        default_skill = "veripr" if (git_info["dirty"] or git_info["ahead"]) else "verihunt"
        selected.add(default_skill)
        requested_order.append(default_skill)

    causal_plan = sorted(selected, key=lambda sk: CAUSAL_PRIORITY[sk])
    reordered = requested_order != causal_plan
    mode = "CHAIN" if len(causal_plan) > 1 else "SINGLE"
    budget_gate = "CONFIRM_OVER_2_SKILLS" if len(causal_plan) > 2 else "AUTO_PROCEED"

    skills_map = discover_skills(root, getattr(args, "skills_dir", None))
    first_skill = causal_plan[0]
    first_skill_md = skills_map.get(first_skill, {}).get("skill_md", "")
    target_scope = ",".join(touched_files[:12]) if touched_files else "."

    route_payload: Dict[str, Any] = {
        "prompt": prompt,
        "mode": mode,
        "requested_order": requested_order,
        "causal_plan": causal_plan,
        "reordered": reordered,
        "budget_gate": budget_gate,
        "matched_keywords": matched_keywords,
        "git_state": git_info,
        "risk_scan": risk_info,
        "sec_auto_added": sec_auto_added,
        "target_scope": touched_files if touched_files else ["."],
    }

    route_json_path = ""
    if args.s:
        s_dir = Path(args.s).resolve()
        rp = s_dir / "logs" / "route_plan.json"
        _write_lf_file(rp, json.dumps(route_payload, indent=2, ensure_ascii=False) + "\n")
        route_json_path = str(rp)
        state = _load_state(s_dir)
        if state:
            skills_map = state.get("skills", skills_map)
            first_skill_md = skills_map.get(first_skill, {}).get("skill_md", first_skill_md)
            state["route_plan"] = route_payload
            state["stage_index"] = 0
            _save_state(s_dir, state)
            _append_worklog(
                s_dir,
                "Phase 1 - Routed",
                [f"Plan={' -> '.join(causal_plan)} reordered={reordered} sec_risk={risk_info['sec_risk']} scope={_trunc(target_scope, 60)}"],
            )

    _emit_lines(
        [
            f"MODE={mode} BUDGET_GATE={budget_gate}",
            f"PLAN={' -> '.join(causal_plan)}",
            f"REQUESTED_ORDER={','.join(requested_order)} REORDERED={reordered}",
            f"INTENT_HITS={'; '.join(f'{k}:{','.join(v[:2])}' for k, v in matched_keywords.items()) or 'git_or_fallback'}",
            f"GIT_STATE=dirty:{git_info['dirty']},ahead:{git_info['ahead']},base:{git_info['base_ref'] or 'HEAD'}",
            f"SEC_RISK={risk_info['sec_risk']} AUTO_SEC={sec_auto_added} RISK_FILES={','.join(risk_info['flagged_files'][:4]) or 'none'}",
            f"TARGET_SCOPE={_trunc(target_scope, 100)}",
            f"CURRENT_SKILL={first_skill}",
            f"CURRENT_SKILL_MD={first_skill_md or 'NOT_INSTALLED'}",
            f"ROUTE_JSON={route_json_path or 'memory'}",
        ]
    )
    return 0


# ---------------------------------------------------------------------------
# Subcommand: handoff (Cumulative Overlay + Circuit Breaker)
# ---------------------------------------------------------------------------


def _run_overlay_check(overlay_dir: Path, check_cmd: str) -> Tuple[int, str, bool]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["VERIPILOT_OVERLAY"] = str(overlay_dir.resolve())
    args_list = shlex.split(check_cmd, posix=(os.name != "nt"))
    if os.name == "nt":
        args_list = [a.strip('"').strip("'") for a in args_list]
    try:
        proc = subprocess.run(
            args_list,
            cwd=str(overlay_dir),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
        broken = bool(HARNESS_BROKEN_PATTERN.search(combined)) or (proc.returncode != 0 and "ran 0 tests" in combined.lower())
        return proc.returncode, _trunc(combined, 140), broken
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, _trunc(str(exc), 140), True


def cmd_handoff(args: argparse.Namespace) -> int:
    s_dir = Path(args.s).resolve()
    state = _load_state(s_dir)
    if not state:
        _emit_lines([f"ERROR=Invalid or uninitialized session: {s_dir}"])
        return 2

    plan: List[str] = (state.get("route_plan") or {}).get("causal_plan") or []
    stage_idx = int(state.get("stage_index", 0))
    skill = args.skill.strip().lower()
    overlay_dir = s_dir / "overlay"
    prev_ckpt = (
        s_dir / "checkpoints" / f"stage_{stage_idx}_{state['completed_stages'][-1]['skill']}"
        if state.get("completed_stages")
        else s_dir / "baseline"
    )
    if not prev_ckpt.is_dir():
        prev_ckpt = s_dir / "baseline"

    # Evaluate Circuit Breaker first
    tripped = False
    reason = "NONE"
    detail = ""
    if args.status in ("HARNESS_BROKEN", "ENV_BROKEN"):
        tripped = True
        reason = args.status
        detail = args.summary or "Stage reported broken test harness or environment."
    elif args.check_cmd:
        rc, out_snip, broken = _run_overlay_check(overlay_dir, args.check_cmd)
        if broken:
            tripped = True
            reason = "HARNESS_BROKEN"
            detail = out_snip
        elif rc != 0 and args.status == "FAIL":
            detail = out_snip

    if not tripped and args.enforce_budget and (len(state.get("completed_stages", [])) + 1) >= 2:
        next_idx = stage_idx + 1
        if next_idx < len(plan) and not args.confirm_over_budget:
            tripped = True
            reason = "BUDGET_EXCEEDED_2_SKILLS"
            detail = f"Halted before stage {next_idx + 1} ({plan[next_idx]}); requires user confirmation."

    if tripped:
        state["circuit_breaker"] = {"tripped": True, "reason": reason, "detail": detail}
        state["completed_stages"].append(
            {
                "stage": stage_idx + 1,
                "skill": skill,
                "status": reason,
                "findings": int(args.findings),
                "tests_ran": int(args.tests_ran),
                "patch": "",
                "summary": _trunc(detail or args.summary or reason, 120),
            }
        )
        _save_state(s_dir, state)
        _append_worklog(s_dir, f"HALTED - Circuit Breaker ({reason})", [f"Stage {stage_idx + 1} ({skill}) tripped: {_trunc(detail, 90)}"])
        _emit_lines(
            [
                "HANDOFF_STATUS=HALTED_CIRCUIT_BREAKER",
                f"STAGE={stage_idx + 1}/{max(len(plan), 1)} SKILL={skill}",
                "CIRCUIT_BREAKER=TRIPPED",
                f"REASON={reason}",
                f"DETAIL={_trunc(detail, 110)}",
                "NEXT_SKILL=NONE",
                "NEXT_SKILL_MD=NONE",
                f"OVERLAY={overlay_dir}",
            ]
        )
        return 0

    # Apply patch or workspace overlay delta
    touched_files: List[str] = []
    if args.patch:
        pp = Path(args.patch).resolve()
        if not pp.is_file():
            _emit_lines([f"ERROR=Patch file not found: {pp}"])
            return 2
        try:
            touched_files = _apply_unified_patch_to_dir(overlay_dir, pp.read_text(encoding="utf-8", errors="replace"))
        except ValueError as exc:
            _emit_lines([f"HANDOFF_STATUS=PATCH_CONFLICT", f"ERROR={exc}"])
            return 2
    elif args.from_dir:
        fd = Path(args.from_dir).resolve()
        if not fd.is_dir():
            _emit_lines([f"ERROR=Source dir not found: {fd}"])
            return 2
        touched_files = _sync_from_dir_to_overlay(fd, overlay_dir)

    stage_num = stage_idx + 1
    stage_patch_text, stage_modified = _generate_tree_diff(prev_ckpt, overlay_dir)
    stage_patch_path = s_dir / "patches" / f"stage_{stage_num}_{skill}.patch"
    _write_lf_file(stage_patch_path, stage_patch_text)

    ckpt_dir = s_dir / "checkpoints" / f"stage_{stage_num}_{skill}"
    _snapshot_overlay_dir(overlay_dir, ckpt_dir)

    next_idx = stage_idx + 1
    next_skill = plan[next_idx] if next_idx < len(plan) else "NONE"
    skills_map = state.get("skills", {})
    next_skill_md = skills_map.get(next_skill, {}).get("skill_md", "") if next_skill != "NONE" else "NONE"

    state["stage_index"] = next_idx
    state["completed_stages"].append(
        {
            "stage": stage_num,
            "skill": skill,
            "status": args.status,
            "findings": int(args.findings),
            "tests_ran": int(args.tests_ran),
            "patch": str(stage_patch_path),
            "modified_files": sorted(set(touched_files) | set(stage_modified)),
            "summary": _trunc(args.summary or "Stage completed", 120),
        }
    )
    _save_state(s_dir, state)
    _append_worklog(
        s_dir,
        f"Phase 3 - Handoff ({skill} -> {next_skill})",
        [f"Stage {stage_num} ({skill}) status={args.status} findings={args.findings} tests={args.tests_ran} files={','.join(stage_modified) or 'none'}"],
    )

    _emit_lines(
        [
            "HANDOFF_STATUS=OK",
            f"STAGE={stage_num}/{max(len(plan), stage_num)} SKILL={skill} STATUS={args.status}",
            "CIRCUIT_BREAKER=OK REASON=NONE",
            f"STAGE_PATCH={stage_patch_path}",
            f"FILES_UPDATED={','.join(stage_modified) or 'none'}",
            f"CHECKPOINT={ckpt_dir}",
            f"OVERLAY={overlay_dir}",
            f"NEXT_SKILL={next_skill}",
            f"NEXT_SKILL_MD={next_skill_md or 'NOT_INSTALLED'}",
            f"REMAINING={','.join(plan[next_idx:]) or 'none'}",
        ]
    )
    return 0


# ---------------------------------------------------------------------------
# Subcommand: finalize (Unified Pure-LF Patch + Cleanliness)
# ---------------------------------------------------------------------------


def _verify_git_apply(root: Path, patch_path: Path) -> str:
    if not patch_path.is_file() or not patch_path.read_text(encoding="utf-8", errors="replace").strip():
        return "EMPTY"
    if not _is_git_repo(root):
        return "NON_GIT_SKIP"
    proc = _run_git(
        root,
        ["apply", "--check", "--ignore-space-change", "--ignore-whitespace", str(patch_path.resolve())],
        timeout_s=20,
    )
    return "OK" if proc.returncode == 0 else f"FAIL:{_trunc(proc.stderr or proc.stdout, 90)}"


def cmd_finalize(args: argparse.Namespace) -> int:
    s_dir = Path(args.s).resolve()
    state = _load_state(s_dir)
    if not state:
        _emit_lines([f"ERROR=Invalid or uninitialized session: {s_dir}"])
        return 2

    root = Path(state["root"]).resolve()
    baseline_dir = s_dir / "baseline"
    overlay_dir = s_dir / "overlay"
    unified_patch = s_dir / "patches" / "veripilot-unified.patch"

    verify_status = "SKIPPED"
    if args.verify_cmd and overlay_dir.is_dir():
        rc, out_snip, broken = _run_overlay_check(overlay_dir, args.verify_cmd)
        verify_status = "PASS" if rc == 0 and not broken else f"FAIL:{out_snip}"

    if baseline_dir.is_dir() and overlay_dir.is_dir():
        patch_text, modified_files = _generate_tree_diff(baseline_dir, overlay_dir)
        _write_lf_file(unified_patch, patch_text)
    else:
        patch_text = unified_patch.read_text(encoding="utf-8", errors="replace") if unified_patch.is_file() else ""
        modified_files = []

    git_apply_status = _verify_git_apply(root, unified_patch)
    patch_bytes = unified_patch.stat().st_size if unified_patch.is_file() else 0
    has_cr = b"\r" in unified_patch.read_bytes() if unified_patch.is_file() else False

    cleanliness = "NOT_CLEANED"
    if args.clean:
        for temp_sub in ("baseline", "overlay", "checkpoints", "tmp"):
            _remove_readonly_and_rmtree(s_dir / temp_sub)
        before_path = s_dir / "logs" / "fs-before.txt"
        before_lines = before_path.read_text(encoding="utf-8", errors="replace").splitlines() if before_path.is_file() else []
        snap_mode = state.get("snap_mode", "git")
        _, after_lines = _take_snapshot(root)
        diff = _diff_snapshots(before_lines, after_lines, snap_mode)
        _clean_new_agent_caches(root, diff)
        _, after_lines2 = _take_snapshot(root)
        diff2 = _diff_snapshots(before_lines, after_lines2, snap_mode)
        _write_lf_file(s_dir / "logs" / "fs-after.txt", "\n".join(after_lines2) + ("\n" if after_lines2 else ""))
        stray = diff2.get("new_or_changed", [])
        cleanliness = "CLEAN (0 stray files outside .bughunt/)" if not stray else f"DIRTY ({len(stray)} stray)"

    stages = state.get("completed_stages", [])
    cb = state.get("circuit_breaker", {})
    cb_label = "TRIPPED" if cb.get("tripped") else "OK"
    total_findings = sum(int(st.get("findings", 0)) for st in stages)
    stage_summary = " | ".join(f"{st['skill']}:{st['status']}({st['findings']})" for st in stages) or "none"

    _append_worklog(
        s_dir,
        f"Phase 4 - Finalized ({cb_label})",
        [f"unified_patch={unified_patch} git_apply={git_apply_status} verify={verify_status} cleanliness={cleanliness}"],
    )

    _emit_lines(
        [
            f"FINALIZE_STATUS={'HALTED' if cb.get('tripped') else 'OK'}",
            f"UNIFIED_PATCH={unified_patch}",
            f"PATCH_BYTES={patch_bytes} PURE_LF={not has_cr} GIT_APPLY={git_apply_status}",
            f"FILES_MODIFIED={','.join(modified_files) or 'none'}",
            f"VERIFY_CMD={verify_status}",
            f"CIRCUIT_BREAKER={cb_label} REASON={cb.get('reason', 'NONE')}",
            f"CLEANLINESS={cleanliness}",
            f"TOTAL_FINDINGS={total_findings} STAGES={stage_summary}",
        ]
    )
    return 0


# ---------------------------------------------------------------------------
# Subcommand: install (One-Command Suite Installer across 6 Platforms)
# ---------------------------------------------------------------------------


def _resolve_platform_targets(
    platforms: Sequence[str],
    target_dir: Optional[str],
    home_dir: Optional[str],
    project_dir: Optional[str],
) -> Dict[str, Path]:
    home = Path(home_dir).expanduser().resolve() if home_dir else Path.home()
    proj = Path(project_dir).expanduser().resolve() if project_dir else Path.cwd()
    default_map = {
        "claude": home / ".claude" / "skills",
        "antigravity": home / ".gemini" / "config" / "skills",
        "cursor": proj / ".cursor" / "skills",
        "windsurf": proj / ".windsurf" / "skills",
        "roocode": proj / ".roo" / "skills",
        "cline": proj / ".cline" / "skills",
    }
    if target_dir:
        base = Path(target_dir).expanduser().resolve()
        if len(platforms) == 1:
            return {platforms[0]: base}
        return {p: base / p for p in platforms}
    return {p: default_map[p] for p in platforms}


def _copy_skill_offline(src: Path, dst: Path) -> None:
    if src.resolve() == dst.resolve():
        return
    _remove_readonly_and_rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        src,
        dst,
        ignore=shutil.ignore_patterns(".git", ".bughunt", "__pycache__", ".pytest_cache", "*.pyc"),
    )


def _install_skill_online(repo_url: str, tag: str, dst: Path) -> None:
    if not shutil.which("git"):
        raise RuntimeError("git CLI is required for online install")
    if dst.is_dir() and (dst / ".git").is_dir():
        proc = _run_git(dst, ["fetch", "--tags", "--force"], timeout_s=60)
        if proc.returncode != 0:
            raise RuntimeError(_trunc(proc.stderr or proc.stdout, 100))
        co = _run_git(dst, ["checkout", tag], timeout_s=30)
        if co.returncode != 0:
            raise RuntimeError(_trunc(co.stderr or co.stdout, 100))
        return
    if dst.exists():
        _remove_readonly_and_rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["git", "clone", "--branch", tag, "--depth", "1", repo_url, str(dst)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
    )
    if proc.returncode != 0:
        raise RuntimeError(_trunc(proc.stderr or proc.stdout, 100))


def cmd_install(args: argparse.Namespace) -> int:
    raw_plats = [p.strip().lower() for p in (args.platform or "antigravity").split(",") if p.strip()]
    if "all" in raw_plats:
        platforms = list(ALL_PLATFORMS)
    else:
        platforms = []
        for p in raw_plats:
            norm = PLATFORM_ALIASES.get(p, p)
            if norm not in ALL_PLATFORMS:
                _emit_lines([f"ERROR=Unknown platform '{p}'. Choose from: all,{','.join(ALL_PLATFORMS)}"])
                return 2
            if norm not in platforms:
                platforms.append(norm)

    skills_req = [s.strip().lower() for s in (args.skills or "").split(",") if s.strip()] or list(SUITE_REGISTRY.keys())
    for sk in skills_req:
        if sk not in SUITE_REGISTRY:
            _emit_lines([f"ERROR=Unknown skill '{sk}'. Choose from: {','.join(SUITE_REGISTRY)}"])
            return 2

    target_roots = _resolve_platform_targets(platforms, args.target_dir, args.home_dir, args.project_dir)
    offline_dir = Path(args.offline_from).expanduser().resolve() if args.offline_from else None
    mode = "OFFLINE" if offline_dir else "ONLINE"

    results: List[str] = []
    errors: List[str] = []
    for plat, dest_root in target_roots.items():
        ok_count = 0
        for sk in skills_req:
            meta = SUITE_REGISTRY[sk]
            dst = dest_root / sk
            try:
                if offline_dir:
                    cand = offline_dir / sk
                    if not cand.is_dir() and sk == "veripilot" and (offline_dir / "scripts" / "vpilot.py").is_file():
                        cand = offline_dir
                    if not cand.is_dir():
                        raise FileNotFoundError(f"Offline source missing: {cand}")
                    _copy_skill_offline(cand, dst)
                else:
                    _install_skill_online(meta["repo"], meta["tag"], dst)
                ok_count += 1
            except Exception as exc:
                errors.append(f"{plat}/{sk}:{_trunc(str(exc), 60)}")
        results.append(f"{plat}:{ok_count}/{len(skills_req)}->{dest_root}")

    pins = ",".join(f"{sk}@{SUITE_REGISTRY[sk]['tag']}" for sk in skills_req)
    out = [
        f"INSTALL_STATUS={'OK' if not errors else 'PARTIAL_ERROR'} MODE={mode}",
        f"SKILLS_PINNED={pins}",
        *results[:8],
    ]
    if errors:
        out.append(f"ERRORS={'; '.join(errors[:3])}")
    _emit_lines(out)
    return 0 if not errors else 1


# ---------------------------------------------------------------------------
# Subcommand: doctor
# ---------------------------------------------------------------------------


def cmd_doctor(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    py_ok = sys.version_info >= (3, 9)

    git_bin = shutil.which("git")
    git_ver = "missing"
    git_ok = False
    if git_bin:
        gp = subprocess.run(["git", "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
        if gp.returncode == 0:
            git_ver = gp.stdout.strip()
            git_ok = True

    skills = discover_skills(root, getattr(args, "skills_dir", None))
    skill_lines: List[str] = []
    missing_or_bad: List[str] = []
    for sk, meta in SUITE_REGISTRY.items():
        info = skills[sk]
        if not info["installed"]:
            missing_or_bad.append(sk)
            skill_lines.append(f"SKILL_{sk.upper()}=MISSING (expected {meta['cli']})")
            continue
        cli_ok = True
        try:
            ast.parse(Path(info["cli_path"]).read_text(encoding="utf-8", errors="replace"), filename=info["cli_path"])
        except SyntaxError:
            cli_ok = False
            missing_or_bad.append(sk)
        skill_lines.append(f"SKILL_{sk.upper()}={'OK' if cli_ok else 'SYNTAX_ERR'}@{info['version']} path={info['path']}")

    bh_dir = root / ".bughunt"
    stale_sessions = 0
    if bh_dir.is_dir():
        stale_sessions = sum(1 for d in bh_dir.iterdir() if d.is_dir() and (d / "overlay").exists())
    excl_state = "NON_GIT"
    if _is_git_repo(root):
        proc = _run_git(root, ["rev-parse", "--git-path", "info/exclude"], timeout_s=10)
        if proc.returncode == 0 and proc.stdout.strip():
            raw_p = Path(proc.stdout.strip())
            ep = raw_p if raw_p.is_absolute() else (root / raw_p)
            excl_state = "OK" if (ep.is_file() and ".bughunt" in ep.read_text(encoding="utf-8", errors="replace")) else "NOT_EXCLUDED"

    healthy = py_ok and git_ok and not missing_or_bad
    remedy = (
        f"Run: python {Path(__file__).resolve()} install --platform antigravity"
        if missing_or_bad
        else "NONE"
    )
    lines = [
        f"DOCTOR_STATUS={'HEALTHY' if healthy else 'DEGRADED'}",
        f"PYTHON={py_ver} ({'OK' if py_ok else 'UPGRADE>=3.9'}) GIT={git_ver} ({'OK' if git_ok else 'MISSING'})",
        *skill_lines,
        f"GIT_EXCLUDE={excl_state} ACTIVE_OVERLAYS={stale_sessions}",
        f"REMEDY={remedy}",
    ]
    _emit_lines(lines)
    return 0 if healthy else 1


# ---------------------------------------------------------------------------
# Subcommand: log
# ---------------------------------------------------------------------------


def cmd_log(args: argparse.Namespace) -> int:
    s_dir = Path(args.s).resolve()
    if not s_dir.is_dir():
        _emit_lines([f"ERROR=Session directory not found: {s_dir}"])
        return 2
    status = _append_worklog(s_dir, args.status, args.entry or [])
    _emit_lines([f"LOG_STATUS=OK", f"WORKLOG={s_dir / 'worklog.md'}", f"STATUS={status}"])
    return 0


# ---------------------------------------------------------------------------
# Argument Parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="VeriPilot Suite Orchestrator & Installer CLI (stdlib only)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp_init = sub.add_parser("init", help="Initialize VeriPilot session and overlay workspace")
    sp_init.add_argument("--root", default=".", help="Target repository root")
    sp_init.add_argument("--skills-dir", default=None, help="Explicit parent folder containing VeriHunt skills")

    sp_route = sub.add_parser("route", help="3-layer intent + Git + file risk triage & causal plan")
    sp_route.add_argument("--root", default=".", help="Target repository root")
    sp_route.add_argument("--s", default=None, help="Optional VeriPilot session path")
    sp_route.add_argument("--prompt", required=True, help="User prompt in Thai or English")
    sp_route.add_argument("--changed-files", default="", help="Optional comma-separated changed file override")
    sp_route.add_argument("--skills-dir", default=None, help="Explicit skills directory")

    sp_hand = sub.add_parser("handoff", help="Apply verified stage output onto cumulative overlay & check Circuit Breaker")
    sp_hand.add_argument("--s", required=True, help="VeriPilot session path")
    sp_hand.add_argument("--skill", required=True, choices=list(CAUSAL_PRIORITY.keys()), help="Completed skill name")
    sp_hand.add_argument("--patch", default=None, help="Unified diff patch produced by stage")
    sp_hand.add_argument("--from-dir", default=None, help="Modified stage directory to sync into overlay")
    sp_hand.add_argument("--status", default="PASS", choices=["PASS", "FAIL", "HARNESS_BROKEN", "ENV_BROKEN"])
    sp_hand.add_argument("--findings", type=int, default=0, help="Confirmed findings count")
    sp_hand.add_argument("--tests-ran", type=int, default=0, help="Verification tests/probes executed")
    sp_hand.add_argument("--check-cmd", default=None, help="Optional command executed inside overlay to probe harness health")
    sp_hand.add_argument("--summary", default="", help="1-line stage summary")
    sp_hand.add_argument("--enforce-budget", action="store_true", help="Trip Circuit Breaker if chain exceeds 2 skills without confirmation")
    sp_hand.add_argument("--confirm-over-budget", action="store_true", help="Allow >2 skill chain when --enforce-budget is set")

    sp_fin = sub.add_parser("finalize", help="Export cumulative LF patch, verify git apply --check, clean temps")
    sp_fin.add_argument("--s", required=True, help="VeriPilot session path")
    sp_fin.add_argument("--clean", action="store_true", help="Remove temporary overlay/baseline/checkpoint folders")
    sp_fin.add_argument("--verify-cmd", default=None, help="Optional final check command inside overlay prior to cleanup")

    sp_inst = sub.add_parser("install", help="Install or update all 5 VeriHunt skills across agent platforms")
    sp_inst.add_argument("--platform", default="antigravity", help="Target platform(s): all,claude,antigravity,cursor,windsurf,roocode,cline")
    sp_inst.add_argument("--target-dir", default=None, help="Override destination directory")
    sp_inst.add_argument("--home-dir", default=None, help="Override home directory for global platform paths")
    sp_inst.add_argument("--project-dir", default=None, help="Override project directory for project-local platform paths")
    sp_inst.add_argument("--offline-from", default=None, help="Copy skills locally instead of cloning from GitHub")
    sp_inst.add_argument("--skills", default=None, help="Comma-separated subset of skills (default: all 5)")

    sp_doc = sub.add_parser("doctor", help="Check Python, Git, 5 skill engines, exclude rules & temp cleanliness")
    sp_doc.add_argument("--root", default=".", help="Target repository root")
    sp_doc.add_argument("--skills-dir", default=None, help="Explicit parent folder containing VeriHunt skills")

    sp_log = sub.add_parser("log", help="Update S/worklog.md status and append entries")
    sp_log.add_argument("--s", required=True, help="VeriPilot session path")
    sp_log.add_argument("--status", default=None, help="New Status line value")
    sp_log.add_argument("--entry", action="append", default=[], help="Entry text to append")

    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "init": cmd_init,
        "route": cmd_route,
        "handoff": cmd_handoff,
        "finalize": cmd_finalize,
        "install": cmd_install,
        "doctor": cmd_doctor,
        "log": cmd_log,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
