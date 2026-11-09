const base = new URL('./', import.meta.url)
const dataDirectory = '/workbench/data'
const databaseFile = dataDirectory + '/clinical.sqlite3'
// A cached older app must not overwrite the encrypted model snapshot.
const snapshotKey = 'clinical-library-v3'
const modelSnapshotKey = 'clinical-models-v2'
const legacySnapshotKey = 'clinical'
const encryptionKey = 'encryption-key'
const encoder = new TextEncoder()
const decoder = new TextDecoder('utf-8', { fatal: true })
const activeRequests = new Map()
const responseLimit = 4 * 1024 * 1024
const originalPattern = /^originals\/([a-f0-9]{64})\.(pdf|txt|md|doc|docx)$/
const knowledgePattern = /^knowledge\/(?:active\.json|browser-assets\.json|[a-f0-9]{64}\/(?:manifest\.json|open_formula_library\.json))$/

function openRecords() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('nihaixia-records:' + base.pathname, 1)
    request.onupgradeneeded = () => request.result.createObjectStore('snapshots')
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

function readRecord(database, key) {
  return new Promise((resolve, reject) => {
    const request = database.transaction('snapshots').objectStore('snapshots').get(key)
    request.onsuccess = () => resolve(request.result ?? null)
    request.onerror = () => reject(request.error)
  })
}

async function latestRecord(database) {
  for (const key of [snapshotKey, modelSnapshotKey, legacySnapshotKey]) {
    const value = await readRecord(database, key)
    if (value) return { key, value }
  }
  return { key: null, value: null }
}

async function originalDigest(bytes) {
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))
  return Array.from(digest, value => value.toString(16).padStart(2, '0')).join('')
}

async function getEncryptionKey(database) {
  const current = await readRecord(database, encryptionKey)
  if (current) return current
  const generated = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt'])
  return new Promise((resolve, reject) => {
    const transaction = database.transaction('snapshots', 'readwrite')
    const store = transaction.objectStore('snapshots')
    const request = store.get(encryptionKey)
    let selected
    request.onsuccess = () => {
      selected = request.result ?? generated
      if (!request.result) {
        try { store.put(generated, encryptionKey) }
        catch { transaction.abort() }
      }
    }
    transaction.oncomplete = () => resolve(selected)
    transaction.onabort = () => reject(transaction.error)
  })
}

function captureFiles(python) {
  const files = [['clinical.sqlite3', python.FS.readFile(databaseFile)]]
  function collect(directory) {
    for (const name of python.FS.readdir(dataDirectory + '/' + directory).sort()) {
      if (name === '.' || name === '..') continue
      const relative = directory + '/' + name
      const stat = python.FS.lstat(dataDirectory + '/' + relative)
      if (python.FS.isDir(stat.mode)) collect(relative)
      else if (python.FS.isFile(stat.mode)) {
        if (relative.startsWith('knowledge/') && !knowledgePattern.test(relative)) throw new Error('Unsupported knowledge resource')
        files.push([relative, python.FS.readFile(dataDirectory + '/' + relative)])
      }
      else throw new Error('Unsupported model storage')
    }
  }
  for (const directory of ['models', 'knowledge']) {
    if (python.FS.analyzePath(dataDirectory + '/' + directory).exists) collect(directory)
  }
  const header = encoder.encode(JSON.stringify(files.map(([name, bytes]) => [name, bytes.length])))
  if (header.length > 128 * 1024) throw new Error('Snapshot metadata too large')
  const bytes = new Uint8Array(4 + header.length + files.reduce((total, [, value]) => total + value.length, 0))
  new DataView(bytes.buffer).setUint32(0, header.length)
  bytes.set(header, 4)
  let position = 4 + header.length
  for (const [, value] of files) {
    bytes.set(value, position)
    position += value.length
  }
  return bytes
}

function snapshotFiles(bytes) {
  if (!(bytes instanceof Uint8Array) || bytes.length < 4) throw new Error('Invalid snapshot')
  const length = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength).getUint32(0)
  if (length > 128 * 1024 || length > bytes.length - 4) throw new Error('Invalid snapshot header')
  const entries = JSON.parse(decoder.decode(bytes.subarray(4, 4 + length)))
  if (!Array.isArray(entries) || entries.length === 0) throw new Error('Invalid snapshot files')
  let position = 4 + length
  const files = new Map()
  for (const entry of entries) {
    if (!Array.isArray(entry) || entry.length !== 2) throw new Error('Invalid snapshot file')
    const [name, size] = entry
    if (typeof name !== 'string' || (name !== 'clinical.sqlite3' && !/^models\/[a-zA-Z0-9_.\/-]+$/.test(name) && !knowledgePattern.test(name))
        || name.split('/').some(part => part === '..' || part === '.' || !part)
        || files.has(name) || !Number.isSafeInteger(size) || size < 0 || size > bytes.length - position) {
      throw new Error('Invalid snapshot entry')
    }
    files.set(name, bytes.subarray(position, position + size))
    position += size
  }
  if (!files.has('clinical.sqlite3') || position !== bytes.length) throw new Error('Invalid snapshot content')
  return files
}

