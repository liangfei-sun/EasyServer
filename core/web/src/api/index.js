import axios from 'axios'

const api = axios.create({ baseURL: '/api', timeout: 30000 })

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

// 备份管理
export const getBackupStatus = () => api.get('/backup/status')
export const triggerBackup = () => api.post('/backup/trigger')
export const updateBackupSchedule = (schedule, retainDays) => api.put('/backup/schedule', { schedule, retain_days: retainDays })

export default api
