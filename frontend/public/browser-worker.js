const base = new URL('./', import.meta.url)
const dataDirectory = '/workbench/data'
const databaseFile = `${dataDirectory}/clinical.sqlite3`
const key = 'clinical'

function openRecords() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(`nihaixia-records:${base.pathname}`, 1)
    request.onupgradeneeded = () => request.result.createObjectStore('snapshots')
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

function readSnapshot(database) {
  return new Promise((resolve, reject) => {
    const request = database.transaction('snapshots').objectStore('snapshots').get(key)
    request.onsuccess = () => resolve(request.result ?? null)
    request.onerror = () => reject(request.error)
  })
}

function saveSnapshot(database, revision, bytes) {
  return new Promise((resolve, reject) => {
    const transaction = database.transaction('snapshots', 'readwrite')
    const store = transaction.objectStore('snapshots')
    const request = store.get(key)
    let next = null
    request.onsuccess = () => {
      if ((request.result?.revision ?? null) !== revision) return
      try {
        next = crypto.randomUUID()
        store.put({ revision: next, bytes }, key)
      } catch {
        transaction.abort()
      }
    }
    transaction.oncomplete = () => resolve(next)
    transaction.onabort = () => reject(transaction.error)
  })
}

async function prepare() {
  const indexURL = new URL('runtime/pyodide/', base).href
  const { loadPyodide } = await import(`${indexURL}pyodide.mjs`)
  const [python, database, archive] = await Promise.all([
    loadPyodide({ indexURL, packages: ['sqlite3'] }),
    openRecords(),
    fetch(new URL('runtime/engine.zip', base)).then(response => {
      if (!response.ok) throw new Error(`Engine archive ${response.status}`)
      return response.arrayBuffer()
    }),
  ])
  python.unpackArchive(archive, 'zip', { extractDir: '/workbench' })
  python.FS.mkdirTree(dataDirectory)
  const stored = await readSnapshot(database)
  if (stored) python.FS.writeFile(databaseFile, stored.bytes)
  python.runPython(`
import sys
sys.path.insert(0, '/workbench')
from app.browser_api import dispatch, initialize
initialize('${dataDirectory}', '/workbench/knowledge')
`)
  return {
    python, database,
    dispatch: python.globals.get('dispatch'),
    revision: stored?.revision ?? null,
    initial: stored ? null : python.FS.readFile(databaseFile),
  }
}

let runtime
let queue = Promise.resolve()
self.addEventListener('message', ({ data }) => {
  if (typeof data?.id !== 'string') return
  const { id, method, path, body } = data
  const respond = (status, value) => self.postMessage({ id, status, body: value })
  queue = queue.then(async () => {
    if (typeof method !== 'string' || typeof path !== 'string' || typeof body !== 'string') {
      respond(400, { detail: '网页请求格式无效' })
      return
    }
    let state
    try {
      runtime ??= prepare()
      state = await runtime
    } catch {
      runtime = undefined
      respond(503, { detail: '网页工作台加载失败，请检查网络及浏览器存储后重新打开' })
      return
    }
    const { python, database, dispatch, initial } = state
    let stored
    try {
      stored = await readSnapshot(database)
      const revision = stored?.revision ?? null
      if (state.revision !== revision) {
        const bytes = stored?.bytes ?? initial
        if (!bytes) {
          respond(409, { detail: '浏览器记录存储已重置，请重新打开工作台' })
          return
        }
        python.FS.writeFile(databaseFile, bytes)
        state.revision = revision
      }
    } catch {
      respond(503, { detail: '读取本机记录失败，请检查浏览器存储后重试' })
      return
    }

    const result = JSON.parse(dispatch(method, path, body))
    // shortcut: write a single SQLite snapshot until record size warrants incremental storage.
    const writes = /^(POST|PUT)$/i.test(method) && /^\/consultations(?:\/|\?|$)/.test(path)
    if (writes && result.status >= 200 && result.status < 300) {
      try {
        const next = await saveSnapshot(database, state.revision, python.FS.readFile(databaseFile))
        if (next === null) {
          python.FS.writeFile(databaseFile, stored?.bytes ?? initial)
          respond(409, { detail: '另一标签页已保存记录，请刷新后重试' })
          return
        }
        state.revision = next
      } catch {
        python.FS.writeFile(databaseFile, stored?.bytes ?? initial)
        respond(507, { detail: '记录未保存，请检查浏览器存储空间后重试' })
        return
      }
    }
    respond(result.status, result.body)
  }).catch(() => respond(500, { detail: '网页工作台处理失败，请重新打开后重试' }))
})