function restoreFiles(python, bytes) {
  const files = snapshotFiles(bytes)
  function remove(directory) {
    for (const name of python.FS.readdir(directory)) {
      if (name === '.' || name === '..') continue
      const path = directory + '/' + name
      if (python.FS.isDir(python.FS.lstat(path).mode)) {
        remove(path)
        python.FS.rmdir(path)
      } else python.FS.unlink(path)
    }
  }
  for (const directory of ['models', 'knowledge']) {
    const path = dataDirectory + '/' + directory
    if (python.FS.analyzePath(path).exists) remove(path)
  }
  for (const [name, value] of files) {
    const path = dataDirectory + '/' + name
    python.FS.mkdirTree(path.slice(0, path.lastIndexOf('/')))
    python.FS.writeFile(path, value)
  }
}

function legacySnapshot(bytes) {
  const value = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes)
  const header = encoder.encode(JSON.stringify([['clinical.sqlite3', value.length]]))
  const result = new Uint8Array(4 + header.length + value.length)
  new DataView(result.buffer).setUint32(0, header.length)
  result.set(header, 4)
  result.set(value, 4 + header.length)
  return result
}

function encryptionParameters(revision, iv) {
  return { name: 'AES-GCM', iv, additionalData: encoder.encode(base.pathname + ':' + revision) }
}

async function decodeRecord(state, record) {
  if (record.version !== 2 && record.version !== 3) {
    if (!(record.bytes instanceof Uint8Array) && !(record.bytes instanceof ArrayBuffer)) throw new Error('Invalid legacy record')
    return legacySnapshot(record.bytes)
  }
  const value = await crypto.subtle.decrypt(encryptionParameters(record.revision, record.iv), state.key, record.ciphertext)
  const bytes = new Uint8Array(value)
  snapshotFiles(bytes)
  return bytes
}

async function saveSnapshot(state, bytes) {
  const revision = crypto.randomUUID()
  const iv = crypto.getRandomValues(new Uint8Array(12))
  const ciphertext = await crypto.subtle.encrypt(encryptionParameters(revision, iv), state.key, bytes)
  return new Promise((resolve, reject) => {
    const transaction = state.database.transaction('snapshots', 'readwrite')
    const store = transaction.objectStore('snapshots')
    const request = store.get(snapshotKey)
    let saved = false
    request.onsuccess = () => {
      if ((request.result?.revision ?? null) !== state.revision) return
      const write = () => {
        try {
          store.put({ revision, version: 3, iv, ciphertext }, snapshotKey)
          if (state.legacyKey !== null) store.delete(state.legacyKey)
          saved = true
        } catch { transaction.abort() }
      }
      if (state.legacyKey === null) write()
      else {
        const legacy = store.get(state.legacyKey)
        legacy.onsuccess = () => {
          if ((legacy.result?.revision ?? null) === state.legacyRevision) write()
        }
      }
    }
    transaction.oncomplete = () => resolve(saved ? revision : null)
    transaction.onabort = () => reject(transaction.error)
  })
}

async function relayConfiguration() {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 5000)
  try {
    const response = await fetch(new URL('runtime/relay.json', base), {
      signal: controller.signal, credentials: 'omit', redirect: 'error', cache: 'no-store',
    })
    if (!response.ok) return null
    const value = await response.json()
    const url = new URL(value.url)
    const local = url.origin === base.origin && url.protocol === 'http:'
    if ((url.protocol !== 'https:' && !local) || url.username || url.password || url.hash) return null
    if (!Array.isArray(value.providers) || !value.providers.every(host => typeof host === 'string' && /^[a-z0-9.-]+$/.test(host))) return null
    return { url: url.href, providers: new Set(value.providers) }
  } catch { return null }
  finally { clearTimeout(timeout) }
}

