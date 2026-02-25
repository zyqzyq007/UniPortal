import request from '../utils/request'
import type { AxiosRequestConfig } from 'axios'

export interface Project {
  project_id: string
  name: string
  description?: string
  owner_id: string
  created_at: string
}

export interface CreateProjectParams {
  name: string
  description?: string
}

export const getProjects = () => {
  return request({
    url: '/projects',
    method: 'get'
  })
}

export const getProject = (id: string) => {
  return request({
    url: `/projects/${id}`,
    method: 'get'
  })
}

export const createProject = (data: CreateProjectParams | FormData, config?: AxiosRequestConfig) => {
  return request({
    url: '/projects',
    method: 'post',
    data,
    ...config
  })
}

export const updateProject = (id: string, data: Partial<CreateProjectParams>) => {
  return request({
    url: `/projects/${id}`,
    method: 'put',
    data
  })
}

export const deleteProject = (id: string) => {
  return request({
    url: `/projects/${id}`,
    method: 'delete'
  })
}

export const getProjectStructure = (id: string, path?: string) => {
  return request({
    url: `/projects/${id}/structure`,
    method: 'get',
    params: { path }
  })
}

export const getProjectFileContent = (id: string, path: string) => {
  return request({
    url: `/projects/${id}/file`,
    method: 'get',
    params: { path }
  })
}
