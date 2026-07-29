<template>
  <div class="dashboard">
    <h2>仪表盘</h2>
    <el-row :gutter="20" class="system-info">
      <el-col :span="8">
        <el-card shadow="hover">
          <template #header><span>CPU 使用率</span></template>
          <el-progress :percentage="system.cpu" :color="progressColor" />
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="hover">
          <template #header><span>内存使用</span></template>
          <div class="mem-info">{{ system.memUsed }} / {{ system.memTotal }}</div>
          <el-progress :percentage="system.memPercent" :color="progressColor" />
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="hover">
          <template #header><span>磁盘使用</span></template>
          <div class="mem-info">{{ system.diskUsed }} / {{ system.diskTotal }}</div>
          <el-progress :percentage="system.diskPercent" :color="progressColor" />
        </el-card>
      </el-col>
    </el-row>
    <h3 style="margin-top: 30px">服务状态</h3>
    <el-row :gutter="16">
      <el-col :span="6" v-for="svc in services" :key="svc.id" style="margin-bottom: 16px">
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
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '../api'

const services = ref([])
const system = ref({ cpu: 0, memUsed: '-', memTotal: '-', memPercent: 0, diskUsed: '-', diskTotal: '-', diskPercent: 0 })
const progressColor = '#409EFF'

const loadServices = async () => {
  try {
    const { data } = await api.get('/services')
    services.value = (data.services || []).map(s => ({
      id: s.module,
      name: s.module,
      status: s.running ? 'running' : (s.error ? 'error' : 'stopped'),
      ...s
    }))
  } catch (e) { console.error(e) }
}

const formatMem = (mb) => mb >= 1024 ? (mb / 1024).toFixed(1) + ' GB' : mb + ' MB'

const loadSystemInfo = async () => {
  try {
    const { data } = await api.get('/info')
    system.value = {
      appName: data.name || 'EasyServer',
      appVersion: data.version || '',
      appDescription: data.description || '',
      cpu: typeof data.cpu === 'number' ? data.cpu : 0,
      memUsed: data.memTotal ? formatMem(data.memUsed) : '-',
      memTotal: data.memTotal ? formatMem(data.memTotal) : '-',
      memPercent: typeof data.memPercent === 'number' ? data.memPercent : 0,
      diskUsed: data.diskTotal ? data.diskUsed + ' GB' : '-',
      diskTotal: data.diskTotal ? data.diskTotal + ' GB' : '-',
      diskPercent: typeof data.diskPercent === 'number' ? data.diskPercent : 0,
    }
  } catch (e) {
    // 保持默认值
  }
}

const toggleService = async (svc) => {
  const action = svc.status === 'running' ? 'stop' : 'start'
  try {
    await api.post(`/services/${svc.id}/${action}`)
    loadServices()
  } catch (e) { console.error(e) }
}

onMounted(() => { loadServices(); loadSystemInfo() })
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
