import { describe, expect, it, beforeEach } from 'vitest'

// Simulate module-level state
let localStorageStore: Record<string, string> = {}

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

beforeEach(() => {
  ;(globalThis as any).localStorage._data = {}
})

import {
  getToken,
  setToken,
  clearToken,
  setUserName,
  getUserName,
  setUserAvatar,
  getUserAvatar,
  setUserEmail,
  getUserEmail,
  clearUser
} from '../utils/auth'
import { vi } from 'vitest'

describe('auth utils', () => {
  const ls = () => (globalThis as any).localStorage._data as Record<string, string>

  describe('token', () => {
    it('setToken stores token', () => {
      setToken('my-token-123')
      expect(ls()['uni-portal-token']).toBe('my-token-123')
    })

    it('getToken retrieves token', () => {
      ls()['uni-portal-token'] = 'stored-token'
      expect(getToken()).toBe('stored-token')
    })

    it('getToken returns null when not set', () => {
      expect(getToken()).toBeNull()
    })

    it('clearToken removes token', () => {
      setToken('token')
      clearToken()
      expect(ls()['uni-portal-token']).toBeUndefined()
    })
  })

  describe('username', () => {
    it('stores and retrieves username', () => {
      setUserName('Alice')
      expect(getUserName()).toBe('Alice')
    })

    it('defaults to 未登录 when not set', () => {
      expect(getUserName()).toBe('未登录')
    })
  })

  describe('avatar', () => {
    it('stores and retrieves avatar', () => {
      setUserAvatar('https://example.com/avatar.png')
      expect(getUserAvatar()).toBe('https://example.com/avatar.png')
    })

    it('defaults to empty string', () => {
      expect(getUserAvatar()).toBe('')
    })
  })

  describe('email', () => {
    it('stores and retrieves email', () => {
      setUserEmail('test@example.com')
      expect(getUserEmail()).toBe('test@example.com')
    })

    it('defaults to empty string', () => {
      expect(getUserEmail()).toBe('')
    })
  })

  describe('clearUser', () => {
    it('clears all user data', () => {
      setUserName('Bob')
      setUserAvatar('avatar.png')
      setUserEmail('bob@test.com')

      clearUser()

      expect(ls()['uni-portal-user']).toBeUndefined()
      expect(ls()['uni-portal-avatar']).toBeUndefined()
      expect(ls()['uni-portal-email']).toBeUndefined()
    })
  })
})
