# Raspberry Pi 5 Deployment

ไฟล์นี้คือแนวทาง deploy MVP ไป Raspberry Pi 5 แบบรันใน container

## แนวคิด

- ใช้ `sqlite3` ใน volume ของเครื่อง Pi ได้เลย เหมาะกับ MVP และงานภายใน
- รันผ่าน `docker compose` เพื่อให้จัดการ container ได้ง่าย
- ถ้าต้องการใช้ฟีเจอร์ AI Agent (RAG) ให้ติดตั้ง **Ollama** บนเครื่อง Pi เพิ่มเติม (ดูรายละเอียดด้านล่าง)
- ถ้าต้องการให้เครื่องอื่นในวง LAN เรียกได้ ให้ map port `8080:8080`

## โครงที่แนะนำบน Pi

```text
/home/admin/what-app-database
├── app/
├── data/
├── sample_data/
├── Dockerfile
└── docker-compose.yml
```

## ติดตั้งแบบเร็ว

1. clone repo ลง Pi
2. เข้า shell บน Pi แล้วรัน:

```bash
cd /home/admin
git clone https://github.com/Kung66130/What-app-Database.git what-app-database
cd /home/admin/what-app-database
mkdir -p data
docker compose up -d --build
```

เช็กสถานะ:

```bash
docker compose ps
docker compose logs -n 100
```

## import ข้อมูลตัวอย่างหรือไฟล์จริง

ถ้าต้องการ import sample data ผ่าน container:

```bash
cd /home/admin/what-app-database
docker compose exec whatsapp-agent python main.py import ./sample_data/uk_team_export.txt --group "UK Team"
```

หรือส่งไฟล์จริงเข้า API:

```bash
curl -X POST http://127.0.0.1:8080/imports/whatsapp \
  -H 'Content-Type: application/json' \
  --data-binary @payload.json
```

## อัปเดตเวอร์ชันจาก GitHub

```bash
cd /home/admin/what-app-database
git pull
docker compose up -d --build
```

## ทดสอบ

บน Pi:

```bash
curl http://127.0.0.1:8080/health
```

จากเครื่องอื่นในวง LAN:

```bash
curl http://<PI_IP>:8080/health
```

## การตั้งค่า AI Agent (Ollama)

แอปนี้รองรับการตอบคำถามแบบ AI โดยใช้ **Ollama** รันบนเครื่อง Pi 5:

1. **ติดตั้ง Ollama บน Pi 5:**
   ```bash
   curl -fsSL https://ollama.com/install.sh | sh
   ```

2. **ดาวน์โหลดโมเดลที่แนะนำ (llama3.2):**
   ```bash
   ollama pull llama3.2
   ```
   *หมายเหตุ: Pi 5 รัน llama3.2 ได้รวดเร็วและประหยัด RAM*

3. **ตรวจสอบว่า Ollama รันอยู่:**
   ```bash
   curl http://127.0.0.1:11434
   ```
   (ถ้าขึ้นว่า `Ollama is running` แสดงว่าพร้อมใช้งาน)

เมื่อ Ollama พร้อมแล้ว คำสั่ง `ask` หรือ `/agent/ask` จะเปลี่ยนจากการค้นหาข้อความเฉยๆ เป็นการสรุปคำตอบด้วย AI ทันทีครับ

## การตั้งค่าดึงข้อมูลอัตโนมัติ (Live Sync)

โปรเจ็กต์นี้รองรับการดึงข้อมูลจากกลุ่มและแชทส่วนตัวอัตโนมัติผ่าน **Evolution API**:

1.  **รันระบบด้วย Docker Compose**:
    ```bash
    docker compose up -d
    ```
    *(ระบบจะรัน 3 ตัว: whatsapp-agent, evolution-api, และ redis)*

2.  **สร้าง Instance และสแกน QR Code**:
    - เข้าไปที่หน้าจัดการ Evolution API (Default: `http://<PI_IP>:8081`)
    - หรือใช้โปรแกรมจัดการเช่น **Evolution Manager**
    - สร้าง Instance ใหม่ (เช่นชื่อ `my-account`)
    - สแกน QR Code ด้วยแอป WhatsApp ในมือถือของคุณ

3.  **ตั้งค่า Webhook (ถ้ายังไม่ได้ตั้งใน config)**:
    - ตรวจสอบว่า Webhook URL ชี้ไปที่ `http://whatsapp-agent:8080/webhooks/whatsapp`
    - เปิดใช้งาน Event `MESSAGES_UPSERT`

เมื่อเชื่อมต่อสำเร็จ ทุกข้อความที่ไหลเข้าใน WhatsApp (รวมถึงในกลุ่ม) จะถูกบันทึกลง SQLite โดยอัตโนมัติใน Batch ที่ชื่อว่า `LIVE_SYNC` ครับ

## หมายเหตุเพิ่มเติม
