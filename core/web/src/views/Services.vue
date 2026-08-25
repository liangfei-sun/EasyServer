<template>
  <div class="services-page" v-loading="loading">
    <div style="display: flex; justify-content: space-between; align-items: center">
      <h2>服务管理</h2>
      <el-tag type="info" size="large">共 {{ services.length }} 个服务，{{ services.filter(s => s.status === 'running').length }} 个运行中</el-tag>
      <el-button @click="loadServices" :loading="loading" style="margin-left: 8px">
        <el-icon><Refresh /></el-icon> 刷新
      </el-button>
    </div>

    <!-- 端口冲突警告 -->
    <el-alert v-if="portConflicts.length" type="warning" show-icon :closable="false" style="margin-bottom: 16px">
      <template #title>
        <span style="font-weight: 600">端口冲突检测</span>
      </template>
      <template #default>
        <div v-for="(c, i) in portConflicts" :key="i" style="margin-top: 4px">{{ c.message }}</div>
        <el-button size="small" type="warning" plain @click="checkPorts" style="margin-top: 8px">重新检测</el-button>
      </template>
    </el-alert>
    <el-alert v-else-if="portCheckDone" type="success" show-icon :closable="true" style="margin-bottom: 16px" title="端口检测正常，无冲突" />

    <el-row :gutter="16">
      <el-col :xs="24" :sm="12" :md="8" v-for="svc in services" :key="svc.id" style="margin-bottom: 16px">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span class="svc-name">{{ svc.name }}</span>
              <el-tag :type="svc.status === 'running' ? 'success' : 'danger'" size="small">
                {{ svc.status === 'running' ? '运行中' : '已停止' }}
              </el-tag>
            </div>
          </template>
          <div class="svc-info">
            <div v-if="svc.description" class="svc-desc">{{ svc.description }}</div>
            <div><strong>模块:</strong> {{ svc.id }}</div>
            <div v-if="svc.version"><strong>版本:</strong> {{ svc.version }}</div>
            <div v-if="svc.port" class="port-row">
              <strong>端口:</strong>
              <el-tag v-if="!svc.editingPort" size="small" class="port-tag" @click="startEditPort(svc)">
                {{ svc.port }}
                <el-icon style="margin-left: 4px; vertical-align: middle"><Edit /></el-icon>
              </el-tag>
              <span v-else class="port-edit">
                <el-input-number v-model="svc.newPort" :min="1" :max="65535" size="small" style="width: 110px" />
                <el-button size="small" type="primary" @click="savePort(svc)" style="margin-left: 4px">保存</el-button>
                <el-button size="small" @click="svc.editingPort = false">取消</el-button>
              </span>
            </div>
          </div>
          <div class="svc-actions">
            <el-button v-if="svc.accessUrl" size="small" type="primary" plain @click="openUrl(svc.accessUrl)">访问</el-button>
            <el-button size="small" type="success" @click="doAction(svc.id, 'start')" :disabled="svc.status === 'running'">启动</el-button>
            <el-button size="small" type="danger" @click="doAction(svc.id, 'stop')" :disabled="svc.status !== 'running'">停止</el-button>
            <el-button size="small" type="warning" @click="doAction(svc.id, 'restart')">重启</el-button>
            <el-button size="small" type="primary" @click="doAction(svc.id, 'update')">更新</el-button>
            <el-button size="small" @click="showLogs(svc)">
              <el-icon><Document /></el-icon> 日志
            </el-button>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 日志查看器 -->
    <LogViewer
      :module-id="logModuleId"
      :module-name="logTitle"
      v-model:visible="logVisible"
    />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Edit, Refresh, Document } from '@element-plus/icons-vue'
import LogViewer from '@/components/LogViewer.vue'
import api from '../api'

const services = ref([])
const loading = ref(false)
const logVisible = ref(false)
const logTitle = ref('')
const logModuleId = ref('')
const portConflicts = ref([])
const portCheckDone = ref(false)
const domain = ref('')
const httpsPort = ref('8443')

const loadDomain = async () => {
  try {
    const { data } = await api.get('/config')
    domain.value = data.env_summary?.DOMAIN || ''
    httpsPort.value = data.env_summary?.HTTPS_PORT || '8443'
  } catch (e) { /* ignore */ }
}

