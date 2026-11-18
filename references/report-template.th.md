# รายงานสรุปผลการตรวจสอบรวม VeriPilot (Executive Report)

- **รหัสเซสชัน (Session ID):** `<SNAME>`
- **โฟลเดอร์โปรเจกต์ (Project Root):** `<ROOT>`
- **โหมดการทำงาน (Execution Mode):** `<MODE>` (`SINGLE` | `CHAIN`)
- **ลำดับแผนเหตุและผล (Causal Plan):** `<PLAN>` (ลำดับที่ผู้ใช้พิมพ์: `<REQUESTED_ORDER>`, จัดเรียงใหม่: `<REORDERED>`)
- **สถานะตัวตัดวงจร (Circuit Breaker):** `<CIRCUIT_BREAKER>` (`OK` | `TRIPPED` — `<REASON>`)
- **ไฟล์แพตช์รวมแผ่นเดียว (Unified Patch):** `<UNIFIED_PATCH>` (`git apply --check`: `<GIT_APPLY>`)
- **ความสะอาดของโปรเจกต์หลัก (Cleanliness):** `<CLEANLINESS>`

---

## 1. ผลการวิเคราะห์เส้นทาง 3 ชั้น (3-Layer Triage & Causal Routing)

| ชั้นสัญญาณ (Signal Layer) | หลักฐานที่ตรวจพบจริง | ผลต่อการจัดแผนรัน |
|---|---|---|
| **ชั้นที่ 1: เจตนาจากคำสั่งผู้ใช้** | `<intent_keywords>` | `<intent_skills>` |
| **ชั้นที่ 2: สถานะ Git จริง** | `<git_state_summary>` | `<git_impact>` |
| **ชั้นที่ 3: ความเสี่ยงของไฟล์ที่แตะต้อง** | `<risk_files_and_tokens>` (`SEC_RISK=<SEC_RISK>`) | `<risk_impact>` |

**ขอบเขตไฟล์เป้าหมาย (`TARGET_SCOPE`):** `<TARGET_SCOPE>`

---

## 2. สรุปผลการรันแยกตามด่าน (Stage-by-Stage Causal Summary)

| ด่าน | สกิล | สถานะ | ประเด็นที่พบ | เทสต์/โพรบที่รัน | แพตช์ประจำด่าน | สรุปผลสำคัญ |
|---|---|---|---:|---:|---|---|
| 1 | `<skill_1>` | `<status_1>` | `<findings_1>` | `<tests_1>` | `<patch_1>` | `<summary_1>` |

---

## 3. การส่งไม้ต่อบนพื้นที่ซ้อนทับสะสม และสถานะตัวตัดวงจร

- **ความต่อเนื่องของพื้นที่ซ้อนทับ (`Cumulative Overlay`):** ด่านถัดไปทำงานบนโค้ดที่ผ่านการแก้และยืนยันแล้วของด่านก่อนหน้าใน `S/overlay/` ไม่ได้เริ่มจากโค้ดดิบซ้ำ
- **ผลตรวจซ้ำหลังรวมแพตช์:** `<verify_cmd_status>`
- **เหตุการณ์ตัวตัดวงจร (Circuit Breaker):** `<circuit_breaker_notes_or_ไม่มี>`

---

## 4. ไฟล์แพตช์รวมแผ่นเดียว (`veripilot-unified.patch`)

- **พาธไฟล์แพตช์:** `<UNIFIED_PATCH>`
- **รูปแบบขึ้นบรรทัดใหม่:** Pure LF (`\n` ล้วน ปราศจาก `\r`)
- **รายการไฟล์ที่ถูกแก้ไข:** `<FILES_MODIFIED>`
- **ผลตรวจซ้อนทับกับโปรเจกต์หลัก (`git apply --check`):** `<GIT_APPLY>`

```diff
<unified_patch_preview_or_summary>
```

---

## 5. การยืนยันความสะอาดและการแยกพื้นที่ปลอดภัย (Cleanliness & Host Isolation)

- **ผลเทียบ Snapshot ก่อน–หลัง:** `<CLEANLINESS>`
- **ไฟล์ซอร์สโค้ดหลักที่ถูกแก้ไขก่อนได้รับอนุญาต:** `0` ไฟล์ (งานทั้งหมดถูกกักไว้ใน `.bughunt/` อย่างสมบูรณ์)

---

## 6. บันทึกการนำแพตช์ไปใช้จริง (Applied Patch Log — บันทึกหลังผู้ใช้ยืนยัน)

- `ไม่มี`
