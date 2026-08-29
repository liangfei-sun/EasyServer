import axios from 'axios'
import { ElMessage } from 'element-plus'

const api = axios.create({ baseURL: '/api', timeout: 30000 })

// 请求拦截器：自动附加 Authorization header
api.interceptors.request.use(config => {
  const token = localStorage.getItem('easyserver_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截器：统一错误处理
api.interceptors.response.use(
  response => response,
  error => {
    if (error.response) {
      const { status, data } = error.response
      if (status === 401) {
        // Token 过期或无效，清除并跳转登录
        localStorage.removeItem('easyserver_token')
        // 避免在登录/setup 页面重复跳转
        const currentPath = window.location.hash?.replace('#', '') || ''
        if (!['/login', '/setup'].includes(currentPath)) {
          ElMessage.warning('登录已过期，请重新登录')
          window.location.hash = '#/login'
        }
        return Promise.reject(error)
      }
      // 显示后端返回的错误信息
      const detail = data?.detail
      if (detail && typeof detail === 'string') {
        ElMessage.error(detail)
      }
    } else if (error.code === 'ECONNABORTED') {
      ElMessage.error('请求超时，请检查服务是否运行正常')
    } else if (!error.response) {
      ElMessage.error('网络异常，请检查服务是否运行正常')
    }
    return Promise.reject(error)
  }
)

export const getServices = () => api.get('/services')
export const getService = (id) => api.get(`/services/${id}`)
export const startService = (id) => api.post(`/services/${id}/start`)
export const stopService = (id) => api.post(`/services/${id}/stop`)
export const restartService = (id) => api.post(`/services/${id}/restart`)
export const updateService = (id) => api.post(`/services/${id}/update`)
export const getServiceLogs = (id, lines = 100) => api.get(`/services/${id}/logs`, { params: { lines } })
export const checkPorts = () => api.get('/services/port-check')
export const updateServicePort = (id, port) => api.put(`/services/${id}/port`, null, { params: { port } })

export const getConfig = () => api.get('/config')
export const updateConfig = (data) => api.put('/config', data)
export const getSetupStatus = () => api.get('/config/setup/status')
export const completeSetup = () => api.post('/config/setup/complete')
export const generatePassword = () => api.post('/config/generate-password')

export const getModules = () => api.get('/modules')
export const getModule = (id) => api.get(`/modules/${id}`)
export const installModule = (moduleId, config) => api.post('/modules/install', { module_id: moduleId, config })
export const uninstallModule = (id) => api.post(`/modules/${id}/uninstall`)

export const generateNginx = () => api.post('/nginx/generate')
export const reloadNginx = () => api.post('/nginx/reload')

export const getDocList = () => api.get('/docs')
export const getDoc = (docId) => api.get(`/docs/${docId}`)
export const getModuleDocs = (moduleId) => api.get(`/docs/modules/${moduleId}`)

// 配置文件编辑
export const getConfigFiles = () => api.get('/config/files')
export const getConfigFile = (filename) => api.get(`/config/files/${filename}`)
export const updateConfigFile = (filename, content) => api.put(`/config/files/${filename}`, { content })

// 备份管理
export const getBackupStatus = () => api.get('/backup/status')
export const triggerBackup = () => api.post('/backup/trigger')
export const updateBackupSchedule = (schedule, retainDays) => api.put('/backup/schedule', { schedule, retain_days: retainDays })

export default api
