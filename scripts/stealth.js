// stealth.js
// Injected via Playwright add_init_script to mask automation artifacts.
// stealth.js
(function () {
    try{
    // 1. Erase navigator.webdriver completely
    // Trackers check if this property exists at all, not just if it's true/false.
        Object.defineProperty(Object.getPrototypeOf(navigator), 'webdriver', {
            get: () => undefined,
            configurable: true
        });
    } catch (e) { }

    if (!window.chrome) {
        window.chrome = {};
    }
    window.chrome.runtime = {};
    // 3. Mock navigator.plugins and navigator.mimeTypes
    // Headless/Automated browsers often report 0 plugins, which is a massive red flag for bots.
    // We mock the standard Chrome PDF Viewer.
    const PluginArray = [
        {
            name: 'Chrome PDF Plugin',
            filename: 'internal-pdf-viewer',
            description: 'Portable Document Format'
        },
        {
            name: 'Chrome PDF Viewer',
            filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai',
            description: ''
        },
        {
            name: 'Native Client',
            filename: 'internal-nacl-plugin',
            description: ''
        }
    ];

    try {
        Object.defineProperty(navigator, 'plugins', {
            get: () => PluginArray,
            configurable: true
        });
        Object.defineProperty(navigator, 'mimeTypes', {
            get: () => [
                { type: 'application/pdf', suffixes: 'pdf', description: '', enabledPlugin: PluginArray[0] }
            ],
            configurable: true
        });
    } catch (e) { }
    // 4. Fix the Permissions API
    // Bots usually have Notification permissions set to 'denied' by default,
    // but querying the API reveals inconsistencies. We force it to report 'prompt' like a fresh human user.
    try {
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = parameters => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
        );
    } catch (e) { }
    // 5. Spoof Languages
    // Sometimes automated browsers don't set the language arrays correctly.
    try {
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en'],
            configurable: true
        });
    } catch (e) { }
    // 6. Erase CDP/Selenium global variables
    // Some older drivers leak variables starting with `cdc_` into the window object.
    for (const key in window) {
        if (key.startsWith('cdc_') || key.startsWith('$cdc_')) {
            delete window[key];
        }
    }
})();