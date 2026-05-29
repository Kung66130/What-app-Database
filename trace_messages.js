require('dotenv').config();
const os = require('os');
const fs = require('fs');
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

const client = new Client({
    authStrategy: new LocalAuth(),
    authTimeoutMs: 120000,
    puppeteer: {
        executablePath: resolveLinuxChromiumPath(),
        headless: true,
        timeout: 0,
        protocolTimeout: 240000,
        args: [
            '--disable-dev-shm-usage',
            '--mute-audio',
            '--no-first-run',
            '--no-default-browser-check',
        ],
    },
});

async function logEvent(label, msg) {
    try {
        const chat = await msg.getChat();
        const groupName = chat.isGroup ? chat.name : '(private)';
        const payload = {
            label,
            fromMe: msg.fromMe,
            type: msg.type,
            body: msg.body,
            groupName,
            from: msg.from,
            timestamp: new Date().toISOString(),
        };
        console.log(JSON.stringify(payload));
    } catch (error) {
        console.error(`[trace:${label}]`, error);
    }
}

client.on('ready', () => {
    console.log(JSON.stringify({ label: 'ready', timestamp: new Date().toISOString() }));
});

client.on('message', async (msg) => {
    await logEvent('message', msg);
});

client.on('message_create', async (msg) => {
    await logEvent('message_create', msg);
});

client.initialize().catch((err) => {
    console.error('[trace:init]', err);
    process.exit(1);
});
