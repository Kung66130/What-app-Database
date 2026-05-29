const fs = require('fs');
const path = require('path');
const util = require('util');

let activeLogger = null;

function pad(value) {
    return String(value).padStart(2, '0');
}

function formatDate(date) {
    return [
        date.getFullYear(),
        pad(date.getMonth() + 1),
        pad(date.getDate()),
    ].join('-');
}

function formatTimestamp(date) {
    return `${formatDate(date)} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}.${String(date.getMilliseconds()).padStart(3, '0')}`;
}

function formatArg(arg) {
    if (arg instanceof Error) {
        return arg.stack || arg.message;
    }
    if (typeof arg === 'string') {
        return arg;
    }
    return util.inspect(arg, {
        colors: false,
        depth: 6,
        breakLength: Infinity,
    });
}

function createLogger(options = {}) {
    const logDir = path.resolve(
        process.env.WA_AGENT_LOG_DIR || options.logDir || path.join(__dirname, 'logs'),
    );
    fs.mkdirSync(logDir, { recursive: true });

    const appName = options.appName || 'whatsapp-agent';
    const logFile = path.join(logDir, `${appName}-${formatDate(new Date())}.log`);

    function write(level, args) {
        const line = `[${formatTimestamp(new Date())}] [${level}] ${args.map(formatArg).join(' ')}\n`;
        fs.appendFileSync(logFile, line, 'utf8');
    }

    return {
        logDir,
        logFile,
        info: (...args) => write('INFO', args),
        warn: (...args) => write('WARN', args),
        error: (...args) => write('ERROR', args),
    };
}

function initFileLogger(options = {}) {
    if (activeLogger) {
        return activeLogger;
    }

    const logger = createLogger(options);
    const originalConsole = {
        log: console.log.bind(console),
        warn: console.warn.bind(console),
        error: console.error.bind(console),
    };

    console.log = (...args) => {
        logger.info(...args);
        originalConsole.log(...args);
    };
    console.warn = (...args) => {
        logger.warn(...args);
        originalConsole.warn(...args);
    };
    console.error = (...args) => {
        logger.error(...args);
        originalConsole.error(...args);
    };

    process.on('uncaughtException', (error) => {
        logger.error('[Process] uncaughtException', error);
        originalConsole.error(error);
        process.exitCode = 1;
    });

    process.on('unhandledRejection', (reason) => {
        logger.error('[Process] unhandledRejection', reason);
        originalConsole.error(reason);
    });

    activeLogger = logger;
    console.log(`[Logger] Writing runtime logs to ${logger.logFile}`);
    logger.info('[Process] start', { pid: process.pid, cwd: process.cwd(), argv: process.argv });

    process.on('exit', (code) => {
        logger.info('[Process] exit', { code });
    });

    return logger;
}

module.exports = {
    initFileLogger,
};
