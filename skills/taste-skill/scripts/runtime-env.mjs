// Local Codex integration: use the existing browser and user temporary storage.
// No browser downloads, dependency installs or global environment changes.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const localTmp = '/data/lzh/default-storage/tmp';
if (!process.env.TMPDIR && fs.existsSync(localTmp)) process.env.TMPDIR = localTmp;
if (!process.env.TASTE_SKILL_TMP) process.env.TASTE_SKILL_TMP = path.join(os.tmpdir(), 'taste-skill');

if (!process.env.CHROME_PATH || !fs.existsSync(process.env.CHROME_PATH)) {
  const candidates = ['/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium', '/usr/bin/chromium-browser', '/snap/bin/chromium', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'];
  const caches = [process.env.PLAYWRIGHT_BROWSERS_PATH, path.join(os.homedir(), '.cache/ms-playwright')].filter(p => p && p !== '0' && fs.existsSync(p));
  for (const cache of caches) {
    const builds = fs.readdirSync(cache).filter(n => /^chromium(?:_headless_shell)?-\d+$/.test(n)).sort((a, b) => Number(b.match(/\d+$/)[0]) - Number(a.match(/\d+$/)[0]));
    for (const build of builds) {
      for (const suffix of ['chrome-headless-shell-linux64/chrome-headless-shell', 'chrome-linux64/chrome', 'chrome-linux/chrome', 'chrome-headless-shell-mac-arm64/chrome-headless-shell', 'chrome-headless-shell-mac-x64/chrome-headless-shell']) candidates.push(path.join(cache, build, suffix));
    }
  }
  const browser = candidates.find(p => fs.existsSync(p));
  if (browser) process.env.CHROME_PATH = browser;
}
