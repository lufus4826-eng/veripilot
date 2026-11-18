---
name: veripilot
description: Smart Router, Cumulative Overlay Orchestrator, and One-Command Installer for the VeriHunt Suite (VeriPR, VeriHunt, VeriSec, VeriPerf). Auto-triages user intent (TH/EN), Git state, and touched file risk, enforces Causal Execution Order, chains stages over a cumulative overlay workspace, stops cleanly on Circuit Breaker trips, and exports one conflict-free LF patch. (ตัวคัดเลือกสกิลอัตโนมัติ ตัวร้อยเรียงงานต่อเนื่องผ่านพื้นที่ซ้อนทับสะสม และตัวติดตั้งทั้งตระกูล VeriHunt ในคำสั่งเดียว — pilot, orchestrate, route, auto verify, install verihunt suite, เช็กโค้ดก่อนส่ง, ตรวจครบจบในคำสั่งเดียว)
---

# VeriPilot

Goal: Route any engineering verification request to the right VeriHunt suite skill(s), orchestrate multi-skill chains cleanly without context bloat or patch conflicts, and install/diagnose the entire 5-skill suite in one command.

## 4 Iron Engineering Laws (Non-Negotiable)
1. **Just-in-Time Skill Loading:** NEVER preload all sibling `SKILL.md` files (`veripr`, `verihunt`, `verisec`, `veriperf`). Call `read_file` on **ONLY** the active stage's `SKILL.md` right before executing that stage.
2. **Causal Execution Order:** Always execute multi-skill chains in strict causal order:
   **Correctness (`veripr` -> `verihunt`) -> Security (`verisec`) -> Performance (`veriperf`)**
   Never tune performance on buggy code or before security guards are in place.
3. **Cumulative Overlay Workspace (`S/overlay/`):** Stage `N+1` MUST inspect, test, and patch `S/overlay/` containing all verified changes from Stages `1..N` — never raw baseline source — so `finalize` outputs one conflict-free unified patch (`S/patches/veripilot-unified.patch`).
4. **Circuit Breaker:** If Stage 1 (or any stage) reports `HARNESS_BROKEN` / `ENV_BROKEN`, or a chain exceeds **2 skills** (`BUDGET_GATE=CONFIRM_OVER_2_SKILLS`), stop and ask the user before continuing. Never burn tokens on broken test environments.

## Default Parameters & Token Efficiency
`VP=<skill_dir>/scripts/vpilot.py` | `S=.bughunt/pilot-<YYYYMMDD-HHMMSS>/` | **CLI Output Cap:** every `vpilot.py` command emits `<= 12` lines.
- **Language:** Auto-match user prompt language (Thai or English; keep technical terms like *Causal Order*, *Cumulative Overlay*, *Circuit Breaker*, *Dual-Gate* in English).
- **Host Isolation:** NEVER modify host source files before explicit user approval. Work strictly inside `S/` (`.bughunt/` is auto-added to `.git/info/exclude` by `init`).
- **Lazy-Load References:** Read `references/routing-matrix.md` only if triage rules need clarification. Load `references/report-template.th.md` (TH) or `references/report-template.md` (EN) **ONLY in Phase 4**.

---

## Phase 0 — Workspace & Suite Discovery
1. Run chained discovery in one command:
   ```text
   python "<VP>" init --root . ; python "<VP>" doctor --root .
   ```
2. Capture `S`, `OVERLAY`, and installed skill paths. If any required sibling skill is missing (`DOCTOR_STATUS=DEGRADED`), immediately give the user the 1-command installer:
   ```text
   python "<VP>" install --platform antigravity
   ```
   and stop until installed.

## Phase 1 — Deterministic Triage & Causal Plan
1. Run the 3-layer router (Bilingual Intent + Real Git Status + Touched File Risk Scan):
   ```text
   python "<VP>" route --root . --s "$S" --prompt "<user_prompt>"
   ```
2. Inspect `PLAN`, `REORDERED`, `SEC_RISK`, `BUDGET_GATE`, `TARGET_SCOPE`, `CURRENT_SKILL_MD`, and `NEXT_TARGET_ROOT`:
   - **1–2 skills (`BUDGET_GATE=AUTO_PROCEED`):** Proceed straight to Phase 2.
   - **> 2 skills (`BUDGET_GATE=CONFIRM_OVER_2_SKILLS`):** Present the short causal plan (`PLAN`, why reordered/triggered, target scope) to the user before proceeding unless the user explicitly requested all skills in one run.

## Phase 2 — Stage Execution via Lazy Load
1. Call `read_file` on **ONLY** `CURRENT_SKILL_MD` (or `NEXT_SKILL_MD` from `handoff`).
2. Execute that skill's Dual-Gate workflow strictly against **`NEXT_TARGET_ROOT` (`S/overlay/`, NEVER raw host root)** using `NEXT_STAGE_ARGS` (`--root "$NEXT_TARGET_ROOT"`) and narrowed `TARGET_SCOPE`:
   - Collect the stage's verified patch (`--patch`) or modified workspace (`--from-dir`), finding count, test count, and status (`PASS` | `HARNESS_BROKEN` | `ENV_BROKEN`).

## Phase 3 — Overlay Handoff & Circuit Check
1. Commit the stage's verified work into `S/overlay/` and check the Circuit Breaker:
   ```text
   python "<VP>" handoff --s "$S" --skill <current_skill> --patch <stage_patch> --status <PASS|HARNESS_BROKEN> --findings <N> --tests-ran <N> --summary "<1-line summary>"
   ```
2. Branch strictly on `vpilot.py handoff` output:
   - **`CIRCUIT_BREAKER=TRIPPED`:** Stop immediately! Report `REASON`, failing command/harness symptom, and ask the user how to fix the environment or narrow scope.
   - **`NEXT_SKILL!=NONE`:** Loop back to **Phase 2**, lazy-loading **ONLY** `NEXT_SKILL_MD` and targeting **`NEXT_TARGET_ROOT`** (`NEXT_STAGE_ARGS`).
   - **`NEXT_SKILL=NONE`:** Proceed to **Phase 4**.

## Phase 4 — Unified Patch & Executive Summary
1. Run finalization + verification + cleanup in one command **AND** parallel `read_file` on **ONLY** `references/report-template.th.md` (TH) or `references/report-template.md` (EN):
   ```text
   python "<VP>" finalize --s "$S" --clean
   ```
2. Write `S/pilot-report.md` from the loaded template using stage digests and `S/patches/veripilot-unified.patch`.
3. Present a concise Executive Summary in chat (Causal Plan executed, findings & verified fixes per stage, `GIT_APPLY`, `CLEANLINESS`, `S/patches/veripilot-unified.patch`, and `S/pilot-report.md` paths) and ask before applying the unified patch to the host repo.

## Post-Report Host Application (Explicit Approval Only)
Run `git apply <S>/patches/veripilot-unified.patch` -> run final suite verification -> append Section 6 `"Applied Patch Log"` in `S/pilot-report.md`.
