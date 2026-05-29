const { initFileLogger } = require('./logger');
initFileLogger({ appName: 'whatsapp-qr-image' });
const os = require('os');
const fs = require('fs');
const path = require('path');
const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode');

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

    if (platform === 'linux') {
        args.unshift('--no-sandbox', '--disable-setuid-sandbox');
    }

    return args;
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

const outputFile = process.env.WA_QR_FILE || 'qr.png';

const client = new Client({
    authStrategy: new LocalAuth(authOptions),
    authTimeoutMs: 120000,
    qrMaxRetries: 15,
    puppeteer: {
        executablePath: resolveLinuxChromiumPath(),
        headless: true,
        timeout: 0,
        protocolTimeout: 240000,
        args: buildPuppeteerArgs(),
    },
});

client.on('qr', async (qr) => {
    await qrcode.toFile(outputFile, qr, {
        color: { dark: '#000000', light: '#FFFFFF' },
        margin: 2,
        scale: 10,
    });
    console.log(`QR Code saved to ${outputFile}`);
});

client.on('ready', () => {
    console.log('SUCCESS: WhatsApp connected');
    process.exit(0);
});

client.on('auth_failure', (msg) => {
    console.error('[Auth Failure]', msg);
});

client.on('disconnected', (reason) => {
    console.error('[Disconnected]', reason);
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
    console.error('[Fatal] Failed to start WhatsApp Client:', err);
    process.exit(1);
});
