import request from '../utils/request'

export interface LoginParams {
  username: string
  password: string
}

export interface RegisterParams {
  username: string
  password: string
}

export interface UserInfo {
  id: string
  username: string
  last_login?: string
}

export const login = (data: LoginParams) => {
  return request({
    url: '/auth/login',
    method: 'post',
    data
  })
}

export const register = (data: RegisterParams) => {
  return request({
    url: '/auth/register',
    method: 'post',
    data
  })
}

export const getUserInfo = () => {
  return request({
    url: '/auth/me',
    method: 'get'
  })
}
