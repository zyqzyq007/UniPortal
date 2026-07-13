import { describe, expect, it, beforeEach } from 'vitest'

import { pushFrontLog } from '../utils/frontLogger'

type MockStorage = {
  _data: Record<string, string>
  getItem(this: MockStorage, key: string): string | null
  setItem(this: MockStorage, key: string, value: string): void
  removeItem(this: MockStorage, key: string): void
}

// Mock localStorage for the logger
const storage: MockStorage = {
  _data: {},
  getItem(key: string) {
    return this._data[key] ?? null
  },
  setItem(key: string, value: string) {
    this._data[key] = value
  },
  removeItem(key: string) {
    delete this._data[key]
  }
}

vi.stubGlobal('localStorage', storage)

// Override the stub with a fresh copy before each test
beforeEach(() => {
  storage._data = {}
})

import { vi } from 'vitest'

describe('frontLogger', () => {
  it('adds log entries', () => {
    pushFrontLog({ level: 'error', message: 'Something failed' })
    pushFrontLog({ level: 'info', message: 'User logged in' })

    const raw = storage._data['uni-portal-front-logs']
    const logs = JSON.parse(raw)
    expect(logs).toHaveLength(2)
    expect(logs[0].level).toBe('info')
    expect(logs[1].level).toBe('error')
  })

  it('caps at 200 entries', () => {
    for (let i = 0; i < 250; i++) {
      pushFrontLog({ level: 'info', message: `msg ${i}` })
    }
    const raw = storage._data['uni-portal-front-logs']
    const logs = JSON.parse(raw)
    expect(logs).toHaveLength(200)
    // Most recent first
    expect(logs[0].message).toBe('msg 249')
  })

  it('each log has a timestamp', () => {
    pushFrontLog({ level: 'info', message: 'test' })
    const raw = storage._data['uni-portal-front-logs']
    const logs = JSON.parse(raw)
    expect(logs[0].time).toBeDefined()
    expect(new Date(logs[0].time).getTime()).toBeGreaterThan(0)
  })

  it('handles code and detail fields', () => {
    pushFrontLog({ level: 'error', message: 'Error', code: 500, detail: 'Stack trace' })
    const raw = storage._data['uni-portal-front-logs']
    const logs = JSON.parse(raw)
    expect(logs[0].code).toBe(500)
    expect(logs[0].detail).toBe('Stack trace')
  })
})
