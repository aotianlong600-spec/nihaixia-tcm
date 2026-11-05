// Private IPC only: the Python parent encrypts credential frames; never log this pipe.
import { pathToFileURL } from 'node:url';

export function validateCredential(value) {
  if (!value || value.type !== 'oauth' || !Number.isFinite(value.expires) || value.expires <= 0) throw Error('Invalid credential');
  for (const key of ['access', 'refresh']) if (typeof value[key] !== 'string' || !value[key] || value[key].length > 7000 || /[\x00-\x20\x7f]/.test(value[key])) throw Error('Invalid credential');
  if (typeof value.accountId !== 'string' || !value.accountId || value.accountId.length > 256) throw Error('Invalid account');
  return { type: 'oauth', access: value.access, refresh: value.refresh, expires: value.expires, accountId: value.accountId };
}

function authUrl(value) {
  const url = new URL(value);
  if (url.protocol !== 'https:' || !['auth.openai.com', 'chatgpt.com'].includes(url.hostname) || url.username || url.password || url.port) throw Error('Invalid authorization URL');
  return url.href;
}

export function publicAuthEvent(event) {
  if (event.type === 'auth_url') return { type: 'auth_url', url: authUrl(event.url) };
  if (event.type === 'device_code') {
    if (typeof event.userCode !== 'string' || !/^[A-Za-z0-9-]{1,64}$/.test(event.userCode)) throw Error('Invalid device code');
    return { type: 'device_code', userCode: event.userCode, verificationUri: authUrl(event.verificationUri) };
  }
  return { type: 'progress', message: '等待OpenAI授权完成' };
}

export async function performOAuth(request, { oauth, emit, signal }) {
  if (!request || !['login', 'refresh'].includes(request.op)) throw Error('Invalid operation');
  if (request.op === 'refresh') return validateCredential(await oauth.refresh(validateCredential(request.credential), signal));
  if (!['device', 'browser'].includes(request.method)) throw Error('Invalid login method');
  const interaction = {
    signal,
    notify: event => emit(publicAuthEvent(event)),
    prompt: prompt => {
      if (prompt.type === 'select') {
        const choice = request.method === 'device' ? 'device_code' : 'browser';
        if (!prompt.options?.some(o => o.id === choice)) throw Error('Unsupported selection');
        return Promise.resolve(choice);
      }
      if (prompt.type !== 'manual_code') return Promise.reject(Error('Unsupported login prompt'));
      emit({ type: 'waiting_callback' });
      // The SDK races this against its localhost callback. No password is entered in our app.
      return new Promise((resolve, reject) => {
        const cancel = () => reject(Error('Login cancelled'));
        if (signal.aborted || prompt.signal?.aborted) return cancel();
        signal.addEventListener('abort', cancel, { once: true });
        prompt.signal?.addEventListener('abort', cancel, { once: true });
      });
    },
  };
  return validateCredential(await oauth.login(interaction, { agentName: 'nihaixia-tcm' }));
}

async function ipcMain() {
  process.env = {};
  if (process.stdout.isTTY) { process.exitCode = 1; return; }
  const controller = new AbortController();
  let input = '', started = false, finished = false;
  let timer = setTimeout(() => stop('timeout'), 10000);
  const write = event => { if (!finished) process.stdout.write(JSON.stringify(event) + '\n'); };
  const end = event => {
    if (finished) return;
    finished = true; clearTimeout(timer); controller.abort(); process.stdin.pause();
    process.stdout.write(JSON.stringify(event) + '\n', () => process.exit(event.type === 'credential' ? 0 : 1));
  };
  function stop(code) { end({ type: 'error', code, message: 'OpenAI授权未完成，请重试、取消或改用设备码登录' }); }
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (target, init) => {
    const url = new URL(target instanceof Request ? target.url : String(target));
    if (url.protocol !== 'https:' || !['auth.openai.com', 'chatgpt.com'].includes(url.hostname) || url.port || url.username || url.password) throw Error('Unexpected OAuth endpoint');
    return originalFetch(target, { ...init, redirect: 'manual', signal: controller.signal });
  };
  process.stdin.setEncoding('utf8');
  process.stdin.on('data', data => {
    input += data;
    if (Buffer.byteLength(input) > 65536) return stop('input_limit');
    let newline;
    while ((newline = input.indexOf('\n')) !== -1) {
      const line = input.slice(0, newline); input = input.slice(newline + 1);
      let request;
      try { request = JSON.parse(line); } catch { return stop('invalid_request'); }
      if (started) { if (request.type === 'cancel') stop('cancelled'); else stop('invalid_request'); return; }
      started = true;
      clearTimeout(timer); timer = setTimeout(() => stop('timeout'), request.op === 'refresh' ? 30000 : 15 * 60 * 1000);
      void (async () => {
        try {
          const { openaiCodexProvider } = await import('@earendil-works/pi-ai/providers/openai-codex');
          const credential = await performOAuth(request, { oauth: openaiCodexProvider().auth.oauth, emit: write, signal: controller.signal });
          end({ type: 'credential', credential });
        } catch { stop(controller.signal.aborted ? 'cancelled' : 'oauth_failed'); }
      })();
    }
  });
  process.stdin.on('end', () => stop('cancelled'));
  process.stdout.on('error', () => { controller.abort(); process.exit(1); });
  process.on('uncaughtException', () => stop('oauth_failed'));
  process.on('unhandledRejection', () => stop('oauth_failed'));
}

if (process.argv[1] && pathToFileURL(process.argv[1]).href === import.meta.url) void ipcMain();
