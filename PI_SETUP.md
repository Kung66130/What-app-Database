# Raspberry Pi 5 Deployment

ไฟล์นี้คือแนวทาง deploy MVP ไป Raspberry Pi 5 โดยตรง

## แนวคิด

- ใช้ `sqlite3` ในเครื่อง Pi ได้เลย เหมาะกับ MVP และงานภายใน
- รันเป็น `systemd service` เพื่อให้บูตแล้วขึ้นอัตโนมัติ
- ถ้าจะเรียกจากเครื่องอื่นในวง LAN ให้ bind ที่ `0.0.0.0`

## โครงที่แนะนำบน Pi

```text
/home/pi/whatsapp-agent
├── app/
├── data/
├── sample_data/
├── main.py
└── deploy/wa-agent.service
```

## ติดตั้งแบบเร็ว

1. คัดลอกโปรเจ็กต์ไปที่ Pi เช่น `/home/pi/whatsapp-agent`
2. เข้า shell บน Pi แล้วรัน:

```bash
cd /home/pi/whatsapp-agent
python3 main.py init-db
python3 main.py import ./sample_data/uk_team_export.txt --group "UK Team"
python3 main.py serve
```

ถ้าต้องการให้เครื่องอื่นเรียกได้:

```bash
WA_AGENT_HOST=0.0.0.0 WA_AGENT_PORT=8080 python3 main.py serve
```

## ติดตั้งเป็น systemd service

แก้ path ใน `deploy/wa-agent.service` ให้ตรงกับเครื่องจริงก่อน โดยเฉพาะ:

- `User`
- `WorkingDirectory`
- `WA_AGENT_DATA_DIR`
- `ExecStart`

จากนั้นติดตั้ง:

```bash
sudo cp deploy/wa-agent.service /etc/systemd/system/wa-agent.service
sudo systemctl daemon-reload
sudo systemctl enable wa-agent
sudo systemctl start wa-agent
sudo systemctl status wa-agent
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
