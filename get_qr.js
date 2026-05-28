const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');

const os = require('os');
const fs = require('fs');

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

    // These flags are primarily useful/required in many Linux container setups.
    if (platform === 'linux') {
        args.unshift('--no-sandbox', '--disable-setuid-sandbox');
    }

    // Avoid flags like --single-process / --no-zygote which can cause crashes on Windows/macOS.
    return args;
}

const executablePath = resolveLinuxChromiumPath();
const clientId = (process.env.WWEBJS_CLIENT_ID || '').trim();
const dataPath = process.env.WWEBJS_DATA_PATH || undefined;
const authOptions = {};

if (clientId) {
    authOptions.clientId = clientId;
}
if (dataPath) {
    authOptions.dataPath = dataPath;
}

const client = new Client({
    authStrategy: new LocalAuth(authOptions),
    authTimeoutMs: 120000,
    qrMaxRetries: 15,
    puppeteer: {
        executablePath: executablePath,
        headless: true,
        timeout: 0,
        protocolTimeout: 240000,
        args: buildPuppeteerArgs()
    }
});

client.on('qr', (qr) => {
    console.clear();
    console.log('\n======================================================================');
    console.log(' สแกน QR Code ด้านล่างนี้เพื่อเชื่อมต่อระบบ:');
    console.log('======================================================================\n');
    qrcode.generate(qr, { small: false });
});

client.on('ready', () => {
    console.log('\n======================================================================');
    console.log(' SUCCESS: เข้าสู่ระบบสำเร็จแล้ว!');
    console.log('======================================================================\n');
    process.exit(0);
});

client.initialize();
