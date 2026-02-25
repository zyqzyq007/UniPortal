import axios from 'axios';
import router from '../router';
// Create Axios instance
const service = axios.create({
    baseURL: '/api', // Proxy target
    timeout: 10000,
    withCredentials: true // Allow cookies
});
// Request interceptor
service.interceptors.request.use((config) => {
    // Add token if exists in localStorage (optional if using cookies)
    // const token = localStorage.getItem('token')
    // if (token) {
    //   config.headers.Authorization = `Bearer ${token}`
    // }
    return config;
}, (error) => {
    return Promise.reject(error);
});
// Response interceptor
service.interceptors.response.use((response) => {
    return response.data;
}, (error) => {
    const { response } = error;
    if (response) {
        const { status, data, headers } = response;
        const contentType = headers?.['content-type'] || '';
        const isEmptyBody = data === '' || data === undefined || data === null;
        const isNonJson = typeof data === 'string' && !contentType.includes('application/json');
        if (status === 401) {
            // Redirect to login on 401
            if (router.currentRoute.value.path !== '/login') {
                router.push('/login');
            }
        }
        if (status >= 500 && (isEmptyBody || isNonJson)) {
            return Promise.reject({
                code: 503,
                message: '后端服务不可用，请确认服务已启动并监听 8080',
                data: data
            });
        }
        // Return custom error format
        return Promise.reject({
            code: status,
            message: data.message || 'Error',
            data: data
        });
    }
    return Promise.reject({
        code: 503,
        message: '网络异常或后端不可用',
        data: error.message || 'Network Error'
    });
});
export default service;
