const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');

const executablePath = require('os').platform() === 'linux' ? 
    (require('fs').existsSync('/usr/bin/chromium') ? '/usr/bin/chromium' : '/usr/bin/chromium-browser') 
    : undefined;

const client = new Client({
    authStrategy: new LocalAuth(),
    authTimeoutMs: 120000,
    qrMaxRetries: 15,
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
