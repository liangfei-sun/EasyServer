<template>
  <div class="network-page">
    <h2>网络配置</h2>
    <p class="page-desc">管理域名、访问方式与服务发布</p>

    <!-- 区块1：网络状态总览 -->
    <el-card style="max-width: 800px; width: 100%; margin-bottom: 20px">
      <template #header>
        <div class="card-header-row">
          <span style="font-weight:600">网络状态</span>
          <el-tag v-if="isConfigured" :type="statusConnected ? 'success' : 'warning'" size="small">
            {{ statusConnected ? '已连接' : '已配置' }}
          </el-tag>
          <el-tag v-else type="info" size="small">未配置</el-tag>
        </div>
      </template>
      <el-descriptions :column="isMobile ? 1 : 2" border>
        <el-descriptions-item label="访问方式">{{ accessModeLabel }}</el-descriptions-item>
        <el-descriptions-item label="域名">{{ domain || '未设置' }}</el-descriptions-item>
        <el-descriptions-item v-if="currentMode === 'cloudflare_tunnel' || currentMode === 'hybrid'" label="隧道状态">
          <el-tag :type="tunnelStatus.connected ? 'success' : 'danger'" size="small">
            {{ tunnelStatus.connected ? '已连接' : '未连接' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item v-if="currentMode === 'cloudflare_tunnel' || currentMode === 'hybrid'" label="Tunnel 中转服务">
          {{ tunnelStatus.routes?.length || 0 }} 个
        </el-descriptions-item>
      </el-descriptions>
    </el-card>

    <!-- 区块1.5：系统诊断（仅已配置时显示） -->
    <el-card v-if="isConfigured" style="max-width: 800px; width: 100%; margin-bottom: 20px">
      <template #header>
        <div class="card-header-row">
          <span style="font-weight:600">系统诊断</span>
          <el-button size="small" :loading="diagnosticsLoading" @click="loadDiagnostics">刷新</el-button>
        </div>
      </template>
      <div v-loading="diagnosticsLoading && !diagnostics" style="min-height: 40px">
        <div v-if="diagnostics" class="diagnostics-grid">
          <div class="diag-item">
            <span class="diag-label">域名</span>
            <span class="diag-value">{{ diagnostics.domain || '未配置' }}</span>
          </div>
          <div class="diag-item">
            <span class="diag-label">公网 IPv4</span>
            <span class="diag-value" :class="{ 'text-red': !diagnostics.public_ipv4 }">
              {{ diagnostics.public_ipv4 || '未检测到' }}
            </span>
          </div>
          <div class="diag-item">
            <span class="diag-label">公网 IPv6</span>
            <span class="diag-value" :class="{ 'text-warn': !diagnostics.public_ipv6 }">
              {{ diagnostics.public_ipv6 || '未检测到' }}
            </span>
          </div>
          <div class="diag-item">
            <span class="diag-label">HTTPS 端口</span>
            <span class="diag-value">{{ diagnostics.https_port }}</span>
          </div>
          <div class="diag-item">
            <span class="diag-label">SSL 证书</span>
            <span class="diag-value">
              <el-tag :type="diagnostics.ssl_valid ? 'success' : 'warning'" size="small">
                {{ diagnostics.ssl_valid ? '有效' : '未配置' }}
              </el-tag>
              <span v-if="diagnostics.ssl_expiry && diagnostics.ssl_valid" style="font-size:12px;color:#909399;margin-left:6px">
                到期: {{ diagnostics.ssl_expiry }}
              </span>
            </span>
          </div>
        </div>
        <div v-if="diagnostics?.warnings?.length" style="margin-top: 12px">
          <el-alert v-for="(w, i) in diagnostics.warnings" :key="i" type="warning" :closable="false" :title="w.message" style="margin-bottom: 6px" />
        </div>
        <div v-else-if="diagnostics" style="margin-top: 12px">
          <el-alert type="success" :closable="false" title="所有检查项均正常" />
        </div>
      </div>
    </el-card>

    <!-- 域名管理 -->
    <DomainManager :domains="domains" :dns-providers="dnsProviders" @refresh="onDomainsChanged" />

    <!-- 场景A：未配置网络 - 智能推荐 -->
    <template v-if="!isConfigured">
      <el-card style="max-width: 800px; width: 100%; margin-bottom: 20px">
        <template #header><span style="font-weight:600">推荐方案</span></template>
        <div class="scheme-card recommended" :class="{ active: selectedScheme === 'tunnel' }" @click="selectedScheme = 'tunnel'">
          <div class="scheme-header">
            <span class="scheme-name">Cloudflare Tunnel</span>
            <el-tag type="success" size="small">推荐</el-tag>
          </div>
          <div class="scheme-desc">无需开放端口，免公网 IP，访问不带端口号</div>
          <div class="scheme-detect" v-if="detectInfo">
            <el-tag size="small" type="info">检测到: {{ detectInfo }}</el-tag>
          </div>
          <el-button type="primary" size="large" @click.stop="showTunnelSetupDialog = true" style="margin-top: 12px">一键接入</el-button>
        </div>
        <div class="scheme-card" :class="{ active: selectedScheme === 'domain' }" @click="selectedScheme = 'domain'">
          <div class="scheme-header">
            <span class="scheme-name">域名反代 (Nginx)</span>
            <el-tag size="small">备选</el-tag>
          </div>
          <div class="scheme-desc">需开放端口，访问需带端口号（如 :8443）</div>
          <el-button size="large" @click.stop="openDomainSetup" style="margin-top: 12px">展开配置</el-button>
        </div>
      </el-card>
    </template>

    <!-- 场景B：Tunnel 已配置 - 管理界面 -->
    <template v-if="currentMode === 'cloudflare_tunnel' && isConfigured">
      <TunnelSetup
        :tunnel-status="tunnelStatus"
        :domain="domain"
        :show-status-card="true"
        @setup-complete="onTunnelSetupComplete"
        @refresh-tunnel="loadTunnelStatus"
      />
      <TunnelPublish
        :tunnel-status="tunnelStatus"
        :selected-tunnel-domain="selectedTunnelDomain"
        @refresh="loadTunnelStatus"
      />
    </template>

    <!-- 场景C：域名反代 / 智能混合路由已配置 - 管理界面 -->
    <DomainReverse
      v-if="(currentMode === 'domain' || currentMode === 'hybrid') && isConfigured"
      ref="domainReverseRef"
      :domain-form="domainForm"
      :domain="domain"
      :current-mode="currentMode"
      :dns-providers="dnsProviders"
      :dns-credentials="dnsCredentials"
      :dns-configured="dnsConfigured"
      :ssl-valid="sslValid"
      :ssl-expiry="sslExpiry"
      :dns-sync="dnsSync"
      :dns-sync-result="dnsSyncResult"
      :tunnel-status="tunnelStatus"
      :tunnel-loading="tunnelLoading"
      :selected-tunnel-domain="selectedTunnelDomain"
      :https-port="domainForm.https_port"
      @update:ssl-valid="sslValid = $event"
      @update:ssl-expiry="sslExpiry = $event"
      @update:dns-sync-result="dnsSyncResult = $event"
      @refresh-config="onConfigChanged"
      @refresh-tunnel="loadTunnelStatus"
      @refresh-dns="loadDnsStatus"
      @regenerate-nginx="regenerateNginx"
      @open-tunnel-setup="showTunnelSetupDialog = true"
    />

    <!-- 场景D：IPv6 直连已配置 -->
    <template v-if="currentMode === 'ipv6_direct' && isConfigured">
      <el-card style="max-width: 800px; width: 100%; margin-bottom: 20px">
        <template #header><span style="font-weight:600">IPv6 直连</span></template>
        <el-alert type="info" :closable="false" style="margin-bottom: 16px">
          服务端口直接暴露在公网，通过 <code>http://[公网IPv6]:端口</code> 访问各服务，无需域名和 DNS。
        </el-alert>
        <el-table :data="serviceList" size="small" empty-text="暂无已安装的服务">
          <el-table-column prop="name" label="服务" min-width="120" />
          <el-table-column prop="port" label="端口" width="80" />
          <el-table-column label="访问地址" min-width="200">
            <template #default="{ row }">
              <span v-if="ipv6Addr" style="font-family:monospace;font-size:12px">http://[{{ ipv6Addr }}]:{{ row.port }}</span>
              <span v-else style="color:#909399">未检测到 IPv6 地址</span>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </template>

    <!-- 场景E：自由配置已配置 -->
    <template v-if="currentMode === 'custom' && isConfigured">
      <el-card style="max-width: 800px; width: 100%; margin-bottom: 20px">
        <template #header><span style="font-weight:600">自由配置</span></template>
        <el-alert type="info" :closable="false" style="margin-bottom: 16px">
          自由配置模式不会自动管理网络模块，你可以从应用商店自行安装和配置所需服务。
        </el-alert>
        <div style="margin-bottom: 12px; display: flex; gap: 8px">
          <el-button type="primary" size="small" @click="$router.push('/market')">前往应用商店</el-button>
          <el-button size="small" @click="regenerateNginx">重新生成 Nginx 配置</el-button>
        </div>
        <el-table :data="networkModules" size="small" empty-text="暂无网络模块">
          <el-table-column prop="name" label="模块" min-width="120" />
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="row.running ? 'success' : 'info'" size="small">{{ row.running ? '运行中' : '已停止' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="160">
            <template #default="{ row }">
              <el-button v-if="row.running" type="warning" size="small" @click="stopModule(row.id)">停止</el-button>
              <el-button v-else type="primary" size="small" @click="startModule(row.id)">启动</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </template>

    <!-- 区块3：高级选项（折叠区） -->
    <el-card style="max-width: 800px; width: 100%; margin-bottom: 20px">
      <el-collapse>
        <el-collapse-item title="高级选项">
          <div class="advanced-section">
            <div class="advanced-item">
              <div class="advanced-title">IPv6 直连</div>
              <div class="advanced-desc">直接用公网 IPv6 地址访问，无需域名和 DNS。通过 <code>http://[IPv6]:端口</code> 访问各服务。</div>
              <el-button size="small" :disabled="currentMode === 'ipv6_direct'" @click="switchMode('ipv6_direct')">
                {{ currentMode === 'ipv6_direct' ? '当前使用' : '切换到 IPv6 直连' }}
              </el-button>
            </div>
            <el-divider />
            <div class="advanced-item">
              <div class="advanced-title">自由配置</div>
              <div class="advanced-desc">不自动管理网络模块，自行从应用商店安装和配置所需服务。</div>
              <el-button size="small" :disabled="currentMode === 'custom'" @click="switchMode('custom')">
                {{ currentMode === 'custom' ? '当前使用' : '切换到自由配置' }}
              </el-button>
            </div>
            <el-divider v-if="isConfigured" />
            <div class="advanced-item" v-if="isConfigured">
              <div class="advanced-title">切换访问方式</div>
              <div class="advanced-desc">更改当前的访问方式，切换后可能会停止或启动相关模块。</div>
              <div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap">
                <el-button size="small" :disabled="currentMode === 'cloudflare_tunnel'" @click="switchMode('cloudflare_tunnel')">Cloudflare Tunnel</el-button>
                <el-button size="small" :disabled="currentMode === 'domain'" @click="switchMode('domain')">域名反代</el-button>
                <el-button size="small" :disabled="currentMode === 'hybrid'" @click="switchMode('hybrid')">智能混合路由</el-button>
              </div>
              <div class="form-help" style="margin-top:8px">
                智能混合路由：域名反代 + Tunnel 中转并存，大带宽服务走域名反代，轻量服务走 Tunnel
              </div>
            </div>
          </div>
        </el-collapse-item>
      </el-collapse>
    </el-card>

    <!-- 区块4：SSL 配置（底部） -->
    <el-card style="max-width: 800px; width: 100%; margin-bottom: 20px">
      <template #header><span style="font-weight:600">🔒 SSL 配置</span></template>
      <el-form label-width="100px">
        <el-form-item label="SSL 邮箱">
          <el-input v-model="sslEmailInput" placeholder="admin@example.com" />
          <div class="form-help">用于 Let's Encrypt 自动签发 / 续签 SSL 证书</div>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="saveDomain" :loading="savingDomainInfo">保存</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- Tunnel 一键接入弹窗（未配置时从推荐卡片触发，或 domain/hybrid 模式下从 Tunnel 引导触发） -->
    <TunnelSetup
      v-model="showTunnelSetupDialog"
      :tunnel-status="tunnelStatus"
      :domain="domain"
      :show-status-card="false"
      @setup-complete="onTunnelSetupComplete"
      @refresh-tunnel="loadTunnelStatus"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox, ElLoading } from 'element-plus'
import { useMobile } from '@/composables/useMobile'
import api from '../api'
import DomainManager from './network/DomainManager.vue'
import TunnelSetup from './network/TunnelSetup.vue'
import TunnelPublish from './network/TunnelPublish.vue'
import DomainReverse from './network/DomainReverse.vue'

// 网络模式切换涉及模块安装与启动，首次切换耗时较长，单独放宽超时（10 分钟），
// 其他普通 API 请求仍保持全局 30s 超时不受影响
const NETWORK_SWITCH_TIMEOUT = 10 * 60 * 1000
const SWITCH_LOADING_TEXT = '正在切换访问方式，首次切换需安装并启动相关模块，可能需要几分钟，请勿关闭页面'

const { isMobile } = useMobile()

// ===== 基础状态 =====
const domain = ref('')
const sslEmailInput = ref('')
const currentMode = ref('domain')
const isConfigured = ref(false)
const savingDomainInfo = ref(false)

const accessModeLabels = {
  cloudflare_tunnel: 'Cloudflare Tunnel',
  domain: '域名反代 (Nginx)',
  ipv6_direct: 'IPv6 直连',
  custom: '自由配置',
  hybrid: '智能混合路由'
}
const accessModeLabel = computed(() => accessModeLabels[currentMode.value] || '未配置')

// ===== 系统诊断 =====
const diagnostics = ref(null)
const diagnosticsLoading = ref(false)

const loadDiagnostics = async () => {
  diagnosticsLoading.value = true
  try {
    const { data } = await api.get('/config/diagnostics')
    diagnostics.value = data
  } catch (e) {
    console.error('系统诊断失败:', e)
  } finally {
    diagnosticsLoading.value = false
  }
}

// ===== 域名管理 =====
const domains = ref([])
const selectedTunnelDomain = ref('')

const tunnelDomains = computed(() =>
  domains.value.filter(d => d.purpose === 'tunnel' || d.purpose === 'both')
)

// ===== 智能推荐 =====
const selectedScheme = ref('tunnel')
const detectInfo = ref('')
const showTunnelSetupDialog = ref(false)
const domainReverseRef = ref(null)

const openDomainSetup = () => {
  domainReverseRef.value?.openSetupDialog()
}

// ===== Tunnel 状态 =====
const tunnelStatus = ref({ configured: false, connected: false, routes: [], services: [] })
const tunnelLoading = ref(false)

const statusConnected = computed(() => {
  if (currentMode.value === 'cloudflare_tunnel') return tunnelStatus.value.connected
  return isConfigured.value
})

// ===== 域名反代配置（传递给 DomainReverse）=====
const domainForm = ref({
  dns_provider: 'aliyun', https_port: 8443, ssl_email: '', panel_subdomain: 'panel'
})
const dnsProviders = ref([])
const dnsCredentials = ref({ aliyun: {}, cloudflare: {} })
const dnsConfigured = ref({})
const sslValid = ref(false)
const sslExpiry = ref('')

// ===== DNS 记录同步 =====
const dnsSync = ref({ ipv4: '', ipv6: '' })
const dnsSyncResult = ref({})

const loadDnsStatus = async () => {
  try {
    const { data } = await api.get('/dns/status')
    dnsSync.value = { ipv4: data.public_ipv4 || '', ipv6: data.public_ipv6 || '' }
  } catch { /* 忽略 */ }
}

// ===== IPv6 =====
const ipv6Addr = ref('')
const serviceList = ref([])

// ===== 自由配置 =====
const networkModules = ref([])

// ===== 数据加载 =====
const loadConfig = async () => {
  try {
    const { data } = await api.get('/config')
    const cfg = data.config || {}
    const env = data.env_summary || {}
    domain.value = env.DOMAIN || cfg.domain || ''
    sslEmailInput.value = cfg.ssl_email || ''
    const rawMode = env.ACCESS_MODE || cfg.access_mode || 'domain'
    currentMode.value = rawMode
    isConfigured.value = !!data.network_configured || !!cfg.network_configured

    // DNS 提供商
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

    domainForm.value.dns_provider = cfg.dns_provider || 'aliyun'
    domainForm.value.https_port = parseInt(env.HTTPS_PORT) || cfg.https_port || 8443
    domainForm.value.ssl_email = cfg.ssl_email || ''
    domainForm.value.panel_subdomain = cfg.panel_subdomain || 'panel'

    if (domain.value) {
      detectInfo.value = `域名 ${domain.value} 已配置`
    }

    const ssl = data.ssl_status || {}
    sslValid.value = !!ssl.ssl_valid
    sslExpiry.value = ssl.ssl_expiry || ''

    // 多域名列表
    domains.value = data.domains || []
    if (tunnelDomains.value.length > 0 && !selectedTunnelDomain.value) {
      selectedTunnelDomain.value = tunnelDomains.value[0].domain
    }
  } catch (e) {
    ElMessage.error('加载配置失败')
  }
}

const loadTunnelStatus = async () => {
  tunnelLoading.value = true
  try {
    const { data } = await api.get('/cloudflare/status')
    tunnelStatus.value = data
  } catch (e) {
    // Tunnel 未配置时忽略错误
  } finally {
    tunnelLoading.value = false
  }
}

const loadServices = async () => {
  try {
    const { data } = await api.get('/services')
    serviceList.value = (data.services || [])
      .filter(s => s.port)
      .map(s => ({ name: s.name || s.module, port: s.port }))

    const netIds = ['nginx', 'acme', 'ddns-go', 'cloudflare-tunnel']
    networkModules.value = (data.services || [])
      .filter(s => netIds.includes(s.module))
      .map(s => ({ id: s.module, name: s.name || s.module, running: s.running }))
  } catch (e) { /* ignore */ }
}

const detectIPv6 = async () => {
  try {
    ipv6Addr.value = '' // 暂时留空，后续可扩展
  } catch { /* ignore */ }
}

// ===== 子组件事件处理 =====
const onDomainsChanged = async () => {
  // 域名变更后重新加载域名列表和配置
  try {
    const res = await api.get('/config/domains')
    domains.value = res.data.domains || []
  } catch (e) {
    console.error('加载域名失败:', e)
  }
  await loadConfig()
}

const onTunnelSetupComplete = () => {
  loadTunnelStatus()
  loadConfig()
}

const onConfigChanged = () => {
  loadConfig()
  loadTunnelStatus()
  loadServices()
}

// ===== Nginx =====
const regenerateNginx = async () => {
  try {
    await api.post('/nginx/generate')
    ElMessage.success('Nginx 配置已重新生成')
  } catch (e) {
    ElMessage.error('生成失败: ' + (e.response?.data?.detail || e.message))
  }
}

// ===== SSL 邮箱保存 =====
const saveDomain = async () => {
  savingDomainInfo.value = true
  try {
    await api.put('/config', { ssl_email: sslEmailInput.value })
    ElMessage.success('SSL 邮箱已保存')
    loadConfig()
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
  }
  savingDomainInfo.value = false
}

// ===== 切换模式 =====
const switchMode = async (mode) => {
  const modeLabel = accessModeLabels[mode] || mode
  try {
    await ElMessageBox.confirm(
      `确定切换到「${modeLabel}」？\n切换后可能会停止当前正在使用的网络模块。`,
      '切换访问方式',
      { confirmButtonText: '确认切换', cancelButtonText: '取消', type: 'warning' }
    )
  } catch { return }

  const loading = ElLoading.service({ lock: true, text: SWITCH_LOADING_TEXT, background: 'rgba(0, 0, 0, 0.6)' })
  try {
    await api.post('/config/network', { access_mode: mode }, { timeout: NETWORK_SWITCH_TIMEOUT })
    ElMessage.success(`已切换到 ${modeLabel}`)
    loadConfig()
    loadTunnelStatus()
    loadServices()
  } catch (e) {
    ElMessage.error('切换失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    loading.close()
  }
}

// ===== 自由配置模块操作 =====
const startModule = async (moduleId) => {
  try {
    await api.post(`/services/${moduleId}/start`)
    ElMessage.success(`${moduleId} 已启动`)
    loadServices()
  } catch (e) { ElMessage.error('启动失败: ' + (e.response?.data?.detail || e.message)) }
}

const stopModule = async (moduleId) => {
  try {
    await ElMessageBox.confirm(`确定停止 ${moduleId}？`, '确认操作')
  } catch { return }
  try {
    await api.post(`/services/${moduleId}/stop`)
    ElMessage.success(`${moduleId} 已停止`)
    loadServices()
  } catch (e) { ElMessage.error('停止失败: ' + (e.response?.data?.detail || e.message)) }
}

// ===== 初始化 =====
onMounted(async () => {
  await loadConfig()
  loadTunnelStatus()
  loadServices()
  detectIPv6()
  loadDnsStatus()
  if (isConfigured.value) loadDiagnostics()
})
</script>

<style scoped>
.network-page { max-width: 840px; }
.page-desc { color: #909399; margin: 4px 0 20px; font-size: 14px; }
.card-header-row { display: flex; justify-content: space-between; align-items: center; }

.scheme-card {
  padding: 20px; border: 2px solid #e4e7ed; border-radius: 12px;
  cursor: pointer; transition: all 0.2s; margin-bottom: 12px;
}
.scheme-card:hover { border-color: #409eff; background: #f5f7fa; }
.scheme-card.active { border-color: #409eff; background: #ecf5ff; }
.scheme-card.recommended { border-color: #67c23a; }
.scheme-card.recommended.active { border-color: #67c23a; background: #f0f9eb; }
.scheme-header { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.scheme-name { font-weight: 600; font-size: 15px; }
.scheme-desc { font-size: 13px; color: #909399; }
.scheme-detect { margin-top: 8px; }

.form-help { font-size: 12px; color: #909399; margin-top: 4px; line-height: 1.5; }

.advanced-section { padding: 4px 0; }
.advanced-item { padding: 8px 0; }
.advanced-title { font-weight: 600; font-size: 14px; margin-bottom: 4px; }
.advanced-desc { font-size: 13px; color: #909399; margin-bottom: 8px; line-height: 1.5; }
.advanced-desc code { background: #f0f2f5; padding: 1px 4px; border-radius: 3px; font-size: 12px; }

.diagnostics-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px 20px;
}
.diag-item { display: flex; flex-direction: column; gap: 4px; }
.diag-label { font-size: 12px; color: #909399; }
.diag-value { font-size: 14px; color: #303133; font-weight: 500; }
.text-red { color: #f56c6c; }
.text-warn { color: #e6a23c; }
</style>
