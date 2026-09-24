const { app, BrowserWindow, dialog, Menu, powerMonitor, powerSaveBlocker, session, shell } = require('electron');
const { existsSync, readFileSync, writeFileSync, mkdirSync } = require('node:fs');
const path = require('node:path');
const { Backend, validateRuntime } = require('./backend.cjs');

let window, backend, quitting = false, checkingQuit = false, blocker;
app.setName('Go2 Data Studio');
if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on('second-instance', () => { window?.show(); window?.focus(); });
  app.whenReady().then(start).catch(async error => {
    dialog.showErrorBox('Go2 Data Studio could not start', error.message);
    // Startup has not exposed the dashboard and therefore cannot have connected a robot.
    if (backend?.child && !backend.exited) backend.child.kill('SIGTERM');
    quitting = true;
    app.quit();
  });
}

async function runtimeSettings() {
  const home = app.getPath('userData');
  mkdirSync(home, { recursive: true, mode: 0o700 });
  const configFile = path.join(home, 'desktop.json');
  let saved = {};
  if (existsSync(configFile)) saved = JSON.parse(readFileSync(configFile, 'utf8'));
  let runtime = process.env.DIMOS_RUNTIME || saved.runtime;
  if (!runtime) {
    const result = await dialog.showOpenDialog({
      title: 'Select your installed DimOS runtime (development preview)',
      message: 'Choose the pinned DimOS checkout containing its configured .venv. This preview does not install the runtime.',
      properties: ['openDirectory'],
    });
    if (result.canceled) return null;
    runtime = result.filePaths[0];
  }
  validateRuntime(runtime);
  writeFileSync(configFile, JSON.stringify({ runtime }), { mode: 0o600 });
  return {
    runtime,
    data: process.env.GO2_SPACES || path.join(home, 'spaces'),
    robotEnv: process.env.GO2_ENV_FILE || path.join(home, 'robot.env'),
    source: app.isPackaged ? path.join(process.resourcesPath, 'app') : path.resolve(__dirname, '..'),
    replayOnly: process.env.GO2_REPLAY_ONLY === '1',
  };
}

async function start() {
  const options = await runtimeSettings();
  if (!options) { quitting = true; app.quit(); return; }
  backend = new Backend(options);
  await backend.start();
  const webSession = session.fromPartition('go2-desktop-session');
  webSession.webRequest.onBeforeSendHeaders((details, callback) => {
    const headers = { ...details.requestHeaders };
    // The renderer never receives Node privileges or the session credential.
    delete headers['X-Go2-Desktop'];
    if (new URL(details.url).origin === backend.origin) headers['X-Go2-Desktop'] = backend.token;
    callback({ requestHeaders: headers });
  });
  webSession.setPermissionRequestHandler((contents, permission, callback) => {
    const trusted = contents && new URL(contents.getURL()).origin === backend.origin;
    callback(!!trusted && ['fullscreen', 'clipboard-sanitized-write'].includes(permission));
  });
  window = new BrowserWindow({
    width: 1280, height: 800, minWidth: 800, minHeight: 600,
    backgroundColor: '#141917', title: 'Go2 Data Studio', show: false,
    webPreferences: { session: webSession, nodeIntegration: false, contextIsolation: true, sandbox: true },
  });
  window.webContents.setWindowOpenHandler(({ url }) => {
    const parsed = new URL(url);
    if (parsed.protocol === 'https:' && !parsed.username && !parsed.password) void shell.openExternal(url);
    return { action: 'deny' };
  });
  window.webContents.on('will-navigate', (event, url) => {
    if (new URL(url).origin !== backend.origin) event.preventDefault();
  });
  window.webContents.on('render-process-gone', () => { void pause(); });
  window.on('blur', () => { void pause(); });
  window.on('close', event => { if (!quitting) { event.preventDefault(); void requestQuit(); } });
  window.once('ready-to-show', () => window.show());
  backend.onExit = () => {
    if (!quitting && !checkingQuit) dialog.showErrorBox('DimOS stopped', 'The local backend exited. It will not reconnect or resume movement automatically. Inspect the data-folder logs before restarting.');
  };
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    { label: 'Go2 Data Studio', submenu: [
      { label: 'Open data folder', click: () => void shell.openPath(options.data) },
      { label: 'Quit', accelerator: 'CommandOrControl+Q', click: () => void requestQuit() },
    ] },
    { label: 'Edit', submenu: [{ role: 'undo' }, { role: 'redo' }, { role: 'cut' }, { role: 'copy' }, { role: 'paste' }, { role: 'selectAll' }] },
    { label: 'View', submenu: [{ role: 'togglefullscreen' }, { role: 'zoomIn' }, { role: 'zoomOut' }, { role: 'resetZoom' }] },
  ]));
  // Idle sleep is inhibited while this control application is open. Manual sleep
  // cannot be guaranteed safe: pause events complement robot-side watchdogs.
  blocker = powerSaveBlocker.start('prevent-app-suspension');
  powerMonitor.on('suspend', () => { void pause(); });
  powerMonitor.on('resume', () => { void pause(); });
  powerMonitor.on('lock-screen', () => { void pause(); });
  await window.loadURL(backend.origin);
}
async function pause() {
  try { await backend?.stopMotion(); } catch { /* Robot-side expiry remains authoritative. */ }
}
async function requestQuit() {
  if (quitting || checkingQuit) return;
  checkingQuit = true;
  try {
    await pause();
    await backend?.quit();
    quitting = true;
    if (blocker !== undefined) powerSaveBlocker.stop(blocker);
    app.quit();
  } catch (error) {
    await dialog.showMessageBox(window, {
      type: 'warning', title: 'Finish the robot session first',
      message: error.message,
      detail: 'Use the dashboard to save recording, lie the robot down with an operator present, visually confirm support and disconnect. Quitting also cancels map jobs and pauses uploads.',
      buttons: ['Return to dashboard'],
    });
    window?.show();
  } finally { checkingQuit = false; }
}
app.on('before-quit', event => { if (!quitting) { event.preventDefault(); void requestQuit(); } });
app.on('window-all-closed', () => { if (quitting) app.quit(); });
