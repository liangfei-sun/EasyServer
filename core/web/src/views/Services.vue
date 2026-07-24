<template>
  <div class="services-page">
    <h2>服务管理</h2>
    <el-row :gutter="16">
      <el-col :span="8" v-for="svc in services" :key="svc.id" style="margin-bottom: 16px">
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
            <div v-if="svc.port"><strong>端口:</strong> {{ svc.port }}</div>
            <div v-if="svc.version"><strong>版本:</strong> {{ svc.version }}</div>
            <div><strong>模块:</strong> {{ svc.id }}</div>
          </div>
          <div class="svc-actions">
            <el-button size="small" type="success" @click="doAction(svc.id, 'start')" :disabled="svc.status === 'running'">启动</el-button>
            <el-button size="small" type="danger" @click="doAction(svc.id, 'stop')" :disabled="svc.status !== 'running'">停止</el-button>
            <el-button size="small" type="warning" @click="doAction(svc.id, 'restart')">重启</el-button>
            <el-button size="small" type="primary" @click="doAction(svc.id, 'update')">更新</el-button>
            <el-button size="small" @click="showLogs(svc)">日志</el-button>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 日志弹窗 -->
    <el-dialog v-model="logVisible" :title="logTitle + ' - 日志'" width="700px" top="5vh">
      <pre class="log-content">{{ logContent }}</pre>
      <template #footer>
        <el-button @click="logVisible = false">关闭</el-button>
        <el-button type="primary" @click="refreshLogs">刷新</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api'

const services = ref([])
const logVisible = ref(false)
const logTitle = ref('')
const logContent = ref('')
const currentLogSvc = ref('')

const loadServices = async () => {
  try {
    const { data } = await api.get('/api/services')
    services.value = data.services || []
  } catch (e) { ElMessage.error('加载服务列表失败') }
}

const doAction = async (id, action) => {
  try {
    const { data } = await api.post(`/api/services/${id}/${action}`)
    ElMessage.success(`${id} ${action} 成功`)
    loadServices()
  } catch (e) { ElMessage.error(`操作失败: ${e.response?.data?.detail || e.message}`) }
}

const showLogs = async (svc) => {
  currentLogSvc.value = svc.id
  logTitle.value = svc.name
  logVisible.value = true
  await refreshLogs()
}

const refreshLogs = async () => {
  try {
    const { data } = await api.get(`/api/services/${currentLogSvc.value}/logs?lines=100`)
    logContent.value = data.logs || '暂无日志'
  } catch (e) { logContent.value = '获取日志失败' }
}

onMounted(loadServices)
</script>

<style scoped>
.card-header { display: flex; justify-content: space-between; align-items: center; }
.svc-name { font-weight: 600; font-size: 16px; }
.svc-info { margin-bottom: 12px; font-size: 13px; line-height: 1.8; }
.svc-actions { display: flex; flex-wrap: wrap; gap: 6px; }
.log-content { background: #1e1e1e; color: #d4d4d4; padding: 16px; border-radius: 6px; max-height: 400px; overflow: auto; font-size: 12px; line-height: 1.5; white-space: pre-wrap; }
</style>
