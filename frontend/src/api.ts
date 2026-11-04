export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) { super(message); this.status = status }
}
export class ApiClient {
  base: string
  token = ''
  constructor(base = '') { this.base = base }
  async session() {
    const response = await fetch(`${this.base}/api/session`, {credentials:'same-origin'})
    if (!response.ok) throw new ApiError(response.status, '会话初始化失败')
    const session = await response.json()
    this.token = session.csrf_token
    return session
  }
  async request<T = any>(path: string, options: RequestInit = {}): Promise<T> {
    if (!this.token) await this.session()
    const headers = new Headers(options.headers)
    if (options.method && !['GET','HEAD'].includes(options.method.toUpperCase())) headers.set('X-CSRF-Token', this.token)
    if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json')
    const response = await fetch(`${this.base}/api${path}`, {...options, headers, credentials:'same-origin'})
    if (!response.ok) {
      const problem = await response.json().catch(() => ({detail:response.statusText}))
      throw new ApiError(response.status, typeof problem.detail === 'string' ? problem.detail : JSON.stringify(problem.detail))
    }
    if (response.headers.get('content-type')?.includes('application/json')) return response.json()
    return await response.blob() as T
  }
  post<T = any>(path: string, data: unknown): Promise<T> { return this.request(path,{method:'POST',body:JSON.stringify(data)}) }
  put<T = any>(path: string, data: unknown): Promise<T> { return this.request(path,{method:'PUT',body:JSON.stringify(data)}) }
}
export const api = new ApiClient()