async function prepare() {
  const indexURL = new URL('runtime/pyodide/', base).href
  const { loadPyodide } = await import(indexURL + 'pyodide.mjs')
  const [python, database, archive, relay] = await Promise.all([
    loadPyodide({ indexURL, packages: ['sqlite3'] }),
    openRecords(),
    fetch(new URL('runtime/engine.zip', base)).then(response => {
      if (!response.ok) throw new Error('Engine archive unavailable')
      return response.arrayBuffer()
    }),
    relayConfiguration(),
  ])
  python.unpackArchive(archive, 'zip', { extractDir: '/workbench' })
  python.FS.mkdirTree(dataDirectory)
  const state = { python, database, relay, key: await getEncryptionKey(database) }
  const selected = await latestRecord(database)
  const stored = selected.value
  const bytes = stored ? await decodeRecord(state, stored) : null
  if (bytes) restoreFiles(python, bytes)
  python.runPython([
    'import sys, json',
    "sys.path.insert(0, '/workbench')",
    'from app.browser_api import (dispatch, initialize, take_requests, complete_request, fail_request, checkpoint, restore_checkpoint, pending_request_ids, original_info, activate_library)',
    "initialize('" + dataDirectory + "', '/workbench/knowledge')",
    'def browser_take_requests():',
    '    return json.dumps(take_requests(), ensure_ascii=False, allow_nan=False)',
    'def browser_pending_requests():',
    '    return json.dumps(pending_request_ids())',
    'def browser_complete_request(request_id, value):',
    '    complete_request(request_id, json.loads(value))',
    'def browser_original_info(source_id):',
    '    return json.dumps(original_info(source_id), ensure_ascii=False, allow_nan=False)',
  ].join('\n'))
  if (bytes) python.globals.get('activate_library')()
  return Object.assign(state, {
    dispatch: python.globals.get('dispatch'),
    takeRequests: python.globals.get('browser_take_requests'),
    pendingRequests: python.globals.get('browser_pending_requests'),
    completeRequest: python.globals.get('browser_complete_request'),
    failRequest: python.globals.get('fail_request'),
    checkpoint: python.globals.get('checkpoint'),
    restoreCheckpoint: python.globals.get('restore_checkpoint'),
    originalInfo: python.globals.get('browser_original_info'),
    activateLibrary: python.globals.get('activate_library'),
    revision: selected.key === snapshotKey ? stored.revision : null,
    legacyKey: selected.key === snapshotKey ? null : selected.key,
    legacyRevision: selected.key === snapshotKey ? null : stored?.revision ?? null,
    current: bytes,
    encrypted: selected.key === snapshotKey && stored?.version === 3,
    initial: stored ? null : captureFiles(python),
  })
}

function sameBytes(first, second) {
  return first && first.length === second.length && first.every((value, index) => value === second[index])
}

async function refreshSnapshot(state) {
  const selected = await latestRecord(state.database)
  const stored = selected.value
  const revision = selected.key === snapshotKey ? stored.revision : null
  const legacyKey = selected.key === snapshotKey ? null : selected.key
  const legacyRevision = legacyKey === null ? null : stored?.revision ?? null
  if (state.revision === revision && state.legacyKey === legacyKey && state.legacyRevision === legacyRevision) return
  const bytes = stored ? await decodeRecord(state, stored) : state.initial
  if (!bytes) throw Object.assign(new Error('浏览器记录存储已重置，请重新打开工作台'), { status: 409 })
  restoreFiles(state.python, bytes)
  state.activateLibrary()
  state.current = bytes
  state.revision = revision
  state.legacyKey = legacyKey
  state.legacyRevision = legacyRevision
  state.encrypted = selected.key === snapshotKey && stored?.version === 3
}

let runtime
let queue = Promise.resolve()
function enqueue(action) {
  const operation = queue.then(action)
  queue = operation.catch(() => {})
  return operation
}

async function transact(action) {
  runtime ??= prepare()
  let state
  try { state = await runtime }
  catch {
    runtime = undefined
    throw Object.assign(new Error('网页工作台加载失败，请检查网络及浏览器存储后重新打开'), { status: 503 })
  }
  for (let attempt = 0; attempt < 3; attempt++) {
    await refreshSnapshot(state)
    const before = captureFiles(state.python)
    const checkpoint = state.checkpoint()
    try {
      const result = await action(state)
      const requests = JSON.parse(state.takeRequests())
      const pending = new Set(JSON.parse(state.pendingRequests()))
      const bytes = captureFiles(state.python)
      if (!state.encrypted || !sameBytes(state.current, bytes)) {
        const revision = await saveSnapshot(state, bytes)
        if (revision === null) {
          restoreFiles(state.python, before)
          state.restoreCheckpoint(checkpoint)
          continue
        }
        state.current = bytes
        state.revision = revision
        state.legacyKey = null
        state.legacyRevision = null
        state.encrypted = true
      }
      for (const [id, active] of activeRequests) {
        if (!pending.has(id)) {
          active.cancelled = true
          clearTimeout(active.delay)
          active.controller.abort()
          activeRequests.delete(id)
        }
      }
      for (const request of requests) {
        if (pending.has(request.id)) startRequest(state, request)
      }
      return result
    } catch (error) {
      restoreFiles(state.python, before)
      state.restoreCheckpoint(checkpoint)
      if (error?.status) throw error
      throw Object.assign(new Error('本次修改未保存，请检查浏览器存储空间后重试'), { status: 507 })
    } finally { checkpoint?.destroy?.() }
  }
  throw Object.assign(new Error('其他标签页正在保存记录，请稍后重试'), { status: 409 })
}

