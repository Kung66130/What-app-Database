const { initFileLogger } = require('./logger');
initFileLogger({ appName: 'whatsapp-tts-reader' });
require('dotenv').config();
const fs = require('fs');
const os = require('os');
const path = require('path');
const https = require('https');
const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const googleTTS = require('google-tts-api');
const sound = require('sound-play');

// Rate limiting state for Gemini translation API (seconds between translation requests)
const TRANSLATION_COOLDOWN_MS = 2000;
let lastTranslationTime = 0;

// Log function that includes timestamp
function logWithTimestamp(level, message, ...args) {
    const timestamp = new Date().toISOString().replace('T', ' ').substring(0, 19);
    const logMsg = `[${timestamp}] [${level}] ${message}`;
    if (level === 'ERROR') {
        console.error(logMsg, ...args);
    } else if (level === 'WARN') {
        console.warn(logMsg, ...args);
    } else {
        console.log(logMsg, ...args);
    }
}

// Translate text to Thai using Gemini API if it contains non-Thai characters
function translateToThai(text) {
    return new Promise(async (resolve) => {
        // Detect if text is mostly Thai already (Thai unicode range: \u0E00-\u0E7F)
        const thaiChars = (text.match(/[\u0E00-\u0E7F]/g) || []).length;
        const totalChars = text.replace(/\s/g, '').length;
        if (totalChars === 0 || thaiChars / totalChars > 0.5) {
            return resolve(text); // Already Thai, skip translation
        }

        const apiKey = process.env.GEMINI_API_KEY;
        if (!apiKey) return resolve(text);

        // Rate limiting: enforces space between translation requests
        const now = Date.now();
        const timeSinceLast = now - lastTranslationTime;
        if (timeSinceLast < TRANSLATION_COOLDOWN_MS) {
            const delay = TRANSLATION_COOLDOWN_MS - timeSinceLast;
            logWithTimestamp('INFO', `[Rate Limit] Cooldown active. Waiting ${delay}ms before translating...`);
            await new Promise(r => setTimeout(r, delay));
        }
        lastTranslationTime = Date.now();

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
                    if (res.statusCode !== 200) {
                        logWithTimestamp('WARN', `[Translate API Warning] Request failed with status ${res.statusCode}. Falling back to original text.`);
                        return resolve(text);
                    }
                    const json = JSON.parse(data);
                    const translated = json.candidates?.[0]?.content?.parts?.[0]?.text?.trim();
                    if (translated) {
                        logWithTimestamp('INFO', `[Translate] "${text}" => "${translated}"`);
                        resolve(translated);
                    } else {
                        resolve(text);
                    }
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

// Helper to split a long message into chunks under 180 characters for safe Google TTS processing
function splitTextIntoTTSChunks(text, maxLength = 180) {
    if (text.length <= maxLength) return [text];
    
    const chunks = [];
    let currentChunk = "";
    
    // Split by spaces or punctuation to keep words intact where possible
    const words = text.split(/(\s+)/); 
    
    for (const word of words) {
        if ((currentChunk + word).length > maxLength) {
            if (currentChunk.trim()) {
                chunks.push(currentChunk.trim());
            }
            currentChunk = word;
        } else {
            currentChunk += word;
        }
    }
    
    if (currentChunk.trim()) {
        chunks.push(currentChunk.trim());
    }
    
    // Fallback: If any single word was too long, split it by characters
    return chunks.flatMap(chunk => {
        if (chunk.length <= maxLength) return [chunk];
        const subChunks = [];
        for (let i = 0; i < chunk.length; i += maxLength) {
            subChunks.push(chunk.substring(i, i + maxLength));
        }
        return subChunks;
    });
}

// Helper function to detect language for dynamic TTS voice selection
function detectLanguage(text) {
    const thaiChars = (text.match(/[\u0E00-\u0E7F]/g) || []).length;
    const englishChars = (text.match(/[a-zA-Z]/g) || []).length;
    if (englishChars > thaiChars) {
        return 'en';
    }
    return 'th';
}

// Queue system to manage sequential audio playback (avoids voices overlapping)
class AudioQueue {
    constructor() {
        this.queue = [];
        this.isPlaying = false;
        this.MAX_QUEUE_SIZE = 50; // Prevention of memory leak
    }

    // Add a text to the speech queue
    enqueue(text) {
        // Enforce maximum queue size
        if (this.queue.length >= this.MAX_QUEUE_SIZE) {
            logWithTimestamp('WARN', `[Queue] Limit reached (${this.MAX_QUEUE_SIZE}). Dropping oldest message to prevent leak.`);
            this.queue.shift(); // Drop oldest
        }

        // Split long messages into safe chunks instead of silently truncating
        const chunks = splitTextIntoTTSChunks(text, 180);
        if (chunks.length > 1) {
            logWithTimestamp('INFO', `[Queue] Splitting long message into ${chunks.length} chunks for clean TTS readout.`);
        }

        for (const chunk of chunks) {
            const lang = detectLanguage(chunk);
            logWithTimestamp('INFO', `[Queue] Added message to queue: "${chunk}" [Lang: ${lang}]`);
            this.queue.push({ text: chunk, lang: lang });
        }
        
        this.processQueue();
    }

    // Process the next item in the queue
    async processQueue() {
        if (this.isPlaying || this.queue.length === 0) {
            return;
        }

        this.isPlaying = true;
        const item = this.queue.shift();
        const text = item.text;
        const lang = item.lang;

        // Error handling fallback: up to 3 retries for robust playback
        let attempt = 0;
        let success = false;
        let filePath = null;

        while (attempt < 3 && !success) {
            attempt++;
            try {
                logWithTimestamp('INFO', `[TTS] Processing text (Attempt ${attempt}/3) [Lang: ${lang}]: "${text}"`);
                filePath = await this.generateSpeechFile(text, lang);
                logWithTimestamp('INFO', `[Audio] Playing audio...`);
                
                // Play audio based on OS
                if (os.platform() === 'linux') {
                    const { exec } = require('child_process');
                    await new Promise((resolve, reject) => {
                        const envVars = 'PULSE_SERVER=unix:/run/user/1004/pulse/native';
                        exec(`${envVars} mplayer -really-quiet -noconsolecontrols "${filePath}"`, (error) => {
                            if (error) reject(error);
                            else resolve();
                        });
                    });
                } else {
                    await sound.play(filePath);
                }
                
                logWithTimestamp('INFO', `[Audio] Playback finished.`);
                success = true; // Succeeded!
            } catch (error) {
                logWithTimestamp('ERROR', `[Queue Attempt ${attempt} Failed]`, error);
                
                // Graceful cleanup of file if created during failure
                if (filePath && fs.existsSync(filePath)) {
                    try { fs.unlinkSync(filePath); } catch (e) {}
                    filePath = null;
                }

                if (attempt < 3) {
                    logWithTimestamp('INFO', `[Queue] Retrying in 1.5s...`);
                    await new Promise(r => setTimeout(r, 1500));
                }
            }
        }

        // Clean up the temporary audio file after playing
        if (filePath) {
            try {
                if (fs.existsSync(filePath)) {
                    fs.unlinkSync(filePath);
                }
            } catch (err) {
                logWithTimestamp('ERROR', `[Cleanup] Failed to delete temp file: ${filePath}`, err);
            }
        }

        this.isPlaying = false;
        // Introduce a short delay between messages
        setTimeout(() => {
            this.processQueue();
        }, 1000);
    }

    // Download TTS audio and return the file path
    generateSpeechFile(text, lang = 'th') {
        return new Promise(async (resolve, reject) => {
            try {
                const url = googleTTS.getAudioUrl(text, {
                    lang: lang,
                    slow: false,
                    host: 'https://translate.google.com',
                    timeout: 8000,
                });

                const filename = `speech_${Date.now()}_${Math.floor(Math.random() * 1000)}.mp3`;
                const dest = path.join(tempDir, filename);

                const file = fs.createWriteStream(dest);
                https.get(url, (response) => {
                    if (response.statusCode !== 200) {
                        reject(new Error(`Google TTS responded with status: ${response.statusCode}`));
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
function resolveLinuxChromiumPath() {
    if (os.platform() !== 'linux') return undefined;
    const candidates = [
        '/usr/bin/chromium',
        '/usr/bin/chromium-browser',
        '/usr/bin/google-chrome',
        '/usr/bin/google-chrome-stable',
    ];
    for (const candidate of candidates) {
        if (fs.existsSync(candidate)) return candidate;
    }
    return undefined;
}

function buildPuppeteerArgs() {
    const args = [
        '--disable-dev-shm-usage',
        '--mute-audio',
        '--no-first-run',
        '--no-default-browser-check',
    ];

    if (os.platform() === 'linux') {
        args.unshift('--no-sandbox', '--disable-setuid-sandbox');
    }

    return args;
}

const executablePath = resolveLinuxChromiumPath();

const client = new Client({
    authStrategy: new LocalAuth(),
    authTimeoutMs: 120000,
    qrMaxRetries: 5,
    puppeteer: {
        executablePath: executablePath,
        headless: true,
        timeout: 0,
        protocolTimeout: 240000,
        args: buildPuppeteerArgs()
    }
});

// Event: QR Code generated (scan with mobile app)
client.on('qr', (qr) => {
    logWithTimestamp('INFO', '\n======================================================================');
    logWithTimestamp('INFO', 'กรุณาสแกน QR Code ด้านล่างนี้ด้วยแอป WhatsApp บนโทรศัพท์ของคุณเพื่อเชื่อมต่อระบบ:');
    logWithTimestamp('INFO', '======================================================================\n');
    
    qrcode.generate(qr, { small: true });
});

// Event: Successfully authenticated
client.on('authenticated', () => {
    logWithTimestamp('INFO', '[System] เข้าสู่ระบบ WhatsApp สำเร็จแล้ว!');
});

// Event: Authentication failed
client.on('auth_failure', (msg) => {
    logWithTimestamp('ERROR', '[System] การยืนยันตัวตนล้มเหลว:', msg);
});

// Event: Client is ready
client.on('ready', async () => {
    logWithTimestamp('INFO', '\n======================================================================');
    logWithTimestamp('INFO', '[System] ระบบ WhatsApp TTS Reader พร้อมทำงานแล้ว!');
    logWithTimestamp('INFO', '[System] กำลังรอข้อความใหม่...');
    logWithTimestamp('INFO', '======================================================================\n');
    
    const readyTargetGroupsStr = process.env.TARGET_GROUP_NAME;
    const readyTargetGroups = readyTargetGroupsStr ? readyTargetGroupsStr.split(',').map(g => g.trim()).filter(Boolean) : [];
    if (readyTargetGroups.length > 0) {
        logWithTimestamp('INFO', `[System] Active group filter: ${readyTargetGroups.join(', ')}`);
    }

    // Play system ready notification
    audioQueue.enqueue('ระบบวอตส์แอปทีทีเอสพร้อมทำงานแล้วค่ะ');
});

// Centralized message handler function to remove duplicate code logic between message & message_create events
async function handleIncomingMessage(msg, isSelfMessage = false) {
    try {
        const chat = await msg.getChat();
        
        // Sender's name with robust fallback to prevent getAlternateUserWid crash
        let senderName = 'ไม่ทราบชื่อ';
        if (msg.fromMe) {
            senderName = 'ฉันเอง';
        } else {
            try {
                const contact = await msg.getContact();
                senderName = contact.pushname || contact.name || 'ไม่ทราบชื่อ';
            } catch (contactError) {
                logWithTimestamp('WARN', `[Message Handler] Could not retrieve contact details: ${contactError.message}`);
            }
        }
        
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
        const targetGroups = targetGroupsStr ? targetGroupsStr.split(',').map(g => g.trim()).filter(Boolean) : [];

        if (chat.isGroup) {
            // Group Chat context
            const groupName = chat.name || 'กลุ่มแชต';
            logWithTimestamp('INFO', `[Debug] Message from group: "${groupName}" fromMe=${msg.fromMe} selfTest=${isSelfMessage}`);
            
            if (targetGroups.length > 0 && !targetGroups.includes(groupName)) {
                logWithTimestamp('INFO', `[Debug] Ignored group "${groupName}" because it is not in TARGET_GROUP_NAME.`);
                return; // Ignore messages from other groups
            }

            logWithTimestamp('INFO', `[New Group Message] [${groupName}] ${senderName}: ${messageText}`);
            const translatedText = await translateToThai(messageText);
            speechString = `ในกลุ่ม ${groupName} คุณ ${senderName} ส่งข้อความว่า ${translatedText}`;
        } else {
            // Private Chat context
            if (targetGroups.length > 0) {
                return; // Ignore private messages if a target group is set
            }

            logWithTimestamp('INFO', `[New Private Message] ${senderName}: ${messageText}`);
            const translatedText = await translateToThai(messageText);
            speechString = `คุณ ${senderName} ส่งข้อความว่า ${translatedText}`;
        }

        // Add formatted speech to queue
        audioQueue.enqueue(speechString);
        
    } catch (error) {
        logWithTimestamp('ERROR', '[Message Handler Error]', error);
    }
}

// Event: Incoming message (more reliable than message_create for messages from others)
client.on('message', async (msg) => {
    // Only handle other people's messages here
    if (msg.fromMe) return;
    await handleIncomingMessage(msg, false);
});

// Event: Message created (receives both incoming and outgoing messages for testing)
client.on('message_create', async (msg) => {
    // Only handle self-testing messages here
    if (!msg.fromMe) return;
    await handleIncomingMessage(msg, true);
});

// Function to robustly delete Chromium lock files that prevent session persistence
function cleanupSingletonLocks() {
    const authDir = path.join(__dirname, '.wwebjs_auth');
    const sessionDir = path.join(authDir, 'session');
    if (fs.existsSync(sessionDir)) {
        try {
            const files = fs.readdirSync(sessionDir);
            for (const file of files) {
                if (file.startsWith('Singleton')) {
                    const filePath = path.join(sessionDir, file);
                    fs.unlinkSync(filePath);
                    logWithTimestamp('INFO', `[Cleanup] Cleaned up stale lock file: ${file}`);
                }
            }
        } catch (e) {
            logWithTimestamp('WARN', `[Cleanup] Warning clearing lock files: ${e.message}`);
        }
    }
}

// Start WhatsApp Client
logWithTimestamp('INFO', '[System] กำลังเริ่มต้นระบบ WhatsApp Client (อาจใช้เวลาสักครู่ในการเริ่มเบราว์เซอร์)...');
cleanupSingletonLocks();
client.initialize().catch(err => {
    logWithTimestamp('ERROR', '[System Fatal Error] ไม่สามารถเริ่มต้น WhatsApp Client ได้:', err);
});
