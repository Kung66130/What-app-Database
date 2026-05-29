const { initFileLogger } = require('./logger');
initFileLogger({ appName: 'whatsapp-pairing-code' });
const os = require('os');
const fs = require('fs');
const path = require('path');
const { Client, LocalAuth } = require('whatsapp-web.js');

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
    const platform = os.platform();
    const args = [
        '--disable-dev-shm-usage',
        '--mute-audio',
        '--no-first-run',
        '--no-default-browser-check',
    ];

    // Common for Linux containers / Pi setups.
    if (platform === 'linux') {
        args.unshift('--no-sandbox', '--disable-setuid-sandbox');
    }

    // Avoid flags like --single-process / --no-zygote which can crash on Windows/macOS.
    return args;
}

const phoneNumber = (process.env.WA_PHONE_NUMBER || process.argv[2] || '').trim();

if (!phoneNumber) {
    console.error('Usage: node get_pairing_code.js <phoneNumber>');
    console.error('Example (TH): node get_pairing_code.js 669XXXXXXXX');
    process.exit(1);
}

const clientId = (process.env.WWEBJS_CLIENT_ID || '').trim();
const dataPath = process.env.WWEBJS_DATA_PATH || undefined;
const authOptions = {};

if (clientId) {
    authOptions.clientId = clientId;
}
if (dataPath) {
    authOptions.dataPath = dataPath;
}

console.log('[System] กำลังจัดทำรหัสเชื่อมโยง (Pairing Code) สำหรับเบอร์:', phoneNumber);
console.log('[System] หมายเหตุ: โค้ดจะรีเฟรชอัตโนมัติทุก 3 นาที — ใช้โค้ด "ล่าสุด" เท่านั้น');

const client = new Client({
    authStrategy: new LocalAuth(authOptions),
    authTimeoutMs: 120000,
    puppeteer: {
        executablePath: resolveLinuxChromiumPath(),
        headless: true,
        timeout: 0,
        protocolTimeout: 240000,
        args: buildPuppeteerArgs(),
    },
});

let latestCode = null;
let latestAt = null;
let pairingRequestInFlight = false;

function printCode(code) {
    latestCode = code;
    latestAt = new Date();
    const ts = latestAt.toLocaleString('th-TH', { hour12: false });

    console.log('\n======================================================================');
    console.log(` รหัสเชื่อมโยงอุปกรณ์ล่าสุดคือ:  ${code}  (เวลา: ${ts})`);
    console.log('======================================================================\n');
    console.log('วิธีทำ (บนมือถือ):');
    console.log('1) WhatsApp -> Linked devices (อุปกรณ์ที่เชื่อมโยง) -> Link a device (เชื่อมโยงอุปกรณ์)');
    console.log('2) กด "Link with phone number instead" (เชื่อมโยงด้วยเบอร์โทรศัพท์แทน)');
    console.log('3) ใส่รหัส 8 หลักด้านบน (ใช้รหัสล่าสุดเท่านั้น)');
}

client.on('code', (code) => {
    printCode(code);
});

async function requestCodeWithRetry() {
    if (pairingRequestInFlight) return;
    pairingRequestInFlight = true;
    try {
        // Give WhatsApp Web a moment after the QR is generated (more stable on some machines).
        await new Promise((r) => setTimeout(r, 8000));
        await client.requestPairingCode(phoneNumber, true, 180000);
    } catch (err) {
        console.error('[Pairing Code Error]', err);
        console.error('[Hint] ถ้าขึ้น error ให้ลองรันใหม่อีกครั้ง หรือใช้วิธี QR: npm run pair:qr');
    } finally {
        pairingRequestInFlight = false;
    }
}

// Whatsapp-web.js triggers QR while unpaired; use that as the moment to request pairing code.
client.on('qr', () => {
    requestCodeWithRetry();
});

client.on('ready', () => {
    console.log('\n======================================================================');
    console.log('SUCCESS: เชื่อมต่อสำเร็จแล้ว!');
    console.log(`Session: ${clientId || 'default-session-store'}`);
    console.log('======================================================================\n');
    process.exit(0);
});

client.on('auth_failure', (msg) => {
    console.error('[Auth Failure]', msg);
});

client.on('disconnected', (reason) => {
    console.error('[Disconnected]', reason);
    if (latestCode) {
        console.error(`[Hint] โค้ดล่าสุดคือ ${latestCode} (เวลา: ${latestAt?.toISOString?.() || '-'})`);
    }
});

process.on('unhandledRejection', (reason) => {
    console.error('[UnhandledRejection]', reason);
});
process.on('uncaughtException', (err) => {
    console.error('[UncaughtException]', err);
});

process.on('SIGINT', async () => {
    try {
        await client.destroy();
    } catch {}
    process.exit(130);
});

// Function to robustly delete Chromium lock files that prevent session persistence
function cleanupSingletonLocks() {
    const authDir = dataPath || path.join(__dirname, '.wwebjs_auth');
    const sessionDir = path.join(authDir, 'session');
    if (fs.existsSync(sessionDir)) {
        try {
            const files = fs.readdirSync(sessionDir);
            for (const file of files) {
                if (file.startsWith('Singleton')) {
                    const filePath = path.join(sessionDir, file);
                    fs.unlinkSync(filePath);
                    console.log(`[Cleanup] Cleaned up stale lock file: ${file}`);
                }
            }
        } catch (e) {
            console.warn(`[Cleanup] Warning clearing lock files: ${e.message}`);
        }
    }
}

cleanupSingletonLocks();
client.initialize().catch((err) => {
    console.error('[Fatal] ไม่สามารถเริ่ม WhatsApp Client ได้:', err);
    process.exit(1);
});
