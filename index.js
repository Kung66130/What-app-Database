require('dotenv').config();
const fs = require('fs');
const os = require('os');
const path = require('path');
const https = require('https');
const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const googleTTS = require('google-tts-api');
const sound = require('sound-play');

// Translate text to Thai using Gemini API if it contains non-Thai characters
function translateToThai(text) {
    return new Promise((resolve) => {
        // Detect if text is mostly Thai already (Thai unicode range: \u0E00-\u0E7F)
        const thaiChars = (text.match(/[\u0E00-\u0E7F]/g) || []).length;
        const totalChars = text.replace(/\s/g, '').length;
        if (totalChars === 0 || thaiChars / totalChars > 0.5) {
            return resolve(text); // Already Thai, skip translation
        }

        const apiKey = process.env.GEMINI_API_KEY;
        if (!apiKey) return resolve(text);

        const body = JSON.stringify({
            contents: [{
                parts: [{ text: `Translate the following message to Thai. Return ONLY the translated text, nothing else:\n\n${text}` }]
            }]
        });

        const options = {
            hostname: 'generativelanguage.googleapis.com',
            path: `/v1beta/models/gemini-2.0-flash:generateContent?key=${apiKey}`,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) }
        };

        const req = https.request(options, (res) => {
            let data = '';
            res.on('data', chunk => data += chunk);
            res.on('end', () => {
                try {
                    const json = JSON.parse(data);
                    const translated = json.candidates?.[0]?.content?.parts?.[0]?.text?.trim();
                    console.log(`[Translate] "${text}" => "${translated}"`);
                    resolve(translated || text);
                } catch (e) {
                    resolve(text);
                }
            });
        });
        req.on('error', () => resolve(text));
        req.write(body);
        req.end();
    });
}

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
            
            // Play audio based on OS
            if (os.platform() === 'linux') {
                const { exec } = require('child_process');
                await new Promise((resolve) => {
                    exec(`mplayer -really-quiet -noconsolecontrols "${filePath}"`, (error) => {
                        if (error) console.error('[Audio Error]', error);
                        resolve();
                    });
                });
            } else {
                await sound.play(filePath);
            }
            
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
const executablePath = require('os').platform() === 'linux' ? 
    (require('fs').existsSync('/usr/bin/chromium') ? '/usr/bin/chromium' : '/usr/bin/chromium-browser') 
    : undefined;

const client = new Client({
    authStrategy: new LocalAuth(),
    authTimeoutMs: 120000,
    qrMaxRetries: 5,
    puppeteer: {
        executablePath: executablePath,
        headless: true,
        timeout: 0,
        protocolTimeout: 240000,
        args: [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-gpu',
            '--disable-software-rasterizer',
            '--disable-accelerated-2d-canvas',
            '--disable-extensions',
            '--mute-audio',
            '--disable-sync',
            '--disable-default-apps',
            '--no-zygote',
            '--single-process'
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
client.on('ready', async () => {
    console.log('\n======================================================================');
    console.log('[System] ระบบ WhatsApp TTS Reader พร้อมทำงานแล้ว!');
    console.log('[System] กำลังรอข้อความใหม่...');
    console.log('======================================================================\n');
    
    // Play system ready notification
    audioQueue.enqueue('ระบบวอตส์แอปทีทีเอสพร้อมทำงานแล้วค่ะ');
});

// Event: Message created (receives both incoming and outgoing messages for testing)
client.on('message_create', async (msg) => {

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

        const targetGroupsStr = process.env.TARGET_GROUP_NAME;
        const targetGroups = targetGroupsStr ? targetGroupsStr.split(',').map(g => g.trim()) : [];

        if (chat.isGroup) {
            // Group Chat context
            const groupName = chat.name || 'กลุ่มแชต';
            console.log(`[Debug] Incoming from group: "${groupName}"`);
            
            if (targetGroups.length > 0 && !targetGroups.includes(groupName)) {
                return; // Ignore messages from other groups
            }

            console.log(`[New Group Message] [${groupName}] ${senderName}: ${messageText}`);
            const translatedText = await translateToThai(messageText);
            speechString = `ในกลุ่ม ${groupName} คุณ ${senderName} ส่งข้อความว่า ${translatedText}`;
        } else {
            // Private Chat context
            if (targetGroups.length > 0) {
                return; // Ignore private messages if a target group is set
            }

            console.log(`[New Private Message] ${senderName}: ${messageText}`);
            const translatedText = await translateToThai(messageText);
            speechString = `คุณ ${senderName} ส่งข้อความว่า ${translatedText}`;
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
