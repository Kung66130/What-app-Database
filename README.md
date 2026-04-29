# WhatsApp Agent MVP

โปรเจ็กต์นี้คือ MVP ของระบบตามแผน `WhatsApp Chat Database & AI Agent System` แต่ทำให้รันได้จริงโดยไม่ต้องติดตั้ง dependency เพิ่ม ใช้ `sqlite3` และ `http.server` จาก Python standard library และตอนนี้จัดโครงให้เหมาะกับการเอาไปรันบน Raspberry Pi 5 ได้แล้ว

## ความสามารถตอนนี้

- import ไฟล์ WhatsApp export (`.txt`) เข้า SQLite
- parse ข้อความหลายบรรทัด และแยก `text` / `system` / `media`
- deduplicate ด้วย `source_hash`
- ค้นหาข้อความตามคำ, คน, กลุ่ม, ช่วงวันที่
- endpoint สำหรับถามตอบแบบ deterministic พร้อม citations ของข้อความต้นทาง
- local HTTP API และ CLI

## โครงสร้างหลัก

- `main.py` จุดเข้าใช้งาน CLI
- `app/parser.py` ตัว parse ไฟล์ WhatsApp export
- `app/db.py` schema และการเชื่อมต่อ SQLite
- `app/services.py` ingestion, search, และ answer logic
- `app/server.py` local JSON API
- `sample_data/uk_team_export.txt` ไฟล์ตัวอย่างสำหรับทดสอบ
- `deploy/wa-agent.service` ตัวอย่าง systemd service สำหรับ Raspberry Pi
- `PI_SETUP.md` คู่มือติดตั้งบน Raspberry Pi 5

## เริ่มใช้งาน

```powershell
cd C:\Project\Whatapp Agent
C:\Users\kung6\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe .\main.py init-db
C:\Users\kung6\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe .\main.py import .\sample_data\uk_team_export.txt --group "UK Team"
```

ค้นหา:

```powershell
C:\Users\kung6\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe .\main.py search --q "SKU-001" --group "UK Team"
```

ถาม agent:

```powershell
C:\Users\kung6\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe .\main.py ask "ใครสั่งสินค้า SKU-001 ครั้งล่าสุด" --group "UK Team"
```

เปิด API server:

```powershell
C:\Users\kung6\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe .\main.py serve
```

Server จะฟังที่ `http://127.0.0.1:8080`

## เป้าหมาย Raspberry Pi 5

ตัวนี้เหมาะกับ Pi มากกว่า Render ในสถานะปัจจุบัน เพราะ:

- ใช้ SQLite local ได้ตรง ๆ
- ไม่มี dependency หนัก
- รันเป็น `systemd` ได้ง่าย
- ไม่ต้องกังวลเรื่อง ephemeral filesystem แบบแพลตฟอร์ม cloud

ดูขั้นตอน deploy เพิ่มที่ [PI_SETUP.md](C:/Project/Whatapp%20Agent/PI_SETUP.md)

## API ที่มี

- `GET /health`
- `GET /groups`
- `GET /imports`
- `GET /messages/search?q=SKU-001&group_name=UK%20Team`
- `POST /imports/whatsapp`
- `POST /agent/ask`

ตัวอย่าง `POST /imports/whatsapp`

```json
{
  "group_name": "UK Team",
  "file_name": "uk_team_export.txt",
  "content": "15/03/2025, 09:34 - John Smith: Please order 200 units of SKU-001"
}
```

ตัวอย่าง `POST /agent/ask`

```json
{
  "question": "มีใครพูดถึง shipment delay บ้าง",
  "group_name": "UK Team",
  "limit": 5
}
```

## ข้อจำกัดปัจจุบัน

- ยังไม่ใช้ FastAPI/PostgreSQL/pgvector เพราะ runtime นี้ไม่มี package เหล่านั้นให้รันตรง ๆ
- `agent/ask` ยังเป็น deterministic answer builder ไม่ใช่ LLM จริง
- ยังไม่มี auth และ dashboard

## ทางอัปเกรดถัดไป

1. เปลี่ยน storage จาก SQLite เป็น PostgreSQL
2. ย้าย HTTP layer ไป FastAPI
3. เพิ่ม embeddings และ semantic search
4. ต่อ LLM จริงสำหรับ translation และ answer synthesis
5. เพิ่ม dashboard และ role-based access