async function responseBody(response, controller) {
  const reader = response.body?.getReader()
  if (!reader) return ''
  const chunks = []
  let length = 0
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    length += value.length
    if (length > responseLimit) {
      controller.abort()
      throw new Error('Response too large')
    }
    chunks.push(value)
  }
  const bytes = new Uint8Array(length)
  let position = 0
  for (const chunk of chunks) {
    bytes.set(chunk, position)
    position += chunk.length
  }
  return decoder.decode(bytes)
}

function startRequest(state, spec) {
  if (activeRequests.has(spec.id)) return
  const active = { controller: new AbortController(), cancelled: false, delay: null }
  activeRequests.set(spec.id, active)
  active.delay = setTimeout(async () => {
    if (active.cancelled) return
    let timedOut = false
    const timeout = setTimeout(() => {
      timedOut = true
      active.controller.abort()
    }, Math.min(Math.max(Number(spec.timeout_ms) || 90000, 1000), 300000))
    let response
    let failure
    try {
      const url = new URL(spec.url)
      const relay = state.relay && url.protocol === 'https:' && !url.port && state.relay.providers.has(url.hostname)
      const target = relay ? state.relay.url : url.href
      const options = {
        method: relay ? 'POST' : spec.method,
        headers: relay ? { 'Content-Type': 'application/json' } : spec.headers,
        body: relay ? JSON.stringify({ url: spec.url, method: spec.method, headers: spec.headers, body: spec.body }) : (spec.body || undefined),
        signal: active.controller.signal,
        credentials: 'omit', redirect: 'error', referrerPolicy: 'no-referrer', cache: 'no-store',
      }
      const result = await fetch(target, options)
      response = {
        status: result.status,
        headers: Object.fromEntries(['content-type', 'retry-after'].map(name => [name, result.headers.get(name)]).filter(([, value]) => value !== null)),
        body: await responseBody(result, active.controller),
      }
    } catch { failure = timedOut ? 'timeout' : active.cancelled ? 'cancelled' : 'network_error' }
    finally {
      clearTimeout(timeout)
      activeRequests.delete(spec.id)
    }
    if (active.cancelled) return
    try {
      await enqueue(() => transact(current => {
        if (failure) current.failRequest(spec.id, failure)
        else current.completeRequest(spec.id, JSON.stringify(response))
        return null
      }))
    } catch {
      // A consumed HTTP response can fail persistence; leave its job explicitly failed.
      await enqueue(async () => {
        const current = await runtime
        current.failRequest(spec.id, 'storage_error')
      }).catch(() => {})
    }
  }, Math.min(Math.max(Number(spec.delay_ms) || 0, 0), 30000))
}

async function readOriginal(state, sourceId) {
  let info
  try { info = JSON.parse(state.originalInfo(sourceId)) }
  catch { throw Object.assign(new Error('原件不存在或尚未完成导入'), { status: 404 }) }
  const relative = info.path.startsWith(dataDirectory + '/') ? info.path.slice(dataDirectory.length + 1) : info.path
  if (!originalPattern.test(relative) || info.sha256 !== sourceId || !relative.startsWith('originals/' + sourceId + '.')) throw new Error('Invalid original path')
  let bytes
  if (state.python.FS.analyzePath(dataDirectory + '/' + relative).exists) {
    bytes = state.python.FS.readFile(dataDirectory + '/' + relative)
  } else {
    throw Object.assign(new Error('原件未随网页知识库载入'), { status: 404 })
  }
  if (await originalDigest(bytes) !== sourceId) throw new Error('Original identity changed')
  return { status: 200, bytes: bytes.buffer, content_type: info.mime, filename: info.filename }
}

self.addEventListener('message', ({ data }) => {
  if (typeof data?.id !== 'string') return
  const { id, method, path, body } = data
  const respond = (status, value) => self.postMessage({ id, status, body: value })
  if (typeof method !== 'string' || typeof path !== 'string' || typeof body !== 'string') {
    respond(400, { detail: '网页请求格式无效' })
    return
  }
  const original = method === 'GET' && /^\/library\/sources\/([a-f0-9]{64})\/original$/.exec(path)
  enqueue(() => transact(state => original ? readOriginal(state, original[1]) : JSON.parse(state.dispatch(method, path, body))))
    .then(result => {
      if (result.bytes) self.postMessage({ id, ...result }, [result.bytes])
      else respond(result.status, result.body)
    })
    .catch(error => respond(error?.status ?? 503, { detail: error?.status ? error.message : '浏览器存储读取失败，请重新打开工作台' }))
})
