# VeriPilot 3-Layer Routing Matrix & Causal Orchestration Rules

This reference documents the deterministic triage logic implemented in `scripts/vpilot.py route` and `handoff`.

## 1. Layer 1 — Bilingual Intent Dictionary (TH + EN)

| Skill | Thai Keywords | English Keywords |
|---|---|---|
| **VeriPR** (`veripr`) | รีวิว, พร้อมส่ง, กระทบ, ก่อนส่ง, ก่อนคอมมิต, ลูกโซ่, เช็กโค้ดก่อนส่ง, ตรวจโค้ดก่อนส่ง, ส่งงาน | `pr`, `pre-commit`, `commit`, `diff`, `ripple`, `contract`, `schema`, `caller`, `pull request` |
| **VeriHunt** (`verihunt`) | หาบัค, ไล่บัค, พัง, รวน, เสถียร, จับผิด, บัค | `bug`, `hunt`, `crash`, `stability`, `edge case`, `qa`, `exception`, `race`, `audit` |
| **VeriSec** (`verisec`) | ช่องโหว่, สิทธิ์รั่ว, ข้ามสิทธิ์, ความปลอดภัย, แฮก, หลุดสิทธิ์, พังสิทธิ์ | `sec`, `security`, `idor`, `bola`, `auth`, `authorization`, `vulnerability`, `mass assignment`, `double spend`, `bypass`, `exploit` |
| **VeriPerf** (`veriperf`) | ช้า, อืด, กินแรม, จูนความเร็ว, ความเร็ว, ประสิทธิภาพ, คอขวด, เร็วขึ้น | `perf`, `performance`, `latency`, `optimize`, `speed`, `slow`, `memory`, `bottleneck`, `n+1`, `benchmark`, `profile` |

`vpilot.py route` also tracks the first appearance position of each matched keyword group in the prompt (`requested_order`) so reordering into causal order is explicitly logged (`REORDERED=True|False`).

## 2. Layer 2 — Real Git State Signal

`vpilot.py route` inspects the repository at `--root`:
1. Uncommitted, staged, or untracked non-ignored files (`git status --porcelain`, ignoring `.bughunt/`).
2. Multi-commit feature branch divergence via `git merge-base <trunk> HEAD`.
3. When local changes or branch divergence exist and the user gives a broad check/review prompt (e.g., `"เช็กโค้ดก่อนส่ง"`, `"check before commit"`), `veripr` is activated with `TARGET_SCOPE` narrowed to the modified files.

## 3. Layer 3 — Touched File Risk Scan

When touched files exist (from Git or `--changed-files`), `vpilot.py` scans filenames and file contents:
- **Security-sensitive paths:** `payment`, `pay`, `auth`, `login`, `token`, `jwt`, `session`, `receipt`, `invoice`, `vault`, `wallet`, `account`, `user`, `role`, `perm`, `permission`, `admin`, `checkout`, `refund`, `transfer`, `billing`, `order`
- **Security-sensitive code tokens:** `requester_id`, `owner_id`, `user_id`, `account_id`, `is_admin`, `authorize`, `permission`, `refund`, `transfer`, `withdraw`, `cursor.execute`, `SELECT `, `UPDATE `, `DELETE `, `INSERT `, `jwt`, `secret`, `token`

If sensitive filenames or code tokens are matched alongside a change-verification workflow (`veripr` or `verihunt`), `SEC_RISK=HIGH` is raised and `verisec` is **automatically appended** to the plan so business-logic & authorization holes are caught before shipping.

## 4. Causal Execution Order & Scope Narrowing

Every selected set of skills is sorted strictly by `CAUSAL_PRIORITY`:
1. `veripr` — Pre-commit/PR differential check & 1-hop ripple / API schema guard
2. `verihunt` — Deep correctness, edge-case & concurrency bug hunt
3. `verisec` — Business-logic, IDOR/BOLA, auth guard & secret redaction audit
4. `veriperf` — Statistical `p50`/`p95`/memory optimization (`>= 15%` speedup Dual-Gate)

**Rule:** Never run `veriperf` before `veripr`/`verihunt`/`verisec`; fixing a correctness or authorization guard afterward frequently alters hot-path execution profiles.

## 5. Circuit Breaker Conditions

`vpilot.py handoff` immediately trips `CIRCUIT_BREAKER=TRIPPED` and sets `NEXT_SKILL=NONE` when:
1. `--status HARNESS_BROKEN` or `--status ENV_BROKEN` is reported by any stage.
2. `--check-cmd` fails inside `S/overlay/` with harness breakdown patterns (`SyntaxError`, `IndentationError`, `ModuleNotFoundError`, `ImportError`, `collection error`, `0 tests ran`, `ENOENT`, `compilation failed`).
3. `--enforce-budget` is active and the pipeline exceeds 2 skills without explicit `--confirm-over-budget`.