const buildAccessUrl = (svc) => {
  if (!svc.subdomain && !svc.port) return ''
  if (svc.subdomain && domain.value) {
    const portSuffix = httpsPort.value && httpsPort.value !== '443' ? `:${httpsPort.value}` : ''
    return `https://${svc.subdomain}.${domain.value}${portSuffix}`
  }
  if (svc.port) {
    return `http://${window.location.hostname}:${svc.port}`
  }
  return ''
}

const loadServices = async () => {
  loading.value = true
  try {
    await loadDomain()
    const { data } = await api.get('/services')
    services.value = (data.services || []).map(s => ({
      id: s.module,
      name: s.name || s.module,
      description: s.description || '',
      version: s.version || '',
      port: s.port || null,
      subdomain: s.subdomain || '',
      protocol: s.protocol || 'http',
      accessUrl: '',
      status: s.running ? 'running' : (s.error ? 'error' : 'stopped'),
      editingPort: false,
      newPort: s.port || 0,
      ...s
    }))
    // 生成访问链接
    services.value.forEach(svc => {
      svc.accessUrl = buildAccessUrl(svc)
    })
  } catch (e) { ElMessage.error('服务状态获取失败，请稍后重试') }
  finally { loading.value = false }
}

const checkPorts = async () => {
  try {
    const { data } = await api.get('/services/port-check')
    portConflicts.value = data.conflicts || []
    portCheckDone.value = true
  } catch (e) { ElMessage.error('端口检测失败') }
}

const startEditPort = (svc) => {
  svc.newPort = svc.port
  svc.editingPort = true
}

const savePort = async (svc) => {
  if (!svc.newPort || svc.newPort < 1 || svc.newPort > 65535) {
    ElMessage.warning('端口号无效')
    return
  }
  try {
    const { data } = await api.put(`/services/${svc.id}/port`, null, { params: { port: svc.newPort } })
    ElMessage.success(data.message || '端口已更新，请重启服务生效')
    svc.port = svc.newPort
    svc.editingPort = false
    // 重新检测端口冲突
    await checkPorts()
  } catch (e) {
    ElMessage.error(`端口修改失败: ${e.response?.data?.detail || e.message}`)
  }
}

const openUrl = (url) => {
  window.open(url, '_blank')
}

const doAction = async (id, action) => {
  // 危险操作二次确认
  if (action === 'stop') {
    try {
      await ElMessageBox.confirm(
        `确定停止 ${id}？${id === 'nginx' ? '\n停止 Nginx 将导致所有域名反代服务无法访问！' : ''}`,
        '确认停止',
        { type: 'warning' }
      )
    } catch { return }
  }
  if (action === 'restart') {
    try {
      await ElMessageBox.confirm(`确定重启 ${id}？`, '确认重启')
    } catch { return }
  }
  if (action === 'update') {
    try {
      await ElMessageBox.confirm(`确定更新 ${id}？更新过程中服务可能短暂不可用。`, '确认更新')
    } catch { return }
  }
  try {
    const { data } = await api.post(`/services/${id}/${action}`)
    const actionLabel = { start: '启动', stop: '停止', restart: '重启', update: '更新' }
    if (data.success === false) {
      ElMessage.error(`${id} ${actionLabel[action] || action} 失败: ${data.error || '未知错误'}`)
    } else {
      ElMessage.success(`${id} ${actionLabel[action] || action} 成功`)
    }
    loadServices()
  } catch (e) { ElMessage.error(`操作失败: ${e.response?.data?.detail || e.message}`) }
}

const showLogs = (svc) => {
  logModuleId.value = svc.id
  logTitle.value = svc.name
  logVisible.value = true
}

onMounted(async () => {
  await loadServices()
  await checkPorts()
})
</script>

<style scoped>
.card-header { display: flex; justify-content: space-between; align-items: center; }
.svc-name { font-weight: 600; font-size: 16px; }
.svc-info { margin-bottom: 12px; font-size: 13px; line-height: 1.8; }
.svc-desc { color: #666; margin-bottom: 4px; font-size: 12px; }
.svc-actions { display: flex; flex-wrap: wrap; gap: 6px; }
.port-row { display: flex; align-items: center; gap: 4px; }
.port-tag { cursor: pointer; }
.port-tag:hover { color: var(--el-color-primary); }
.port-edit { display: inline-flex; align-items: center; }
</style>
