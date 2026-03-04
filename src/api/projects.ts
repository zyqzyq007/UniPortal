import request from '../utils/request'
import type { AxiosRequestConfig } from 'axios'

export interface Project {
  project_id: string
  name: string
  description?: string
  owner_id: string
  created_at: string
  updated_at: string
  item_count: number
  last_upload_at?: string
}

export interface SoftwareItem {
    item_id: string
    name: string
    description?: string
    version?: string
    file_path: string
    file_size: string
    uploaded_at: string
    project_id: string
    created_by: string
}

export interface FileTreeNode {
  name: string
  type: 'dir' | 'file'
  path: string
  size?: number
  updated_at?: string
  children?: FileTreeNode[]
}

export interface FileContentResponse {
  kind: 'text' | 'binary'
  path: string
  size: number
  updated_at: string
  language: string
  mime_type: string
  content?: string
  content_base64?: string
  offset?: number
  limit?: number
  eof?: boolean
}

export interface GetProjectsParams {
    search?: string
    sort?: string
    order?: 'asc' | 'desc'
    page?: number
    limit?: number
}

export interface GetSoftwareItemsParams {
    search?: string
    page?: number
    limit?: number
}

export interface CreateProjectParams {
  name: string
  description?: string
}

export const getProjects = (params?: GetProjectsParams) => {
  return request({
    url: '/projects',
    method: 'get',
    params
  })
}

export const getProject = (id: string) => {
  return request({
    url: `/projects/${id}`,
    method: 'get'
  })
}

export const createProject = (data: CreateProjectParams) => {
  return request({
    url: '/projects',
    method: 'post',
    data
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

export const uploadSoftwareItem = (id: string, formData: FormData, config?: AxiosRequestConfig) => {
    return request({
        url: `/projects/${id}/items/upload`,
        method: 'post',
        data: formData,
        ...config
    })
}

export const getSoftwareItems = (id: string, params?: GetSoftwareItemsParams) => {
    return request({
        url: `/projects/${id}/items`,
        method: 'get',
        params
    })
}

export const deleteSoftwareItem = (id: string, itemId: string) => {
    return request({
        url: `/projects/${id}/items/${itemId}`,
        method: 'delete'
    })
}

export const downloadSoftwareItem = (id: string, itemId: string) => {
    // For download, we might want to open a new window or use a specific download handler
    // But returning the request config is fine if we use window.open or similar
    // Or we can use blob response type
    return `/api/projects/${id}/items/${itemId}/download`
}

export const getProjectStructure = (id: string, path?: string) => {
  return request({
    url: `/projects/${id}/structure`,
    method: 'get',
    params: { path }
  })
}

export const getProjectFileContent = (id: string, filePath: string) => {
  return request({
    url: `/projects/${id}/file`,
    method: 'get',
    params: { path: filePath }
  })
}

export const getItemStructure = (projectId: string, itemId: string, nodePath = '') => {
  return request({
    url: `/projects/${projectId}/items/${itemId}/structure`,
    method: 'get',
    params: { path: nodePath }
  })
}

export const getItemFileContent = (
  projectId: string,
  itemId: string,
  filePath: string,
  params?: { allowLarge?: boolean; offset?: number; limit?: number }
) => {
  return request({
    url: `/projects/${projectId}/items/${itemId}/file`,
    method: 'get',
    params: { path: filePath, ...params }
  })
}

export const operateItemNode = (
  projectId: string,
  itemId: string,
  payload: {
    action: 'new_file' | 'new_folder' | 'rename' | 'delete'
    path: string
    newName?: string
  }
) => {
  return request({
    url: `/projects/${projectId}/items/${itemId}/fs/node`,
    method: 'post',
    data: payload
  })
}
