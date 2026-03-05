import request from '../utils/request';
export const getProjects = (params) => {
    return request({
        url: '/projects',
        method: 'get',
        params
    });
};
export const getProject = (id) => {
    return request({
        url: `/projects/${id}`,
        method: 'get'
    });
};
export const createProject = (data) => {
    return request({
        url: '/projects',
        method: 'post',
        data
    });
};
export const updateProject = (id, data) => {
    return request({
        url: `/projects/${id}`,
        method: 'put',
        data
    });
};
export const deleteProject = (id) => {
    return request({
        url: `/projects/${id}`,
        method: 'delete'
    });
};
export const uploadSoftwareItem = (id, formData, config) => {
    return request({
        url: `/projects/${id}/items/upload`,
        method: 'post',
        data: formData,
        ...config
    });
};
export const getSoftwareItems = (id, params) => {
    return request({
        url: `/projects/${id}/items`,
        method: 'get',
        params
    });
};
export const deleteSoftwareItem = (id, itemId) => {
    return request({
        url: `/projects/${id}/items/${itemId}`,
        method: 'delete'
    });
};
export const downloadSoftwareItem = (id, itemId) => {
    // For download, we might want to open a new window or use a specific download handler
    // But returning the request config is fine if we use window.open or similar
    // Or we can use blob response type
    return `/api/projects/${id}/items/${itemId}/download`;
};
export const getProjectStructure = (id, path) => {
    return request({
        url: `/projects/${id}/structure`,
        method: 'get',
        params: { path }
    });
};
export const getProjectFileContent = (id, filePath) => {
    return request({
        url: `/projects/${id}/file`,
        method: 'get',
        params: { path: filePath }
    });
};
export const getItemStructure = (projectId, itemId, nodePath = '') => {
    return request({
        url: `/projects/${projectId}/items/${itemId}/structure`,
        method: 'get',
        params: { path: nodePath }
    });
};
export const getItemFileContent = (projectId, itemId, filePath, params) => {
    return request({
        url: `/projects/${projectId}/items/${itemId}/file`,
        method: 'get',
        params: { path: filePath, ...params }
    });
};
export const operateItemNode = (projectId, itemId, payload) => {
    return request({
        url: `/projects/${projectId}/items/${itemId}/fs/node`,
        method: 'post',
        data: payload
    });
};
