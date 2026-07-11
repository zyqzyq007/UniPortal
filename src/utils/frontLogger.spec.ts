import { describe, expect, it, beforeEach } from 'vitest'

// Mock localStorage
const store: Record<string, string> = {}
beforeEach(() => {
  Object.keys(store).forEach(k => delete store[k])
})

// Re-define the module-local functions by testing them via localStorage simulation
// Since pushFrontLog is an ESM export, we test it by importing and spying on localStorage
import { pushFrontLog } from '../utils/frontLogger'

// Mock localStorage for the logger
vi.stubGlobal('localStorage', {
  _data: {} as Record<string, string>,
  getItem(key: string) {
    return this._data[key] ?? null
  },
  setItem(key: string, value: string) {
    this._data[key] = value
  },
  removeItem(key: string) {
    delete this._data[key]
  }
})

// Override the stub with a fresh copy before each test
beforeEach(() => {
  ;(globalThis as any).localStorage._data = {}
})

import { vi } from 'vitest'

describe('frontLogger', () => {
  it('adds log entries', () => {
    pushFrontLog({ level: 'error', message: 'Something failed' })
    pushFrontLog({ level: 'info', message: 'User logged in' })

    const raw = (globalThis as any).localStorage._data['uni-portal-front-logs']
    const logs = JSON.parse(raw)
    expect(logs).toHaveLength(2)
    expect(logs[0].level).toBe('info')
    expect(logs[1].level).toBe('error')
  })

  it('caps at 200 entries', () => {
    for (let i = 0; i < 250; i++) {
      pushFrontLog({ level: 'info', message: `msg ${i}` })
    }
    const raw = (globalThis as any).localStorage._data['uni-portal-front-logs']
    const logs = JSON.parse(raw)
    expect(logs).toHaveLength(200)
    // Most recent first
    expect(logs[0].message).toBe('msg 249')
  })

  it('each log has a timestamp', () => {
    pushFrontLog({ level: 'info', message: 'test' })
    const raw = (globalThis as any).localStorage._data['uni-portal-front-logs']
    const logs = JSON.parse(raw)
    expect(logs[0].time).toBeDefined()
    expect(new Date(logs[0].time).getTime()).toBeGreaterThan(0)
  })

  it('handles code and detail fields', () => {
    pushFrontLog({ level: 'error', message: 'Error', code: 500, detail: 'Stack trace' })
    const raw = (globalThis as any).localStorage._data['uni-portal-front-logs']
    const logs = JSON.parse(raw)
    expect(logs[0].code).toBe(500)
    expect(logs[0].detail).toBe('Stack trace')
  })
})
