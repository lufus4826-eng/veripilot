# VeriPilot Live Showcase Report (`examples/fintech_pilot_demo`)

> Generated cleanly by `python -B examples/fintech_pilot_demo/run_demo.py` across all 4 required orchestration scenarios (`PILOT-1`..`PILOT-4`).

## 1. Executive Summary Matrix (EN / TH)

| Case ID | Scenario | Observed Routing / Action | Empirical Outcome |
|---|---|---|---|
| **PILOT-1** | Broad TH pre-submit prompt on payment + receipt diff (`ช่วยเช็กโค้ดก่อนส่งให้หน่อย เพิ่งแก้ระบบชำระเงินกับใบเสร็จไป`) | `3-Layer Triage`: `SEC_RISK=HIGH` -> `veripr -> verisec` | Unified patch `826`B, `GIT_APPLY=OK`, `VERIFY=PASS`, `CLEAN (0 stray files outside .bughunt/)` |
| **PILOT-2** | Mixed causal-order prompt (`อยากจูนความเร็ว เช็กช่องโหว่ และตรวจ PR ในประโยคเดียว`) | Requested `veriperf,verisec,veripr` -> Reordered `veripr -> verisec -> veriperf` (`reordered=True`) | 3 cumulative fixes in `S/overlay/` (`+99.7%` batch speedup), `OK (3-stage patch cleanly applied & tested)` |
| **PILOT-3** | Broken test syntax in Stage 1 (`test_broken_syntax.py`) | `handoff --check-cmd` detected `SyntaxError` | `CIRCUIT_BREAKER=TRIPPED` (`REASON=HARNESS_BROKEN`), `NEXT_SKILL=NONE` |
| **PILOT-4** | Offline 6-platform install + `doctor` health check | `install --platform all --offline-from` + `doctor` | `INSTALL=OK` (6/6 (claude, antigravity, cursor, windsurf, roocode, cline)), `DOCTOR=HEALTHY` |

---

## 2. สรุปผลการสาธิตทั้ง 4 สถานการณ์ (ฉบับภาษาไทย)

1. **`PILOT-1` (Auto-Triage จากสถานะ Git + ความเสี่ยงไฟล์):** ผู้ใช้พิมพ์คำสั่งกว้างๆ ว่าจะเช็กโค้ดก่อนส่งบนสาขาที่แตะ `payment_service.py` และ `receipt_api.py` เอนจินตรวจพบความเสี่ยงด้านสิทธิ์/การเงิน (`SEC_RISK=HIGH`) จึงจัดแผน **`veripr -> verisec`** อัตโนมัติ แก้ทั้งบัคลูกโซ่ `None` ใน `calculate_fee` และช่องโหว่ IDOR ใน `refund_payment` ซ้อนทับกันจนออกเป็นแพตช์ LF ล้วนแผ่นเดียวที่ `git apply --check -> OK`
2. **`PILOT-2` (Causal Execution Order + Cumulative Overlay):** แม้ผู้ใช้จะขอจูนความเร็วก่อนเช็กช่องโหว่และตรวจ PR เอนจินบังคับจัดเรียงใหม่เป็น **`veripr -> verisec -> veriperf`** (`REORDERED=True`) ทำให้ด่าน `verisec` ทำงานต่อบนโค้ดที่แก้ ripple แล้ว และด่าน `veriperf` จูน `reconcile_ledger_batch` (`O(N^2)` -> `O(N)`, เร็วขึ้น `+99.7%`) ทับบนโค้ดที่มีตัวเช็กสิทธิ์ IDOR แล้วอย่างสมบูรณ์
3. **`PILOT-3` (Circuit Breaker ตัดวงจรเมื่อ Harness พัง):** เมื่อด่านแรกเจอ `SyntaxError` ในไฟล์เทสต์ ตัวตัดวงจรสั่งหยุดทันที (`CIRCUIT_BREAKER=TRIPPED`, `REASON=HARNESS_BROKEN`, `NEXT_SKILL=NONE`) ป้องกันการเผา Token ข้ามไปด่านที่ 2 และ 3
4. **`PILOT-4` (One-Command Suite Installer & Doctor):** ทดสอบติดตั้งทั้ง 5 สกิลแบบออฟไลน์ลงครบทั้ง **6 แพลตฟอร์ม** (`claude`, `antigravity`, `cursor`, `windsurf`, `roocode`, `cline`) พร้อมตรวจด้วย `vpilot.py doctor` ได้สถานะ **`HEALTHY`** ครบทุกตัว
