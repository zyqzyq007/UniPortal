const TOKEN_KEY = 'uni-portal-token'
const USER_KEY = 'uni-portal-user'
const AVATAR_KEY = 'uni-portal-avatar'
const EMAIL_KEY = 'uni-portal-email'

export const getToken = () => localStorage.getItem(TOKEN_KEY)

export const setToken = (token: string) => {
  localStorage.setItem(TOKEN_KEY, token)
}

export const clearToken = () => {
  localStorage.removeItem(TOKEN_KEY)
}

export const setUserName = (name: string) => {
  localStorage.setItem(USER_KEY, name)
}

export const getUserName = () => localStorage.getItem(USER_KEY) || '未登录'

export const getUserAvatar = () => localStorage.getItem(AVATAR_KEY) || ''
export const setUserAvatar = (avatar: string) => localStorage.setItem(AVATAR_KEY, avatar)

export const getUserEmail = () => localStorage.getItem(EMAIL_KEY) || ''
export const setUserEmail = (email: string) => localStorage.setItem(EMAIL_KEY, email)

export const clearUser = () => {
  localStorage.removeItem(USER_KEY)
  localStorage.removeItem(AVATAR_KEY)
  localStorage.removeItem(EMAIL_KEY)
}
