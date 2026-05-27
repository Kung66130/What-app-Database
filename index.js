require('dotenv').config();
const fs = require('fs');
const os = require('os');
const path = require('path');
const https = require('https');
const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const googleTTS = require('google-tts-api');
const sound = require('sound-play');

// Create a temporary directory to store downloaded speech audio files
const tempDir = path.join(__dirname, 'temp');
if (!fs.existsSync(tempDir)) {
    fs.mkdirSync(tempDir, { recursive: true });
}

// Queue system to manage sequential audio playback (avoids voices overlapping)
class AudioQueue {
    constructor() {
        this.queue = [];
        this.isPlaying = false;
    }

    // Add a text to the speech queue
    enqueue(text) {
        console.log(`[Queue] Added message to queue: "${text}"`);
        this.queue.push(text);
        this.processQueue();
    }

    // Process the next item in the queue
    async processQueue() {
        if (this.isPlaying || this.queue.length === 0) {
            return;
        }

        this.isPlaying = true;
        const text = this.queue.shift();

        try {
            console.log(`[TTS] Processing text: "${text}"`);
            const filePath = await this.generateSpeechFile(text);
            console.log(`[Audio] Playing audio...`);
            await sound.play(filePath);
            console.log(`[Audio] Playback finished.`);
            
            // Clean up the temporary audio file after playing
            try {
                fs.unlinkSync(filePath);
            } catch (err) {
                console.error(`[Cleanup] Failed to delete temp file: ${filePath}`, err);
            }
        } catch (error) {
            console.error('[Queue Error]', error);
        } finally {
            this.isPlaying = false;
            // Introduce a short delay between messages
            setTimeout(() => {
                this.processQueue();
            }, 1000);
        }
    }

    // Download TTS audio and return the file path
    generateSpeechFile(text) {
        return new Promise(async (resolve, reject) => {
            try {
                // Google TTS has a limit of 200 characters per request.
                // We truncate or slice to safe length (180 chars) for stability, 
                // but usually chat messages are within this limit.
                const safeText = text.substring(0, 180);
                
                const url = googleTTS.getAudioUrl(safeText, {
                    lang: 'th',
                    slow: false,
                    host: 'https://translate.google.com',
                    timeout: 10000,
                });

                const filename = `speech_${Date.now()}_${Math.floor(Math.random() * 1000)}.mp3`;
                const dest = path.join(tempDir, filename);

                const file = fs.createWriteStream(dest);
                https.get(url, (response) => {
                    if (response.statusCode !== 200) {
                        reject(new Error(`Failed to download audio. Google TTS responded with status: ${response.statusCode}`));
                        return;
                    }
                    response.pipe(file);
                    file.on('finish', () => {
                        file.close(() => resolve(dest));
                    });
                }).on('error', (err) => {
                    fs.unlink(dest, () => reject(err));
                });
            } catch (error) {
                reject(error);
            }
        });
    }
}

const audioQueue = new AudioQueue();

// Initialize WhatsApp Client with Local Authentication
const executablePath = os.platform() === 'linux' ? '/usr/bin/chromium-browser' : undefined;

const client = new Client({
    authStrategy: new LocalAuth(),
    puppeteer: {
        executablePath: executablePath,
        headless: true,
        args: [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage'
        ]
    }
});

// Event: QR Code generated (scan with mobile app)
client.on('qr', (qr) => {
    console.log('\n======================================================================');
    console.log('กรุณาสแกน QR Code ด้านล่างนี้ด้วยแอป WhatsApp บนโทรศัพท์ของคุณเพื่อเชื่อมต่อระบบ:');
    console.log('======================================================================\n');
    
    qrcode.generate(qr, { small: true });
});

// Event: Successfully authenticated
client.on('authenticated', () => {
    console.log('[System] เข้าสู่ระบบ WhatsApp สำเร็จแล้ว!');
});

// Event: Authentication failed
client.on('auth_failure', (msg) => {
    console.error('[System] การยืนยันตัวตนล้มเหลว:', msg);
});

// Event: Client is ready
client.on('ready', () => {
    console.log('\n======================================================================');
    console.log('[System] ระบบ WhatsApp TTS Reader พร้อมทำงานแล้ว!');
    console.log('[System] กำลังรอข้อความใหม่...');
    console.log('======================================================================\n');
    
    // Play system ready notification
    audioQueue.enqueue('ระบบวอตส์แอปทีทีเอสพร้อมทำงานแล้วค่ะ');
});

// Event: Message received
client.on('message', async (msg) => {
    // Skip messages sent by oneself
    if (msg.fromMe) return;

    try {
        const chat = await msg.getChat();
        const contact = await msg.getContact();
        
        // Sender's name
        const senderName = contact.pushname || contact.name || 'ไม่ทราบชื่อ';
        
        // Define media text representation
        let messageText = '';
        
        if (msg.type === 'chat') {
            messageText = msg.body;
        } else if (msg.type === 'image') {
            messageText = 'ส่งรูปภาพ';
        } else if (msg.type === 'video') {
            messageText = 'ส่งวิดีโอ';
        } else if (msg.type === 'sticker') {
            messageText = 'ส่งสติกเกอร์';
        } else if (msg.type === 'audio' || msg.type === 'voice') {
            messageText = 'ส่งข้อความเสียง';
        } else {
            messageText = 'ส่งข้อความสื่อ';
        }

        // Ignore empty messages
        if (!messageText.trim()) return;

        let speechString = '';

        const targetGroup = process.env.TARGET_GROUP_NAME;

        if (chat.isGroup) {
            // Group Chat context
            const groupName = chat.name || 'กลุ่มแชต';
            
            if (targetGroup && groupName !== targetGroup) {
                return; // Ignore messages from other groups
            }

            console.log(`[New Group Message] [${groupName}] ${senderName}: ${messageText}`);
            speechString = `ในกลุ่ม ${groupName} คุณ ${senderName} ส่งข้อความว่า ${messageText}`;
        } else {
            // Private Chat context
            if (targetGroup) {
                return; // Ignore private messages if a target group is set
            }

            console.log(`[New Private Message] ${senderName}: ${messageText}`);
            speechString = `คุณ ${senderName} ส่งข้อความว่า ${messageText}`;
        }

        // Add formatted speech to queue
        audioQueue.enqueue(speechString);
        
    } catch (error) {
        console.error('[Message Handler Error]', error);
    }
});

// Start WhatsApp Client
console.log('[System] กำลังเริ่มต้นระบบ WhatsApp Client (อาจใช้เวลาสักครู่ในการเริ่มเบราว์เซอร์)...');
client.initialize().catch(err => {
    console.error('[System Fatal Error] ไม่สามารถเริ่มต้น WhatsApp Client ได้:', err);
});
