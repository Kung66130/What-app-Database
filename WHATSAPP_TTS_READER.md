# WhatsApp TTS Reader (Node)

## Pair / Login

### วิธีที่แนะนำ: Pairing Code (Link with phone number)

```powershell
cd "C:\Project\Whatapp Agent"
npm run pair:code -- 669XXXXXXXX
```

บนมือถือ:
1) WhatsApp -> Linked devices (อุปกรณ์ที่เชื่อมโยง) -> Link a device (เชื่อมโยงอุปกรณ์)
2) กด **Link with phone number instead**
3) ใส่รหัส 8 หลัก “ล่าสุด” ที่โปรแกรมพิมพ์ออกมา (โค้ดจะเปลี่ยนทุก 3 นาที)

ถ้าขึ้น “รหัสไม่ถูก” ให้ดูว่าโค้ดที่ใส่เป็น “โค้ดล่าสุด” ตามเวลาที่แสดงหรือไม่ (อย่าใช้โค้ดเก่า)

### วิธีสำรอง: QR

```powershell
cd "C:\Project\Whatapp Agent"
npm run pair:qr
```

## Run reader

```powershell
cd "C:\Project\Whatapp Agent"
npm start
```

## จำกัดให้ฟังแค่บางกลุ่ม (เช่น กลุ่มเดียว)

ตั้งค่า env `TARGET_GROUP_NAME` เป็นชื่อกลุ่มแบบ “ตรงตัว” (คั่นหลายกลุ่มด้วย comma):

```powershell
$env:TARGET_GROUP_NAME="My Group Name"
npm start
```

หรือใส่ใน `.env`:

```text
TARGET_GROUP_NAME="My Group Name"
```

