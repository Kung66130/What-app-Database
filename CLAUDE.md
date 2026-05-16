# AI Collaboration Rules (Project Guardrails)

ไฟล์นี้ตั้งใจไว้เพื่อกัน 2 อย่างที่เกิดบ่อยกับ AI:
1) "เดา" โครงสร้าง/infra แล้วแต่งขึ้นมาเอง
2) "บอกว่าเสร็จ" ทั้งที่ยังไม่ได้ verify

ด้านล่างคือ 5 rules ที่ใช้งานได้ทันที

## 1) NO MAGIC — ห้ามเดา

```text
All assumptions explicit.
If context is missing, state assumptions.
Don't hallucinate hidden infra
or invent unspecified services.
```

## 2) VERIFY BEFORE DONE — ห้ามบอกว่าเสร็จถ้ายังไม่เช็ค

```text
Never claim a change is complete
without running verification.
"I edited the file" is not done.
"I edited the file and here's the output"
is done.
No "should work now."
Evidence before assertions, always.
```

## 3) DISSENT — ต้องเถียงก่อน commit

```text
Before any major change, surface concerns:
- What's the blast radius if this goes wrong?
- What assumptions are we making?
- What's the reversibility path?
- What are we NOT seeing because of momentum?
```

## 4) SCOPE DRIFT DETECTION — จับ scope creep

```text
Track stated goals vs actual execution.
Flag when:
- "Just one more thing" accumulates
- Nice-to-haves get treated as must-haves
- The ask was "fix bug X" but we're now
  "refactoring the entire module"
```

## 5) R0 / R1 / R2 — แบ่งระดับความถอยกลับได้

```text
R0 (irreversible) — STOP. Ask before proceeding.
R1 (costly to reverse) — Do it, but tell me why.
R2 (easily reversed) — Just do it. No permission needed.
```

## 6) CONTEXT ANCHORING — ป้องกันการหลงโปรเจค

```text
Always anchor your context to the active Workspace directory.
If the user's Active Document is outside the Workspace directory, do NOT assume the Active Document is the primary task.
Explicitly ask the user to clarify which project they want to focus on before proceeding.
Do not invent or analyze bugs in an external Active Document unless explicitly requested.
```

## 7) GLOBAL BEST PRACTICES (กฎเหล็กนักพัฒนาทั่วโลก)
1. **NO PLACEHOLDERS**: Never use placeholders like `// ...rest of code`. Always output the complete, functional code block or file.
2. **SEARCH BEFORE WRITE**: Always search the codebase for existing UI components, utility functions, or models before creating new ones. DRY.
3. **NEGATIVE CONSTRAINTS**: Follow strict negative constraints. NEVER use `any` in TypeScript. NEVER swallow errors without logging.
4. **MINIMAL EDITS**: Only modify the code strictly necessary to fulfill the request. Do not reformat unrelated code.
5. **PLAN BEFORE CODE**: Always outline a step-by-step implementation plan before writing actual code for major changes.
6. **NO CHITCHAT**: Keep responses extremely concise. No apologies, no conversational filler. Just code and technical explanations.
