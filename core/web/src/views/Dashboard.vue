<template>
  <div class="dashboard">
    <h2>仪表盘</h2>

    <!-- 系统资源 -->
    <el-row :gutter="20" class="system-info">
      <el-col :xs="24" :sm="12" :md="8" style="margin-bottom: 12px">
        <el-card shadow="hover">
          <template #header><span>CPU 使用率</span></template>
          <el-progress :percentage="system.cpu" :color="progressColor" />
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :md="8" style="margin-bottom: 12px">
        <el-card shadow="hover">
          <template #header><span>内存使用</span></template>
          <div class="mem-info">{{ system.memUsed }} / {{ system.memTotal }}</div>
          <el-progress :percentage="system.memPercent" :color="progressColor" />
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :md="8" style="margin-bottom: 12px">
        <el-card shadow="hover">
          <template #header><span>磁盘使用</span></template>
          <div class="mem-info">{{ system.diskUsed }} / {{ system.diskTotal }}</div>
          <el-progress :percentage="system.diskPercent" :color="progressColor" />
        </el-card>
      </el-col>
    </el-row>

    <!-- 快捷操作栏 -->
    <el-card style="margin-bottom: 20px">
      <template #header><span style="font-weight:600">快捷操作</span></template>
      <div style="display: flex; gap: 12px; flex-wrap: wrap">
        <el-button type="primary" @click="$router.push('/network-guide')" v-if="!networkConfigured">
          配置网络访问
        </el-button>
        <el-button @click="$router.push('/backup')">立即备份</el-button>
        <el-button @click="restartAll" :loading="restartingAll">全部重启</el-button>
        <el-button @click="loadServices">刷新服务状态</el-button>
      </div>
    </el-card>

    <!-- 服务状态 -->
    <h3 style="margin-top: 10px">服务状态</h3>
    <el-row :gutter="16">
      <el-col :xs="12" :sm="8" :md="6" v-for="svc in services" :key="svc.id" style="margin-bottom: 12px">
        <el-card shadow="hover" class="service-card" :class="{ 'is-stopped': svc.status !== 'running' }">
          <div class="svc-header">
            <span class="svc-name">{{ svc.name }}</span>
            <el-tag :type="svc.status === 'running' ? 'success' : 'danger'" size="small">
              {{ svc.status === 'running' ? '运行中' : '已停止' }}
            </el-tag>
          </div>
          <div class="svc-port" v-if="svc.port">端口: {{ svc.port }}</div>
          <div class="svc-actions">
            <el-button size="small" :type="svc.status === 'running' ? 'danger' : 'success'" @click="toggleService(svc)">
              {{ svc.status === 'running' ? '停止' : '启动' }}
            </el-button>
            <el-button size="small" @click="$router.push('/services')">管理</el-button>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 空状态 -->
    <el-empty v-if="services.length === 0" description="暂无已安装的服务，去模块市场看看？">
      <el-button type="primary" @click="$router.push('/market')">前往模块市场</el-button>
    </el-empty>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api'

const router = useRouter()
const services = ref([])
const system = ref({ cpu: 0, memUsed: '-', memTotal: '-', memPercent: 0, diskUsed: '-', diskTotal: '-', diskPercent: 0 })
const progressColor = '#409EFF'
const networkConfigured = ref(true)
const restartingAll = ref(false)

const loadServices = async () => {
  try {
    const { data } = await api.get('/services')
    services.value = (data.services || []).map(s => ({
      id: s.module,
      name: s.name || s.module,
      status: s.running ? 'running' : (s.error ? 'error' : 'stopped'),
      port: s.port || null,
      ...s
    }))
  } catch (e) { console.error(e) }
}

const formatMem = (mb) => mb >= 1024 ? (mb / 1024).toFixed(1) + ' GB' : mb + ' MB'

const loadSystemInfo = async () => {
  try {
    const { data } = await api.get('/info')
    system.value = {
      cpu: typeof data.cpu === 'number' ? data.cpu : 0,
      memUsed: data.memTotal ? formatMem(data.memUsed) : '-',
      memTotal: data.memTotal ? formatMem(data.memTotal) : '-',
      memPercent: typeof data.memPercent === 'number' ? data.memPercent : 0,
      diskUsed: data.diskTotal ? data.diskUsed + ' GB' : '-',
      diskTotal: data.diskTotal ? data.diskTotal + ' GB' : '-',
      diskPercent: typeof data.diskPercent === 'number' ? data.diskPercent : 0,
    }
  } catch (e) { /* 保持默认值 */ }
}

const checkNetworkStatus = async () => {
  try {
    const { data } = await api.get('/config/setup/status')
    networkConfigured.value = !!data.network_configured
    if (!data.network_configured) {
      // 不自动跳转，显示引导按钮
    }
  } catch (e) { /* ignore */ }
}

const toggleService = async (svc) => {
  const action = svc.status === 'running' ? 'stop' : 'start'
  if (action === 'stop') {
    try {
      await ElMessageBox.confirm(
        `确定停止 ${svc.name}？${svc.id === 'nginx' ? '停止 Nginx 将导致所有服务无法访问！' : ''}`,
        '确认停止',
        { type: 'warning' }
      )
    } catch { return }
  }
  try {
    const { data } = await api.post(`/services/${svc.id}/${action}`)
    if (data.success === false) {
      ElMessage.error(`${svc.name} ${action === 'start' ? '启动' : '停止'}失败: ${data.error || '未知错误'}`)
    } else {
      ElMessage.success(`${svc.name} 已${action === 'start' ? '启动' : '停止'}`)
    }
    loadServices()
  } catch (e) {
    ElMessage.error(`操作失败: ${e.response?.data?.detail || e.message}`)
  }
}

const restartAll = async () => {
  try {
    await ElMessageBox.confirm('确定重启所有运行中的服务？', '确认全部重启', { type: 'warning' })
  } catch { return }
  restartingAll.value = true
  try {
    const runningSvcs = services.value.filter(s => s.status === 'running')
    let failed = []
    for (const svc of runningSvcs) {
      const { data } = await api.post(`/services/${svc.id}/restart`)
      if (data.success === false) failed.push(svc.name)
    }
    if (failed.length) {
      ElMessage.warning(`大部分服务已重启，但以下失败: ${failed.join(', ')}`)
    } else {
      ElMessage.success('所有服务已重启')
    }
    loadServices()
  } catch (e) {
    ElMessage.error(`重启失败: ${e.response?.data?.detail || e.message}`)
  }
  restartingAll.value = false
}

onMounted(() => {
  loadServices()
  loadSystemInfo()
  checkNetworkStatus()
})
</script>

<style scoped>
.system-info { margin-bottom: 20px; }
.mem-info { font-size: 14px; color: #666; margin-bottom: 8px; }
.service-card.is-stopped { opacity: 0.7; }
.svc-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.svc-name { font-weight: 600; font-size: 15px; }
.svc-port { font-size: 12px; color: #999; margin-bottom: 8px; }
.svc-actions { display: flex; gap: 8px; }
</style>
