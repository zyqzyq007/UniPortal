import request from '../utils/request';
export const getProjects = () => {
    return request({
        url: '/projects',
        method: 'get'
    });
};
export const getProject = (id) => {
    return request({
        url: `/projects/${id}`,
        method: 'get'
    });
};
export const createProject = (data, config) => {
    return request({
        url: '/projects',
        method: 'post',
        data,
        ...config
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
export const getProjectStructure = (id, path) => {
    return request({
        url: `/projects/${id}/structure`,
        method: 'get',
        params: { path }
    });
};
export const getProjectFileContent = (id, path) => {
    return request({
        url: `/projects/${id}/file`,
        method: 'get',
        params: { path }
    });
};
