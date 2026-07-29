<template>
  <div class="settings-page">
    <h2>全局设置</h2>

    <!-- 区段1: 服务器配置 -->
    <el-card style="max-width: 700px">
      <template #header><span style="font-weight:600">服务器配置</span></template>
      <el-form :model="form" label-width="120px">
        <el-form-item label="域名">
          <el-input v-model="form.domain" placeholder="example.com" />
        </el-form-item>
        <el-form-item label="访问模式">
          <el-radio-group v-model="form.access_mode">
            <el-radio label="domain">域名反代 (SSL)</el-radio>
            <el-radio label="ipv6_direct">IPv6 直连</el-radio>
            <el-radio label="hybrid">混合模式</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="HTTPS 端口">
          <el-input-number v-model="form.https_port" :min="1" :max="65535" />
        </el-form-item>
        <el-form-item label="SSL 邮箱">
          <el-input v-model="form.ssl_email" placeholder="admin@example.com" />
        </el-form-item>
        <el-form-item label="DNS 提供商">
          <el-input v-model="form.dns_provider" placeholder="cloudflare / aliyun / ..." />
        </el-form-item>
        <el-form-item label="管理面板子域名">
          <el-input v-model="form.panel_subdomain" placeholder="panel">
            <template #append>.{{ form.domain }}</template>
          </el-input>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="saveConfig" :loading="saving">保存配置</el-button>
          <el-button @click="generateNginx" :loading="generating">重新生成 Nginx 配置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 区段2: SSL 证书状态 -->
    <el-card style="max-width: 700px; margin-top: 20px">
      <template #header><span style="font-weight:600">SSL 证书状态</span></template>
      <div class="ssl-status">
        <el-tag :type="sslValid ? 'success' : 'warning'" size="large">{{ sslValid ? '有效' : '未配置' }}</el-tag>
        <span v-if="sslExpiry" style="margin-left: 12px; color: #666">到期: {{ sslExpiry }}</span>
        <el-button style="margin-left: auto" size="small" @click="checkSSL" :loading="sslChecking">刷新状态</el-button>
      </div>
    </el-card>

    <!-- 区段3: 容器资源管理 -->
    <el-card style="max-width: 700px; margin-top: 20px">
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

    <!-- 区段4: 系统服务状态 -->
    <el-card style="max-width: 700px; margin-top: 20px">
      <template #header>
        <div style="display:flex;align-items:center;justify-content:space-between">
          <span style="font-weight:600">系统服务状态</span>
          <el-button size="small" @click="loadServices" :loading="loadingServices">刷新</el-button>
        </div>
      </template>
      <div v-if="services.length === 0" style="color:#999;text-align:center;padding:20px">暂无已安装的服务</div>
      <el-table v-else :data="services" stripe size="small" style="width:100%">
        <el-table-column prop="module" label="服务" width="150" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.running ? 'success' : 'danger'" size="small">
              {{ row.running ? '运行中' : '已停止' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="280">
          <template #default="{ row }">
            <el-button-group>
              <el-button size="small" type="success" @click="doServiceAction(row.module, 'start')" :disabled="row.running">启动</el-button>
              <el-button size="small" type="warning" @click="doServiceAction(row.module, 'stop')" :disabled="!row.running">停止</el-button>
              <el-button size="small" type="primary" @click="doServiceAction(row.module, 'restart')" :disabled="!row.running">重启</el-button>
              <el-button size="small" @click="viewLogs(row.module)">日志</el-button>
            </el-button-group>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 区段5: 备份管理 -->
    <el-card style="max-width: 700px; margin-top: 20px">
      <template #header>
        <div style="display:flex;align-items:center;justify-content:space-between">
          <span style="font-weight:600">备份管理</span>
          <el-button size="small" @click="loadBackupStatus" :loading="backupLoading">刷新状态</el-button>
        </div>
      </template>
      <div v-if="!backupStatus.initialized" style="color:#999;text-align:center;padding:20px">
        备份模块未安装或未初始化，请先在模块市场安装「数据备份」模块。
      </div>
      <template v-else>
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="上次备份">{{ backupStatus.last_backup ? new Date(backupStatus.last_backup).toLocaleString() : '无' }}</el-descriptions-item>
          <el-descriptions-item label="仓库大小">{{ backupStatus.total_size_mb }} MB</el-descriptions-item>
          <el-descriptions-item label="快照数量">{{ backupStatus.snapshots ? backupStatus.snapshots.length : 0 }} 个（显示最近10个）</el-descriptions-item>
          <el-descriptions-item label="备份周期">{{ backupScheduleLabel }}</el-descriptions-item>
        </el-descriptions>
        <div style="margin-top: 16px; display: flex; gap: 12px; flex-wrap: wrap; align-items: center">
          <el-button type="primary" @click="doBackup" :loading="backupTriggering">立即备份</el-button>
          <el-select v-model="backupForm.schedule" style="width: 180px" placeholder="备份周期">
            <el-option value="0 2 * * *" label="每天凌晨2点" />
            <el-option value="0 2 * * 0" label="每周日凌晨2点" />
            <el-option value="0 2 1 * *" label="每月1日凌晨2点" />
            <el-option value="0 */6 * * *" label="每6小时" />
          </el-select>
          <el-input-number v-model="backupForm.retain_days" :min="1" :max="90" style="width: 120px" placeholder="保留天数" />
          <el-button @click="saveBackupSchedule" :loading="backupSaving">保存计划</el-button>
        </div>
        <el-table v-if="backupStatus.snapshots && backupStatus.snapshots.length > 0" :data="backupStatus.snapshots" stripe size="small" style="width:100%; margin-top: 16px">
          <el-table-column label="时间" width="180">
            <template #default="{ row }">{{ new Date(row.time).toLocaleString() }}</template>
          </el-table-column>
          <el-table-column prop="hostname" label="主机" width="120" />
          <el-table-column label="标签" min-width="150">
            <template #default="{ row }">{{ (row.tags || []).join(', ') }}</template>
          </el-table-column>
        </el-table>
      </template>
    </el-card>

    <!-- 日志弹窗 -->
    <el-dialog v-model="logVisible" :title="'日志 - ' + logModule" width="700px" top="5vh">
      <pre class="log-content">{{ logContent }}</pre>
      <template #footer>
        <el-button @click="logVisible = false">关闭</el-button>
        <el-button type="primary" @click="viewLogs(logModule)">刷新</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api'

// ===== 区段1: 服务器配置 =====
const form = ref({ domain: '', access_mode: 'domain', https_port: 8443, ssl_email: '', dns_provider: '', panel_subdomain: 'panel' })
const saving = ref(false)
const generating = ref(false)

const loadConfig = async () => {
  try {
    const { data } = await api.get('/config')
    const cfg = data.config || {}
    const env = data.env_summary || {}
    form.value.domain = env.DOMAIN || cfg.domain || ''
    form.value.access_mode = env.ACCESS_MODE || cfg.access_mode || 'domain'
    form.value.https_port = parseInt(env.HTTPS_PORT) || cfg.https_port || 8443
    form.value.ssl_email = cfg.ssl_email || ''
    form.value.dns_provider = cfg.dns_provider || ''
    form.value.panel_subdomain = cfg.panel_subdomain || 'panel'
    // 加载资源配置
    resourceForm.value.cpu_limit = cfg.cpu_limit || 2.0
    resourceForm.value.memory_limit = cfg.memory_limit || 2048
    resourceForm.value.auto_restart = cfg.auto_restart !== false
    resourceForm.value.log_retention_days = cfg.log_retention_days || 7
    resourceForm.value.auto_cleanup = cfg.auto_cleanup !== false
  } catch (e) { ElMessage.error('加载配置失败') }
}

const saveConfig = async () => {
  saving.value = true
  try {
    await api.put('/config', form.value)
    ElMessage.success('配置已保存')
  } catch (e) { ElMessage.error('保存失败') }
  saving.value = false
}

const generateNginx = async () => {
  generating.value = true
  try {
    await api.post('/nginx/generate')
    ElMessage.success('Nginx 配置已重新生成')
  } catch (e) { ElMessage.error('生成失败') }
  generating.value = false
}

// ===== 区段2: SSL 证书状态 =====
const sslValid = ref(false)
const sslExpiry = ref('')
const sslChecking = ref(false)

const checkSSL = async () => {
  sslChecking.value = true
  try {
    const { data } = await api.get('/config')
    const ssl = data.ssl_status || {}
    sslValid.value = !!ssl.ssl_valid
    sslExpiry.value = ssl.ssl_expiry || ''
  } catch (e) {
    sslValid.value = false
    sslExpiry.value = ''
  }
  sslChecking.value = false
}

// ===== 区段3: 容器资源管理 =====
const resourceForm = ref({
  cpu_limit: 2.0,
  memory_limit: 2048,
  auto_restart: true,
  log_retention_days: 7,
  auto_cleanup: false
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

// ===== 区段4: 系统服务状态 =====
const services = ref([])
const loadingServices = ref(false)
const logVisible = ref(false)
const logModule = ref('')
const logContent = ref('')

const loadServices = async () => {
  loadingServices.value = true
  try {
    const { data } = await api.get('/services')
    services.value = data.services || []
  } catch (e) { ElMessage.error('加载服务列表失败') }
  loadingServices.value = false
}

const doServiceAction = async (moduleId, action) => {
  try {
    const { data } = await api.post(`/services/${moduleId}/${action}`)
    if (data.success !== false) {
      ElMessage.success(`${moduleId} ${action === 'start' ? '启动' : action === 'stop' ? '停止' : '重启'}成功`)
    } else {
      ElMessage.error(data.error || '操作失败')
    }
    loadServices()
  } catch (e) {
    ElMessage.error(`操作失败: ${e.response?.data?.detail || e.message}`)
  }
}

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
  checkSSL()
  loadServices()
  loadBackupStatus()
})

// ===== 区段5: 备份管理 =====
const backupStatus = ref({ initialized: false, snapshots: [], last_backup: '', total_size_mb: 0 })
const backupLoading = ref(false)
const backupTriggering = ref(false)
const backupSaving = ref(false)
const backupForm = ref({ schedule: '0 2 * * *', retain_days: 7 })

const backupScheduleMap = {
  '0 2 * * *': '每天凌晨2点',
  '0 2 * * 0': '每周日凌晨2点',
  '0 2 1 * *': '每月1日凌晨2点',
  '0 */6 * * *': '每6小时'
}
const backupScheduleLabel = computed(() => backupScheduleMap[backupForm.value.schedule] || backupForm.value.schedule)

const loadBackupStatus = async () => {
  backupLoading.value = true
  try {
    const { data } = await api.get('/backup/status')
    backupStatus.value = data
  } catch (e) {
    // 接口不存在或模块未安装，保持默认值
  }
  backupLoading.value = false
}

const doBackup = async () => {
  try {
    await ElMessageBox.confirm('确定立即执行一次全量备份？', '确认备份')
  } catch { return }
  backupTriggering.value = true
  try {
    const { data } = await api.post('/backup/trigger')
    if (data.success) {
      ElMessage.success('备份完成')
      loadBackupStatus()
    } else {
      ElMessage.error('备份失败: ' + (data.error || '未知错误'))
    }
  } catch (e) {
    ElMessage.error('备份失败: ' + (e.response?.data?.detail || e.message))
  }
  backupTriggering.value = false
}

const saveBackupSchedule = async () => {
  backupSaving.value = true
  try {
    await api.put('/backup/schedule', { schedule: backupForm.value.schedule, retain_days: backupForm.value.retain_days })
    ElMessage.success('备份计划已更新')
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
  }
  backupSaving.value = false
}
</script>

<style scoped>
.settings-page { max-width: 800px; }
.ssl-status { display: flex; align-items: center; }
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
</style>
