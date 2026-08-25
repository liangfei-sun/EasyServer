<template>
  <div>
    <el-alert
      v-if="currentMode === 'hybrid'"
      type="info"
      :closable="false"
      style="max-width: 800px; width: 100%; margin-bottom: 20px"
      title="智能混合路由：域名反代 + Tunnel 中转并存。大带宽服务走域名反代，轻量服务走 Tunnel 中转，可在下方「Tunnel 中转服务」中按服务切换。"
    />
    <el-card style="max-width: 800px; width: 100%; margin-bottom: 20px">
      <template #header><span style="font-weight:600">域名反代配置</span></template>
      <el-form :model="domainForm" label-width="120px">
        <el-form-item label="DNS 提供商">
          <el-select v-model="domainForm.dns_provider" style="width: 100%" @change="onDnsProviderChange">
            <el-option v-for="p in dnsProviders" :key="p.id" :label="p.name" :value="p.id">
              <span>{{ p.name }}</span>
              <span style="color: #909399; font-size: 12px; margin-left: 8px">{{ p.acme_plugin || '自定义插件' }}</span>
            </el-option>
          </el-select>
          <div class="form-help">{{ currentDnsProvider?.description }}</div>
        </el-form-item>
        <template v-if="currentDnsProvider">
          <el-form-item v-for="f in currentDnsProvider.fields" :key="f.key" :label="f.label">
            <el-input
              v-if="f.type !== 'textarea'"
              v-model="dnsCredentials[domainForm.dns_provider][f.key]"
              type="password" show-password
              :placeholder="dnsConfigured[domainForm.dns_provider]?.[f.key] ? '已配置，留空保持不变' : (f.placeholder || '请输入')"
            />
            <el-input v-else v-model="dnsCredentials[domainForm.dns_provider][f.key]" type="textarea" :rows="4" :placeholder="f.placeholder" />
            <div class="form-help" v-if="f.help">
              {{ f.help }}
              <a v-if="currentDnsProvider.help_url" :href="currentDnsProvider.help_url" target="_blank" style="margin-left:4px;color:#409eff">前往创建</a>
            </div>
            <el-tag v-if="dnsConfigured[domainForm.dns_provider]?.[f.key]" type="success" size="small" style="margin-top: 4px">
              已配置（留空则不修改）
            </el-tag>
          </el-form-item>
        </template>
        <el-form-item label="HTTPS 端口">
          <el-input-number v-model="domainForm.https_port" :min="1" :max="65535" />
        </el-form-item>
        <el-form-item label="管理面板子域名">
          <el-input v-model="domainForm.panel_subdomain" placeholder="panel">
            <template #append>.{{ domain }}</template>
          </el-input>
        </el-form-item>
        <el-form-item label="SSL 证书">
          <div style="display:flex;align-items:center;gap:8px">
            <el-tag :type="sslValid ? 'success' : 'warning'" size="small">{{ sslValid ? '有效' : '未配置' }}</el-tag>
            <span v-if="sslExpiry" style="font-size:12px;color:#909399">到期: {{ sslExpiry }}</span>
            <el-button size="small" @click="handleCheckSSL" :loading="sslChecking">刷新</el-button>
          </div>
        </el-form-item>
        <el-form-item label="DNS 记录同步">
          <div style="width:100%">
            <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
              <el-tag v-if="dnsSync.ipv4" type="success" size="small">IPv4: {{ dnsSync.ipv4 }}</el-tag>
              <el-tag v-if="dnsSync.ipv6" type="info" size="small">IPv6: {{ dnsSync.ipv6 }}</el-tag>
              <el-button size="small" type="success" @click="handleSyncDns" :loading="dnsSyncing">
                立即同步 DNS 记录
              </el-button>
            </div>
            <div class="form-help" style="margin-top:4px">
              自动为所有服务子域名创建 A / AAAA 解析记录（指向服务器公网 IP），无需登录 DNS 网站手动配置
            </div>
            <!-- 同步结果 -->
            <el-alert
              v-if="dnsSyncResult.summary"
              :type="(dnsSyncResult.summary.failed || dnsSyncResult.summary.skipped) ? 'warning' : 'success'"
              :closable="false"
              style="margin-top:8px"
              :title="`同步完成：新建 ${dnsSyncResult.summary.created} 条，更新 ${dnsSyncResult.summary.updated} 条，无变化 ${dnsSyncResult.summary.unchanged} 条，跳过 ${dnsSyncResult.summary.skipped || 0} 条，失败 ${dnsSyncResult.summary.failed} 条`"
            />
            <div v-if="dnsSyncResult.summary && dnsSyncResult.summary.skipped" class="form-help" style="color:#e6a23c">
              {{ dnsSyncResult.summary.skipped }} 个子域名因已存在 CNAME 记录被跳过（可能已通过 Tunnel 中转发布）
            </div>
            <div v-if="dnsSyncResult.skippedList?.length" style="margin-top:6px">
              <div v-for="(s, i) in dnsSyncResult.skippedList" :key="i" class="form-help" style="color:#e6a23c">
                {{ s.subdomain }}：{{ s.reason || '已存在 CNAME 记录，已跳过' }}
              </div>
            </div>
            <div v-if="dnsSyncResult.failures?.length" style="margin-top:6px">
              <div v-for="(f, i) in dnsSyncResult.failures" :key="i" class="form-help" style="color:#f56c6c">
                {{ f.subdomain }} ({{ f.type }}): {{ f.error }}
              </div>
            </div>
          </div>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="handleSaveConfig" :loading="savingDomain">保存并应用</el-button>
          <el-button @click="$emit('regenerate-nginx')">重新生成 Nginx 配置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- Tunnel 中转服务卡片（域名反代 / 智能混合路由模式） -->
    <el-card style="max-width: 800px; width: 100%; margin-bottom: 20px">
      <template #header>
        <div class="card-header-row">
          <span style="font-weight:600">Tunnel 中转服务</span>
          <div style="display:flex;align-items:center;gap:8px">
            <el-button
              v-if="tunnelStatus.configured"
              size="small" type="success" plain
              :loading="smartConfiguring"
              :disabled="!!routeSwitchingId || smartConfiguring"
              @click="handleApplySmartRouting"
            >
              智能推荐
            </el-button>
            <el-button size="small" :loading="tunnelLoading" @click="$emit('refresh-tunnel')">刷新</el-button>
          </div>
        </div>
      </template>

      <!-- Tunnel 未接入：友好引导 -->
      <div v-if="!tunnelStatus.configured" class="tunnel-guide">
        <div class="tunnel-guide-title">尚未接入 Cloudflare Tunnel</div>
        <p class="tunnel-guide-desc">
          当前所有服务都通过域名反代访问。接入 Cloudflare Tunnel 后，即可按服务选择路由方式：
          大带宽服务继续走域名反代，轻量服务改走 Tunnel 中转（免端口号、无需开放端口）。
        </p>
        <el-button type="primary" size="small" @click="$emit('open-tunnel-setup')">接入 Cloudflare Tunnel</el-button>
      </div>

      <!-- 已接入：服务路由列表 -->
      <template v-else>
        <el-table :data="tunnelStatus.services" size="small" v-loading="tunnelLoading" empty-text="暂无已安装的服务">
          <el-table-column label="服务" min-width="130">
            <template #default="{ row }">
              <span>{{ row.name }}</span>
            </template>
          </el-table-column>
          <el-table-column label="路由方式" width="110">
            <template #default="{ row }">
              <el-tag :type="row.published ? 'primary' : 'success'" size="small">
                {{ row.published ? 'Tunnel 中转' : '域名反代' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="访问地址" min-width="200">
            <template #default="{ row }">
              <a v-if="row.hostname" :href="serviceUrl(row)" target="_blank" class="route-link">{{ serviceUrl(row) }}</a>
              <span v-else style="color:#909399">未配置域名</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="160">
            <template #default="{ row }">
              <el-button
                :type="row.published ? 'success' : 'primary'"
                size="small" plain
                :loading="routeSwitchingId === row.module"
                :disabled="!!routeSwitchingId || smartConfiguring"
                @click="handleSwitchRoute(row)"
              >
                {{ row.published ? '切换为域名反代' : '切换为 Tunnel 中转' }}
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="form-help" style="margin-top: 8px">
          域名反代：DNS AAAA → 服务器 IPv6 → Nginx SSL，适合大带宽服务（访问需带端口）；
          Tunnel 中转：DNS CNAME → Cloudflare 边缘，免端口号。切换后自动更新 DNS 记录。
        </div>
      </template>
    </el-card>

    <!-- 域名反代配置弹窗（未配置时引导用） -->
    <el-dialog v-model="showDomainSetup" title="域名反代配置" :width="isMobile ? '95%' : '680px'" top="5vh" :close-on-click-modal="false">
      <el-form :model="domainForm" label-width="120px">
        <el-form-item label="DNS 提供商">
          <el-select v-model="domainForm.dns_provider" style="width: 100%" @change="onDnsProviderChange">
            <el-option v-for="p in dnsProviders" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <template v-if="currentDnsProvider">
          <el-form-item v-for="f in currentDnsProvider.fields" :key="f.key" :label="f.label">
            <el-input
              v-if="f.type !== 'textarea'"
              v-model="dnsCredentials[domainForm.dns_provider][f.key]"
              type="password" show-password
              :placeholder="f.placeholder || '请输入'"
            />
            <el-input v-else v-model="dnsCredentials[domainForm.dns_provider][f.key]" type="textarea" :rows="3" :placeholder="f.placeholder" />
            <div class="form-help" v-if="f.help">{{ f.help }}</div>
          </el-form-item>
        </template>
        <el-form-item label="HTTPS 端口">
          <el-input-number v-model="domainForm.https_port" :min="1" :max="65535" />
        </el-form-item>
        <el-form-item label="SSL 邮箱">
          <el-input v-model="domainForm.ssl_email" placeholder="admin@example.com" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="handleApplyDomainMode" :loading="savingDomain">保存并应用</el-button>
        </el-form-item>
      </el-form>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { ElMessage, ElMessageBox, ElLoading } from 'element-plus'
import { useMobile } from '@/composables/useMobile'
import api from '../../api'

const NETWORK_SWITCH_TIMEOUT = 10 * 60 * 1000
const SWITCH_LOADING_TEXT = '正在切换访问方式，首次切换需安装并启动相关模块，可能需要几分钟，请勿关闭页面'

const SMART_DIRECT_MODULES = ['frigate', 'nextcloud', 'jellyfin', 'filebrowser', 'calibre-web']
const SMART_TUNNEL_MODULES = ['notediscovery', 'joplin', 'uptime-kuma']

const props = defineProps({
  domainForm: { type: Object, required: true },
  domain: { type: String, default: '' },
  currentMode: { type: String, default: 'domain' },
  dnsProviders: { type: Array, default: () => [] },
  dnsCredentials: { type: Object, required: true },
  dnsConfigured: { type: Object, required: true },
  sslValid: { type: Boolean, default: false },
  sslExpiry: { type: String, default: '' },
  dnsSync: { type: Object, default: () => ({ ipv4: '', ipv6: '' }) },
  dnsSyncResult: { type: Object, default: () => ({}) },
  tunnelStatus: { type: Object, required: true },
  tunnelLoading: { type: Boolean, default: false },
  selectedTunnelDomain: { type: String, default: '' },
  httpsPort: { type: Number, default: 8443 },
})

const emit = defineEmits([
  'refresh-config', 'refresh-tunnel', 'refresh-dns', 'regenerate-nginx', 'open-tunnel-setup',
  'update:sslValid', 'update:sslExpiry', 'update:dnsSyncResult',
])

const { isMobile } = useMobile()

const savingDomain = ref(false)
const sslChecking = ref(false)
const dnsSyncing = ref(false)
const showDomainSetup = ref(false)

const openSetupDialog = () => { showDomainSetup.value = true }
defineExpose({ openSetupDialog })
const routeSwitchingId = ref('')
const smartConfiguring = ref(false)

const currentDnsProvider = computed(() =>
  props.dnsProviders.find(p => p.id === props.domainForm.dns_provider) || null
)

// 服务访问地址
const serviceUrl = (row) => {
  if (row.published) return `https://${row.hostname}`
  return `https://${row.hostname}:${props.httpsPort}`
}

const onDnsProviderChange = () => {
  if (!props.dnsCredentials[props.domainForm.dns_provider]) {
    props.dnsCredentials[props.domainForm.dns_provider] = {}
    props.dnsConfigured[props.domainForm.dns_provider] = {}
    const p = currentDnsProvider.value
    if (p) {
      p.fields.forEach(f => {
        props.dnsCredentials[props.domainForm.dns_provider][f.key] = ''
        props.dnsConfigured[props.domainForm.dns_provider][f.key] = false
      })
    }
  }
}

const handleCheckSSL = async () => {
  sslChecking.value = true
  try {
    const { data } = await api.get('/config')
    const ssl = data.ssl_status || {}
    emit('update:sslValid', !!ssl.ssl_valid)
    emit('update:sslExpiry', ssl.ssl_expiry || '')
  } catch {
    emit('update:sslValid', false)
    emit('update:sslExpiry', '')
  }
  sslChecking.value = false
}

const handleSyncDns = async () => {
  dnsSyncing.value = true
  try {
    const { data } = await api.post('/dns/sync')
    const summary = data.summary || {}
    summary.skipped = summary.skipped || 0
    emit('update:dnsSyncResult', {
      summary,
      failures: (data.results || []).filter(r => !r.success && r.action !== 'skipped'),
      skippedList: (data.results || []).filter(r => r.action === 'skipped')
    })
    if (summary.failed) {
      ElMessage.warning(`DNS 同步完成，但 ${summary.failed} 条记录失败，请检查凭证`)
    } else if (summary.skipped) {
      ElMessage.warning(`DNS 同步完成：${summary.skipped} 个子域名因已存在 CNAME 记录被跳过（可能已通过 Tunnel 发布）`)
    } else {
      ElMessage.success(`DNS 同步完成：新建 ${summary.created} 条，更新 ${summary.updated} 条，无变化 ${summary.unchanged} 条`)
    }
    emit('refresh-dns')
  } catch (e) {
    ElMessage.error('DNS 同步失败: ' + (e.response?.data?.detail || e.message))
  }
  dnsSyncing.value = false
}

const handleSaveConfig = async () => {
  savingDomain.value = true
  try {
    const provider = props.domainForm.dns_provider
    const creds = {}
    const p = currentDnsProvider.value
    if (p) {
      p.fields.forEach(f => {
        const v = props.dnsCredentials[provider]?.[f.key]
        if (v && !v.startsWith('***')) creds[f.key] = v
      })
    }
    await api.put('/config', {
      dns_provider: provider,
      dns_credentials: { [provider]: creds },
      https_port: props.domainForm.https_port,
      panel_subdomain: props.domainForm.panel_subdomain,
      ssl_email: props.domainForm.ssl_email
    })
    await api.post('/nginx/generate')
    ElMessage.success('配置已保存并应用')
    emit('refresh-config')
    emit('refresh-dns')
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
  }
  savingDomain.value = false
}

const handleApplyDomainMode = async () => {
  savingDomain.value = true
  const loading = ElLoading.service({ lock: true, text: SWITCH_LOADING_TEXT, background: 'rgba(0, 0, 0, 0.6)' })
  try {
    const provider = props.domainForm.dns_provider
    const creds = {}
    const p = currentDnsProvider.value
    if (p) {
      p.fields.forEach(f => {
        const v = props.dnsCredentials[provider]?.[f.key]
        if (v && !v.startsWith('***')) creds[f.key] = v
      })
    }
    await api.post('/config/network', {
      access_mode: 'domain',
      dns_provider: provider,
      dns_credentials: { [provider]: creds },
      https_port: props.domainForm.https_port
    }, { timeout: NETWORK_SWITCH_TIMEOUT })
    showDomainSetup.value = false
    ElMessage.success('域名反代已配置并应用')
    emit('refresh-config')
    emit('refresh-dns')
  } catch (e) {
    ElMessage.error('配置失败: ' + (e.response?.data?.detail || e.message))
  }
  loading.close()
  savingDomain.value = false
}

const handleSwitchRoute = async (row) => {
  routeSwitchingId.value = row.module
  try {
    if (row.published) {
      const { data } = await api.post('/cloudflare/unpublish', { hostname: row.hostname })
      ElMessage.success(`${row.name} 已切换为域名反代`)
      if (data.warnings?.length) data.warnings.forEach(w => ElMessage.warning(w))
    } else {
      const { data } = await api.post('/cloudflare/publish', {
        subdomain: row.subdomain, port: row.port,
        ...(props.selectedTunnelDomain ? { domain: props.selectedTunnelDomain } : {})
      })
      ElMessage.success(`${row.name} 已切换为 Tunnel 中转`)
      if (data.dns_warning) ElMessage.warning(data.dns_warning)
    }
    emit('refresh-tunnel')
  } catch (e) {
    ElMessage.error('切换失败: ' + (e.response?.data?.detail || e.message))
  }
  routeSwitchingId.value = ''
}

const handleApplySmartRouting = async () => {
  const services = props.tunnelStatus.services || []
  const toTunnel = services.filter(s => SMART_TUNNEL_MODULES.includes(s.module) && !s.published)
  const toDirect = services.filter(s => SMART_DIRECT_MODULES.includes(s.module) && s.published)
  if (!toTunnel.length && !toDirect.length) {
    ElMessage.info('当前路由配置已符合智能推荐，无需调整')
    return
  }
  const lines = []
  if (toTunnel.length) lines.push(`切换为 Tunnel 中转：${toTunnel.map(s => s.name).join('、')}`)
  if (toDirect.length) lines.push(`切换为域名反代：${toDirect.map(s => s.name).join('、')}`)
  try {
    await ElMessageBox.confirm(
      `智能推荐将按以下规则调整服务路由：\n${lines.join('\n')}\n其余服务保持当前路由方式不变。`,
      '智能推荐',
      { confirmButtonText: '开始配置', cancelButtonText: '取消', type: 'info' }
    )
  } catch { return }

  smartConfiguring.value = true
  const failed = []
  let okCount = 0
  for (const s of toTunnel) {
    try {
      const { data } = await api.post('/cloudflare/publish', {
        subdomain: s.subdomain, port: s.port,
        ...(props.selectedTunnelDomain ? { domain: props.selectedTunnelDomain } : {})
      })
      okCount++
      if (data.dns_warning) ElMessage.warning(`${s.name}: ${data.dns_warning}`)
    } catch (e) {
      failed.push(`${s.name}（Tunnel 中转）`)
    }
  }
  for (const s of toDirect) {
    try {
      await api.post('/cloudflare/unpublish', { hostname: s.hostname })
      okCount++
    } catch (e) {
      failed.push(`${s.name}（域名反代）`)
    }
  }
  smartConfiguring.value = false
  emit('refresh-tunnel')
  if (failed.length) {
    ElMessage.warning(`智能配置完成：成功 ${okCount} 项，失败 ${failed.length} 项（${failed.join('、')}），可单独重试`)
  } else {
    ElMessage.success('智能配置完成：大带宽服务走域名反代，轻量服务走 Tunnel 中转')
  }
}
</script>

<style scoped>
.card-header-row { display: flex; justify-content: space-between; align-items: center; }
.form-help { font-size: 12px; color: #909399; margin-top: 4px; line-height: 1.5; }
.form-help a { color: #409eff; text-decoration: none; }
.route-link { color: #409eff; font-weight: 600; font-size: 13px; }
.tunnel-guide { padding: 12px 4px; }
.tunnel-guide-title { font-weight: 600; font-size: 14px; color: #606266; margin-bottom: 6px; }
.tunnel-guide-desc { font-size: 13px; color: #909399; line-height: 1.6; margin: 0 0 12px; }
</style>
