import { describe, expect, it, beforeEach, vi, beforeAll } from 'vitest'

const STORAGE_KEY = 'TOOL_SERVER_HOST'
const storage = {
  _data: {} as Record<string, string>,
  getItem(key: string) { return this._data[key] ?? null },
  setItem(key: string, value: string) { this._data[key] = value },
  removeItem(key: string) { delete this._data[key] }
}

vi.stubGlobal('localStorage', storage)

// Dynamic import to ensure localStorage mock is in place before module evaluation
let serverHost: any
let resetServerHost: any
let getToolUrl: any

beforeAll(async () => {
  const mod = await import('../store/toolConfig')
  serverHost = mod.serverHost
  resetServerHost = mod.resetServerHost
  getToolUrl = mod.getToolUrl
})

beforeEach(() => {
  storage._data = {}
  serverHost.value = '211.71.15.55'
})

describe('toolConfig', () => {
  it('defaults to 211.71.15.55 when no saved value', () => {
    expect(serverHost.value).toBe('211.71.15.55')
  })

  it('can change and read serverHost value', () => {
    serverHost.value = '192.168.1.100'
    expect(serverHost.value).toBe('192.168.1.100')
  })

  it('resetServerHost restores default', () => {
    serverHost.value = '10.0.0.1'
    resetServerHost()
    expect(serverHost.value).toBe('211.71.15.55')
  })

  describe('getToolUrl', () => {
    it('replaces default host in URL', () => {
      serverHost.value = '192.168.1.100'
      const result = getToolUrl('http://211.71.15.55:5001/static/index.html')
      expect(result).toBe('http://192.168.1.100:5001/static/index.html')
    })

    it('works with different port', () => {
      serverHost.value = '10.0.0.1'
      const result = getToolUrl('http://211.71.15.55:8080/path')
      expect(result).toBe('http://10.0.0.1:8080/path')
    })

    it('returns empty string for empty input', () => {
      expect(getToolUrl('')).toBe('')
    })

    it('preserves URLs without default host', () => {
      serverHost.value = '192.168.1.100'
      expect(getToolUrl('http://example.com/api')).toBe('http://example.com/api')
    })
  })
})
