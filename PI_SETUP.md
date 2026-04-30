# Raspberry Pi 5 Deployment

ไฟล์นี้คือแนวทาง deploy MVP ไป Raspberry Pi 5 แบบรันใน container

## แนวคิด

- ใช้ `sqlite3` ใน volume ของเครื่อง Pi ได้เลย เหมาะกับ MVP และงานภายใน
- รันผ่าน `docker compose` เพื่อให้จัดการ container ได้ง่าย
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

## หมายเหตุ

- ตอนนี้ยังไม่มี auth ถ้าจะเปิดให้คนอื่นในวง network ใช้จริง ควรใส่ reverse proxy หรือ token ก่อน
- ถ้าข้อมูลเริ่มโตมากหรือมีหลายคนใช้งานพร้อมกัน ควรขยับจาก SQLite ไป PostgreSQL ในรอบถัดไป
- ข้อมูลฐานจะอยู่ใน `./data` บนเครื่อง Pi ผ่าน bind mount
