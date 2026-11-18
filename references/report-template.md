# VeriPilot Executive Verification Report

- **Session ID:** `<SNAME>`
- **Project Root:** `<ROOT>`
- **Execution Mode:** `<MODE>` (`SINGLE` | `CHAIN`)
- **Causal Plan:** `<PLAN>` (Requested Order: `<REQUESTED_ORDER>`, Reordered: `<REORDERED>`)
- **Circuit Breaker:** `<CIRCUIT_BREAKER>` (`OK` | `TRIPPED` — `<REASON>`)
- **Unified Patch:** `<UNIFIED_PATCH>` (`git apply --check`: `<GIT_APPLY>`)
- **Host Workspace Cleanliness:** `<CLEANLINESS>`

---

## 1. 3-Layer Triage & Causal Routing Rationale

| Signal Layer | Observed Evidence | Routing Impact |
|---|---|---|
| **Layer 1: User Intent** | `<intent_keywords>` | `<intent_skills>` |
| **Layer 2: Git State** | `<git_state_summary>` | `<git_impact>` |
| **Layer 3: Touched File Risk** | `<risk_files_and_tokens>` (`SEC_RISK=<SEC_RISK>`) | `<risk_impact>` |

**Target Scope:** `<TARGET_SCOPE>`

---

## 2. Stage-by-Stage Causal Execution Summary

| Stage | Skill | Status | Findings | Tests / Probes Ran | Stage Patch | Key Outcome |
|---|---|---|---:|---:|---|---|
| 1 | `<skill_1>` | `<status_1>` | `<findings_1>` | `<tests_1>` | `<patch_1>` | `<summary_1>` |

---

## 3. Cumulative Overlay Verification & Circuit Breaker Log

- **Overlay Consistency:** Stage N+1 operated directly on top of verified fixes from Stages 1..N inside `S/overlay/`.
- **Post-Merge Verification:** `<verify_cmd_status>`
- **Circuit Breaker Events:** `<circuit_breaker_notes_or_None>`

---

## 4. Unified Cross-Platform Patch (`veripilot-unified.patch`)

- **Path:** `<UNIFIED_PATCH>`
- **Line Endings:** Pure LF (`\n`, zero `\r` bytes)
- **Modified Files:** `<FILES_MODIFIED>`
- **Host Compatibility (`git apply --check --ignore-space-change --ignore-whitespace`):** `<GIT_APPLY>`

```diff
<unified_patch_preview_or_summary>
```

---

## 5. Cleanliness & Host Isolation Verification

- **Baseline vs. Final Snapshot:** `<CLEANLINESS>`
- **Host Source Files Modified Before Approval:** `0` (all edits confined to `.bughunt/` until explicit approval)

---

## 6. Applied Patch Log (Populated Only After Explicit User Approval)

- `None`
