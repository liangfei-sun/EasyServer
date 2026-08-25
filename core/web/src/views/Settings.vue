<template>
  <div class="settings-page">
    <h2>全局设置</h2>

    <!-- 域名信息（只读展示） -->
    <el-card style="max-width: 700px; width: 100%; margin-bottom: 20px">
      <template #header><span style="font-weight:600">基础信息</span></template>
      <el-descriptions :column="isMobile ? 1 : 2" border>
        <el-descriptions-item label="域名">{{ domain }}</el-descriptions-item>
        <el-descriptions-item label="SSL 邮箱">{{ sslEmail }}</el-descriptions-item>
      </el-descriptions>
      <div class="form-help" style="margin-top: 12px">
        如需修改域名或网络访问方式，请前往 <el-button type="primary" link @click="$router.push('/network')">网络配置</el-button>
      </div>
    </el-card>

    <!-- 容器资源管理 -->
    <el-card style="max-width: 700px; width: 100%; margin-bottom: 20px">
      <template #header><span style="font-weight:600">容器资源管理</span></template>
      <el-form :model="resourceForm" label-width="140px">
        <el-form-item label="CPU 限制 (核)">
          <el-input-number v-model="resourceForm.cpu_limit" :min="0.5" :max="16" :step="0.5" :precision="1" />
        </el-form-item>
        <el-form-item label="内存限制 (MB)">
          <el-input-number v-model="resourceForm.memory_limit" :min="256" :max="32768" :step="256" />
        </el-form-item>
        <el-form-item label="自动重启">
          <el-switch v-model="resourceForm.auto_restart" active-text="开启" inactive-text="关闭" />
        </el-form-item>
        <el-form-item label="日志保留天数">
          <el-input-number v-model="resourceForm.log_retention_days" :min="1" :max="90" />
        </el-form-item>
        <el-form-item label="自动清理">
          <el-switch v-model="resourceForm.auto_cleanup" active-text="开启" inactive-text="关闭" />
          <span style="margin-left: 8px; color: #999; font-size: 12px">自动清理未使用的镜像和悬空容器</span>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="saveResources" :loading="savingResources">保存资源设置</el-button>
          <el-button type="warning" @click="cleanupDocker" :loading="cleaning">立即清理</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 日志弹窗 -->
    <el-dialog v-model="logVisible" :title="'日志 - ' + logModule" :width="isMobile ? '95%' : '700px'" top="5vh">
      <pre class="log-content">{{ logContent }}</pre>
      <template #footer>
        <el-button @click="logVisible = false">关闭</el-button>
        <el-button type="primary" @click="viewLogs(logModule)">刷新</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useMobile } from '@/composables/useMobile'
import api from '../api'

const { isMobile } = useMobile()

// ===== 基础信息 =====
const domain = ref('')
const sslEmail = ref('')

const loadConfig = async () => {
  try {
    const { data } = await api.get('/config')
    const cfg = data.config || {}
    const env = data.env_summary || {}
    domain.value = env.DOMAIN || cfg.domain || ''
    sslEmail.value = cfg.ssl_email || ''
    resourceForm.value.cpu_limit = cfg.cpu_limit || 2.0
    resourceForm.value.memory_limit = cfg.memory_limit || 2048
    resourceForm.value.auto_restart = cfg.auto_restart !== false
    resourceForm.value.log_retention_days = cfg.log_retention_days || 7
    resourceForm.value.auto_cleanup = cfg.auto_cleanup !== false
  } catch (e) { ElMessage.error('加载配置失败') }
}

// ===== 容器资源管理 =====
const resourceForm = ref({
  cpu_limit: 2.0, memory_limit: 2048, auto_restart: true,
  log_retention_days: 7, auto_cleanup: false
})
const savingResources = ref(false)
const cleaning = ref(false)

const saveResources = async () => {
  savingResources.value = true
  try {
    await api.put('/config', resourceForm.value)
    ElMessage.success('资源设置已保存')
  } catch (e) { ElMessage.error('保存失败') }
  savingResources.value = false
}

const cleanupDocker = async () => {
  try {
    await ElMessageBox.confirm('确定清理未使用的 Docker 镜像和悬停容器？', '确认清理')
  } catch { return }
  cleaning.value = true
  try {
    await api.post('/services/cleanup')
    ElMessage.success('清理完成')
  } catch (e) {
    ElMessage.warning('清理接口暂未实现，请手动执行 docker system prune')
  }
  cleaning.value = false
}

// ===== 日志查看 =====
const logVisible = ref(false)
const logModule = ref('')
const logContent = ref('')

const viewLogs = async (moduleId) => {
  logModule.value = moduleId
  try {
    const { data } = await api.get(`/services/${moduleId}/logs`, { params: { lines: 200 } })
    logContent.value = data.logs || '无日志'
  } catch (e) {
    logContent.value = '加载日志失败'
  }
  logVisible.value = true
}

onMounted(() => {
  loadConfig()
})
</script>

<style scoped>
.settings-page { max-width: 800px; }
.log-content {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 16px;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.6;
  max-height: 500px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
}
.form-help {
  font-size: 12px;
  color: #909399;
  line-height: 1.5;
}
</style>
