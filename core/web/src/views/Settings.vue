<template>
  <div class="settings-page">
    <h2>全局设置</h2>

    <!-- 区段1: 服务器配置 -->
    <el-card style="max-width: 700px; width: 100%">
      <template #header><span style="font-weight:600">服务器配置</span></template>
      <el-form :model="form" label-width="120px">
        <el-form-item label="域名">
          <el-input v-model="form.domain" placeholder="example.com" />
        </el-form-item>
        <el-form-item label="访问模式">
          <el-radio-group v-model="form.access_mode" @change="onAccessModeChange">
            <el-radio label="domain">域名反代 (SSL)</el-radio>
            <el-radio label="cloudflare_tunnel">Cloudflare Tunnel</el-radio>
            <el-radio label="ipv6_direct">IPv6 直连</el-radio>
            <el-radio label="hybrid">混合模式</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="HTTPS 端口">
          <el-input-number v-model="form.https_port" :min="1" :max="65535" />
        </el-form-item>

        <!-- 域名反代模式：显示 SSL 和 DNS 配置 -->
        <template v-if="form.access_mode === 'domain' || form.access_mode === 'hybrid'">
          <el-form-item label="SSL 邮箱">
            <el-input v-model="form.ssl_email" placeholder="admin@example.com" />
          </el-form-item>
          <el-form-item label="DNS 提供商">
            <el-radio-group v-model="form.dns_provider" @change="onDnsProviderChange">
              <el-radio label="aliyun">阿里云</el-radio>
              <el-radio label="cloudflare">Cloudflare</el-radio>
            </el-radio-group>
          </el-form-item>
          <!-- 阿里云凭证 -->
          <template v-if="form.dns_provider === 'aliyun'">
            <el-form-item label="AccessKey ID">
              <el-input v-model="dnsCredentials.aliyun.key" placeholder="LTAI5t..." type="password" show-password />
              <div class="form-help">
                <a href="https://ram.console.aliyun.com/manage/ak" target="_blank">前往创建</a>
                ，需授予 AliyunDNSFullAccess 权限
              </div>
            </el-form-item>
            <el-form-item label="AccessKey Secret">
              <el-input v-model="dnsCredentials.aliyun.secret" placeholder="AccessKey Secret" type="password" show-password />
            </el-form-item>
          </template>
          <!-- Cloudflare 凭证 -->
          <template v-if="form.dns_provider === 'cloudflare'">
            <el-form-item label="API Token">
              <el-input v-model="dnsCredentials.cloudflare.token" placeholder="Cloudflare API Token" type="password" show-password />
              <div class="form-help">
                <a href="https://dash.cloudflare.com/profile/api-tokens" target="_blank">前往创建</a>
                ，权限选择 Zone &gt; DNS &gt; Edit
              </div>
            </el-form-item>
          </template>
          <el-form-item label="管理面板子域名">
            <el-input v-model="form.panel_subdomain" placeholder="panel">
              <template #append>.{{ form.domain }}</template>
            </el-input>
          </el-form-item>
        </template>

        <!-- Cloudflare Tunnel 模式：显示 Tunnel Token -->
        <template v-if="form.access_mode === 'cloudflare_tunnel'">
          <el-form-item label="Tunnel Token">
            <el-input v-model="form.cf_tunnel_token" placeholder="Cloudflare Tunnel Token" type="password" show-password />
            <div class="form-help">
              在 Cloudflare Zero Trust 面板创建 Tunnel 后获取 Token
            </div>
          </el-form-item>
          <el-alert type="info" :closable="false">
            Cloudflare Tunnel 自带 SSL、反向代理和 DNS，无需配置 Nginx 和 ACME。
          </el-alert>
        </template>

        <el-form-item>
          <el-button type="primary" @click="saveConfig" :loading="saving">保存并应用</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 区段2: SSL 证书状态 -->
    <el-card v-if="form.access_mode === 'domain' || form.access_mode === 'hybrid'" style="max-width: 700px; width: 100%; margin-top: 20px">
      <template #header><span style="font-weight:600">SSL 证书状态</span></template>
      <div class="ssl-status">
        <el-tag :type="sslValid ? 'success' : 'warning'" size="large">{{ sslValid ? '有效' : '未配置' }}</el-tag>
        <span v-if="sslExpiry" style="margin-left: 12px; color: #666">到期: {{ sslExpiry }}</span>
        <el-button style="margin-left: auto" size="small" @click="checkSSL" :loading="sslChecking">刷新状态</el-button>
      </div>
    </el-card>

    <!-- 区段3: 容器资源管理 -->
    <el-card style="max-width: 700px; width: 100%; margin-top: 20px">
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
import { ref, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api'

const isMobile = ref(false)
const checkMobile = () => { isMobile.value = window.innerWidth < 768 }
onMounted(() => { checkMobile(); window.addEventListener('resize', checkMobile) })
onUnmounted(() => { window.removeEventListener('resize', checkMobile) })

// ===== 区段1: 服务器配置 =====
const form = ref({
  domain: '', access_mode: 'domain', https_port: 8443, ssl_email: '',
  dns_provider: 'aliyun', panel_subdomain: 'panel', cf_tunnel_token: ''
})
const dnsCredentials = ref({
  aliyun: { key: '', secret: '' },
  cloudflare: { token: '' }
})
const saving = ref(false)

const loadConfig = async () => {
  try {
    const { data } = await api.get('/config')
    const cfg = data.config || {}
    const env = data.env_summary || {}
    form.value.domain = env.DOMAIN || cfg.domain || ''
    form.value.access_mode = env.ACCESS_MODE || cfg.access_mode || 'domain'
    form.value.https_port = parseInt(env.HTTPS_PORT) || cfg.https_port || 8443
    form.value.ssl_email = cfg.ssl_email || ''
    form.value.dns_provider = cfg.dns_provider || 'aliyun'
    form.value.panel_subdomain = cfg.panel_subdomain || 'panel'
    form.value.cf_tunnel_token = cfg.cf_tunnel_token || ''
    // 加载 DNS 凭证（脱敏后的值）
    if (data.dns_credentials) {
      if (data.dns_credentials.aliyun) {
        dnsCredentials.value.aliyun = data.dns_credentials.aliyun
      }
      if (data.dns_credentials.cloudflare) {
        dnsCredentials.value.cloudflare = data.dns_credentials.cloudflare
      }
    }
    // 加载资源配置
    resourceForm.value.cpu_limit = cfg.cpu_limit || 2.0
    resourceForm.value.memory_limit = cfg.memory_limit || 2048
    resourceForm.value.auto_restart = cfg.auto_restart !== false
    resourceForm.value.log_retention_days = cfg.log_retention_days || 7
    resourceForm.value.auto_cleanup = cfg.auto_cleanup !== false
  } catch (e) { ElMessage.error('加载配置失败') }
}

const onAccessModeChange = () => {
  // 切换访问模式时提示
}

const onDnsProviderChange = () => {
  if (form.value.dns_provider === 'aliyun') {
    dnsCredentials.value.cloudflare.token = ''
  } else if (form.value.dns_provider === 'cloudflare') {
    dnsCredentials.value.aliyun.key = ''
    dnsCredentials.value.aliyun.secret = ''
  }
}

const saveConfig = async () => {
  saving.value = true
  try {
    const saveData = { ...form.value }
    // 域名反代模式附带 DNS 凭证
    if (form.value.access_mode === 'domain' || form.value.access_mode === 'hybrid') {
      saveData.dns_credentials = {
        [form.value.dns_provider]: dnsCredentials.value[form.value.dns_provider]
      }
    }
    await api.put('/config', saveData)
    // 域名模式自动重新生成 Nginx 配置
    if (form.value.access_mode === 'domain' || form.value.access_mode === 'hybrid') {
      try { await api.post('/nginx/generate') } catch {}
    }
    ElMessage.success('配置已保存并应用')
  } catch (e) { ElMessage.error('保存失败') }
  saving.value = false
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

// ===== 区段4: 日志查看 =====
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
  checkSSL()
})
</script>

<style scoped>
.settings-page { max-width: 800px; }
.ssl-status { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
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

@media (max-width: 768px) {
  .ssl-status { flex-direction: column; align-items: flex-start; }
  .ssl-status > .el-button { margin-left: 0 !important; }
}

.form-help {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
  line-height: 1.5;
}

.form-help a {
  color: #409eff;
  text-decoration: none;
}

.form-help a:hover {
  text-decoration: underline;
}
</style>
