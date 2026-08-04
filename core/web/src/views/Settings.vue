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
          <div class="form-help" style="width:100%">
            域名反代：通过 Nginx + SSL 证书访问（https://子域名.域名:端口）；Cloudflare Tunnel：免端口、免公网 IP；
            混合模式：两者同时启用，可按需选择每个服务的访问方式。
          </div>
        </el-form-item>
        <!-- 混合模式说明 -->
        <el-alert v-if="form.access_mode === 'hybrid'" type="info" :closable="false" style="margin-bottom: 16px">
          混合模式：同时启用 <b>Nginx 反向代理</b>（https://子域名.域名:8443）和 <b>Cloudflare Tunnel</b>（https://子域名.域名，免端口），两者可同时访问。
        </el-alert>
        <el-form-item label="HTTPS 端口">
          <el-input-number v-model="form.https_port" :min="1" :max="65535" />
        </el-form-item>

        <!-- 域名反代模式：显示 SSL 和 DNS 配置 -->
        <template v-if="form.access_mode === 'domain' || form.access_mode === 'hybrid'">
          <el-form-item label="SSL 邮箱">
            <el-input v-model="form.ssl_email" placeholder="admin@example.com" />
          </el-form-item>
          <el-form-item label="DNS 提供商">
            <el-select v-model="form.dns_provider" style="width: 100%" @change="onDnsProviderChange">
              <el-option v-for="p in dnsProviders" :key="p.id" :label="p.name" :value="p.id">
                <span>{{ p.name }}</span>
                <span style="color: #909399; font-size: 12px; margin-left: 8px">{{ p.acme_plugin || '自定义插件' }}</span>
              </el-option>
            </el-select>
            <div class="form-help">{{ currentProvider?.description }}</div>
          </el-form-item>
          <!-- 按提供商动态渲染凭证字段 -->
          <template v-if="currentProvider">
            <el-form-item v-for="f in currentProvider.fields" :key="f.key" :label="f.label">
              <el-input
                v-if="f.type !== 'textarea'"
                v-model="dnsCredentials[form.dns_provider][f.key]"
                type="password"
                show-password
                :placeholder="dnsConfigured[form.dns_provider]?.[f.key] ? '已配置，留空保持不变' : (f.placeholder || '请输入')"
              />
              <el-input
                v-else
                v-model="dnsCredentials[form.dns_provider][f.key]"
                type="textarea"
                :rows="4"
                :placeholder="f.placeholder"
              />
              <div class="form-help" v-if="f.help">
                {{ f.help }}
                <a v-if="currentProvider.help_url" :href="currentProvider.help_url" target="_blank" style="margin-left: 4px">前往创建</a>
              </div>
              <el-tag v-if="dnsConfigured[form.dns_provider]?.[f.key]" type="success" size="small" style="margin-top: 4px">
                已配置 {{ dnsCredentials[form.dns_provider][f.key] }}（留空则不修改）
              </el-tag>
            </el-form-item>
            <el-form-item v-if="form.dns_provider === 'custom'">
              <el-alert type="warning" :closable="false">
                自定义选项需要填写 acme.sh DNS 插件名和凭证变量，插件完整列表见
                <a href="https://github.com/acmesh-official/acme.sh/wiki/dnsapi" target="_blank" style="color:#409eff">acme.sh DNS API 文档</a>
              </el-alert>
            </el-form-item>
          </template>
          <el-form-item label="管理面板子域名">
            <el-input v-model="form.panel_subdomain" placeholder="panel">
              <template #append>.{{ form.domain }}</template>
            </el-input>
          </el-form-item>
        </template>

        <!-- Cloudflare Tunnel 模式：引导至内网穿透页面（单一接入入口） -->
        <template v-if="form.access_mode === 'cloudflare_tunnel'">
          <el-alert type="warning" :closable="false">
            <template #title>请通过「内网穿透」页面完成接入</template>
            Cloudflare Tunnel 的接入（创建隧道、启动容器、配置路由、DNS 记录）请统一在「内网穿透」页面操作，无需在此填写 Token。
            <div style="margin-top: 8px">
              <el-button type="primary" size="small" @click="$router.push('/tunnel')">前往内网穿透</el-button>
            </div>
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
import { ref, computed, onMounted, onUnmounted } from 'vue'
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
const dnsCredentials = ref({ aliyun: {}, cloudflare: {} })
const dnsProviders = ref([])
const dnsConfigured = ref({})
const saving = ref(false)

// 当前选中的 DNS 提供商定义
const currentProvider = computed(() =>
  dnsProviders.value.find(p => p.id === form.value.dns_provider) || null
)

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
    // 加载 DNS 提供商列表与凭证状态
    dnsProviders.value = data.dns_providers || []
    const masked = data.dns_credentials || {}
    const configured = data.dns_credentials_configured || {}
    dnsProviders.value.forEach(p => {
      if (!dnsCredentials.value[p.id]) dnsCredentials.value[p.id] = {}
      if (!dnsConfigured.value[p.id]) dnsConfigured.value[p.id] = {}
      p.fields.forEach(f => {
        dnsCredentials.value[p.id][f.key] = masked[p.id]?.[f.key] || ''
        dnsConfigured.value[p.id][f.key] = !!configured[p.id]?.[f.key]
      })
    })
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
  // 切换提供商时初始化凭证对象，避免 v-model 报错
  if (!dnsCredentials.value[form.value.dns_provider]) {
    dnsCredentials.value[form.value.dns_provider] = {}
    dnsConfigured.value[form.value.dns_provider] = {}
    const p = currentProvider.value
    if (p) {
      p.fields.forEach(f => {
        dnsCredentials.value[form.value.dns_provider][f.key] = ''
        dnsConfigured.value[form.value.dns_provider][f.key] = false
      })
    }
  }
}

const saveConfig = async () => {
  saving.value = true
  try {
    const saveData = { ...form.value }
    // 域名反代/混合模式附带 DNS 凭证（只提交用户新填写的值）
    if (form.value.access_mode === 'domain' || form.value.access_mode === 'hybrid') {
      const provider = form.value.dns_provider
      const creds = {}
      const p = currentProvider.value
      if (p) {
        p.fields.forEach(f => {
          const v = dnsCredentials.value[provider]?.[f.key]
          if (v && !v.startsWith('***')) creds[f.key] = v
        })
      }
      saveData.dns_credentials = { [provider]: creds }
    }
    await api.put('/config', saveData)
    // 域名/混合模式自动重新生成 Nginx 配置
    if (form.value.access_mode === 'domain' || form.value.access_mode === 'hybrid') {
      try { await api.post('/nginx/generate') } catch {}
    }
    ElMessage.success('配置已保存并应用')
    loadConfig()  // 刷新已配置状态
  } catch (e) { ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message)) }
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
