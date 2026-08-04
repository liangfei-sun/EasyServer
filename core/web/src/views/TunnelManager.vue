<template>
  <div class="tunnel-page">
    <h2>Cloudflare Tunnel 管理</h2>
    <p class="page-desc">无需开放端口，通过 Cloudflare 隧道将服务发布到公网，访问无需输入端口号</p>

    <!-- 未接入：一键接入流程 -->
    <el-card v-if="!status.configured" style="max-width: 720px; width: 100%">
      <template #header><span style="font-weight:600">一键接入</span></template>
      <el-steps :active="setupStep" align-center finish-status="success" style="margin-bottom: 24px">
        <el-step title="创建 API Token" />
        <el-step title="粘贴并验证" />
        <el-step title="自动接入" />
      </el-steps>

      <el-alert type="info" :closable="false" style="margin-bottom: 16px">
        <p style="margin: 0 0 8px"><b>只需在 Cloudflare 做一次操作</b>：创建一个 API Token（约 1 分钟），其余全部由 EasyServer 自动完成。</p>
        <ol style="margin: 0; padding-left: 20px; line-height: 1.8">
          <li>打开 <a href="https://dash.cloudflare.com/profile/api-tokens" target="_blank" style="color:#409eff">Cloudflare API Tokens</a> 页面</li>
          <li>点击 <b>Create Token</b> → 选择模板 <b>Edit zone DNS</b>（或创建自定义 Token）</li>
          <li>自定义 Token 需添加权限：<code>Account · Cloudflare Tunnel · Edit</code> 和 <code>Zone · DNS · Edit</code></li>
          <li>复制生成的 Token 粘贴到下方</li>
        </ol>
      </el-alert>

      <el-form label-width="110px">
        <el-form-item label="API Token" required>
          <el-input v-model="apiToken" placeholder="粘贴 Cloudflare API Token" type="password" show-password size="large" />
        </el-form-item>
        <el-form-item label="域名">
          <el-input :model-value="domain" disabled size="large" />
          <div class="form-help">域名需托管在 Cloudflare（已在 Cloudflare 添加站点并修改 NS 记录）</div>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" size="large" :loading="verifying" @click="handleVerify">验证 Token</el-button>
          <el-button type="success" size="large" :loading="settingUp" :disabled="!verified" @click="handleSetup">
            一键接入
          </el-button>
        </el-form-item>

        <!-- 高级选项：手动指定 Account ID -->
        <el-collapse style="margin-bottom: 16px">
          <el-collapse-item title="高级选项（手动指定 Account ID，可选）">
            <el-input v-model="accountId" placeholder="如自动获取失败，粘贴 Account ID（Cloudflare 首页 URL 中 /dash/ 后的 ID）" />
            <div class="form-help">Account ID 查看方法：登录 Cloudflare Dashboard，首页 URL 形如 dash.cloudflare.com/&#123;Account ID&#125;，或点击右上角账户头像查看</div>
          </el-collapse-item>
        </el-collapse>
      </el-form>

      <!-- 验证结果 -->
      <div v-if="verifyResult" class="verify-result">
        <el-result v-if="verifyResult.valid" icon="success" title="Token 有效" sub-title="点击「一键接入」自动创建隧道并发布服务">
          <template #extra>
            <div class="verify-info">
              <div v-if="verifyResult.accounts?.length">账户：{{ verifyResult.accounts.map(a => a.name).join('、') }}</div>
              <div v-else-if="verifyResult.account_name">账户：{{ verifyResult.account_name }}（已自动识别）</div>
              <div>域名：{{ verifyResult.domain }}（{{ verifyResult.zone_found ? '已托管到 Cloudflare ✓' : '未检测到托管，接入后需自行添加站点并改 NS' }}）</div>
              <div v-if="verifyResult.zone_error" style="color:#e6a23c">注意：{{ verifyResult.zone_error }}</div>
              <div v-if="verifyResult.tunnel_permission === 'missing'" style="color:#e6a23c">
                注意：Token 缺少隧道管理权限，创建隧道可能失败，请在 Token 权限中添加 Account · Cloudflare Tunnel · Edit
              </div>
            </div>
          </template>
        </el-result>
        <el-alert v-else type="error" :closable="false" :title="'Token 无效：' + (verifyResult.error || '未知错误')" />
      </div>

      <!-- 接入日志 -->
      <div v-if="setupLogs.length" class="setup-logs">
        <div v-for="(log, i) in setupLogs" :key="i" class="log-line">
          <el-tag :type="log.ok ? 'success' : 'danger'" size="small">{{ log.ok ? '✓' : '✗' }}</el-tag>
          <span>{{ log.msg }}</span>
        </div>
        <el-alert v-if="setupDone" type="success" :closable="false" title="接入完成！" style="margin-top: 12px" />
        <el-alert v-if="setupWarning" type="warning" :closable="false" :title="setupWarning" style="margin-top: 12px" />
      </div>
    </el-card>

    <!-- 已接入：状态与路由管理 -->
    <template v-if="status.configured">
      <!-- 状态概览 -->
      <el-card style="max-width: 720px; width: 100%">
        <template #header>
          <div class="card-header-row">
            <span style="font-weight:600">隧道状态</span>
            <el-tag :type="status.connected ? 'success' : 'danger'" size="small">
              {{ status.connected ? '已连接' : '未连接' }}
            </el-tag>
          </div>
        </template>
        <el-descriptions :column="2" border>
          <el-descriptions-item label="隧道名称">{{ status.tunnel_name }}</el-descriptions-item>
          <el-descriptions-item label="隧道 ID">{{ status.tunnel_id }}</el-descriptions-item>
          <el-descriptions-item label="API Token">{{ status.api_token_masked }}</el-descriptions-item>
          <el-descriptions-item label="主域名">{{ status.domain }}</el-descriptions-item>
        </el-descriptions>
        <div v-if="status.error" class="form-help" style="color:#e6a23c; margin-top: 8px">
          状态查询提示：{{ status.error }}
        </div>
        <div style="margin-top: 12px">
          <el-button size="small" @click="loadStatus">刷新状态</el-button>
        </div>
      </el-card>

      <!-- 已发布路由 -->
      <el-card style="max-width: 720px; width: 100%; margin-top: 20px">
        <template #header><span style="font-weight:600">已发布路由</span></template>
        <el-empty v-if="!status.routes?.length" description="暂无已发布的服务" :image-size="60" />
        <div v-for="r in status.routes" :key="r.hostname" class="route-row">
          <div class="route-info">
            <a :href="'https://' + r.hostname" target="_blank" style="color:#409eff; font-weight:600">
              https://{{ r.hostname }}
            </a>
            <span class="route-service">{{ r.service }}</span>
          </div>
          <el-button type="danger" size="small" @click="unpublishRoute(r.hostname)">取消发布</el-button>
        </div>
      </el-card>

      <!-- 服务发布 -->
      <el-card style="max-width: 720px; width: 100%; margin-top: 20px">
        <template #header><span style="font-weight:600">发布服务</span></template>
        <el-table :data="status.services" size="small" empty-text="暂无可以发布的服务">
          <el-table-column prop="name" label="服务" min-width="140" />
          <el-table-column prop="hostname" label="访问地址" min-width="160">
            <template #default="{ row }">
              <span v-if="row.hostname">{{ row.hostname }}</span>
              <span v-else style="color:#909399">未配置域名</span>
            </template>
          </el-table-column>
          <el-table-column prop="port" label="端口" width="70" />
          <el-table-column label="操作" width="110">
            <template #default="{ row }">
              <el-button v-if="row.published" type="success" size="small" disabled>已发布</el-button>
              <el-button v-else type="primary" size="small" :loading="publishingId === row.module" @click="publishService(row)">
                发布
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="form-help" style="margin-top: 8px">
          发布后自动创建路由和 DNS 记录，通过 https://子域名.域名 访问（免端口号）
        </div>
      </el-card>
    </template>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api'

const status = ref({ configured: false })
const domain = ref('')
const apiToken = ref('')
const accountId = ref('')
const verifying = ref(false)
const settingUp = ref(false)
const verified = ref(false)
const verifyResult = ref(null)
const setupStep = ref(0)
const setupLogs = ref([])
const setupDone = ref(false)
const setupWarning = ref('')
const publishingId = ref('')

const loadStatus = async () => {
  try {
    const { data } = await api.get('/cloudflare/status')
    status.value = data
    if (!domain.value) domain.value = data.domain || ''
  } catch (e) {
    ElMessage.error('加载状态失败: ' + (e.response?.data?.detail || e.message))
  }
}

const loadDomain = async () => {
  try {
    const { data } = await api.get('/config')
    const cfg = data.config || {}
    const env = data.env_summary || {}
    domain.value = env.DOMAIN || cfg.domain || ''
  } catch (e) { /* 忽略 */ }
}

const handleVerify = async () => {
  if (!apiToken.value) { ElMessage.warning('请先粘贴 API Token'); return }
  verifying.value = true
  verifyResult.value = null
  try {
    const { data } = await api.post('/cloudflare/verify', { api_token: apiToken.value })
    verifyResult.value = data
    if (data.valid) { verified.value = true; setupStep.value = 1 } else { verified.value = false }
    // 自动填充识别到的 Account ID（用户手动填写的优先）
    if (data.account_id && !accountId.value) {
      accountId.value = data.account_id
    }
  } catch (e) {
    verifyResult.value = { valid: false, error: e.response?.data?.detail || e.message }
    verified.value = false
  }
  verifying.value = false
}

const addLog = (msg, ok = true) => setupLogs.value.push({ msg, ok })

const handleSetup = async () => {
  if (!apiToken.value) return
  settingUp.value = true
  setupLogs.value = []
  setupDone.value = false
  setupWarning.value = ''
  setupStep.value = 2
  try {
    addLog('正在创建/复用隧道...')
    const payload = { api_token: apiToken.value }
    if (accountId.value) payload.account_id = accountId.value
    const { data } = await api.post('/cloudflare/setup', payload)
    addLog(`隧道就绪：${data.tunnel_name} (${data.tunnel_id})`)
    if (data.zone_warning) {
      setupWarning.value = data.zone_warning
      addLog(data.zone_warning, false)
    }
    const failed = (data.results || []).filter(r => !r.success)
    if (failed.length) {
      addLog('容器启动失败: ' + (failed[0].error || '未知错误'), false)
    } else {
      addLog('cloudflare-tunnel 容器已启动')
    }
    setupDone.value = true
    setupStep.value = 3
    setTimeout(() => loadStatus(), 3000)
    ElMessage.success('接入完成！请等待隧道连接后发布服务')
  } catch (e) {
    addLog('接入失败: ' + (e.response?.data?.detail || e.message), false)
    setupDone.value = false
  }
  settingUp.value = false
}

const publishService = async (row) => {
  publishingId.value = row.module
  try {
    const { data } = await api.post('/cloudflare/publish', {
      subdomain: row.subdomain,
      port: row.port
    })
    ElMessage.success(data.message || '发布成功')
    if (data.dns_warning) ElMessage.warning(data.dns_warning)
    loadStatus()
  } catch (e) {
    ElMessage.error('发布失败: ' + (e.response?.data?.detail || e.message))
  }
  publishingId.value = ''
}

const unpublishRoute = async (hostname) => {
  try {
    await ElMessageBox.confirm(`确定取消发布 ${hostname}？`, '确认操作')
  } catch { return }
  try {
    const { data } = await api.post('/cloudflare/unpublish', { hostname })
    ElMessage.success(`已取消发布 ${hostname}`)
    if (data.warnings?.length) data.warnings.forEach(w => ElMessage.warning(w))
    loadStatus()
  } catch (e) {
    ElMessage.error('操作失败: ' + (e.response?.data?.detail || e.message))
  }
}

onMounted(() => {
  loadDomain()
  loadStatus()
})
</script>

<style scoped>
.tunnel-page { max-width: 760px; }
.page-desc { color: #909399; margin: 8px 0 20px; }
.form-help { font-size: 12px; color: #909399; margin-top: 4px; line-height: 1.5; }
.form-help a { color: #409eff; text-decoration: none; }
.card-header-row { display: flex; justify-content: space-between; align-items: center; }
.verify-result { margin-top: 8px; }
.verify-info { font-size: 13px; color: #606266; line-height: 1.8; text-align: left; display: inline-block; }
.setup-logs { margin-top: 16px; }
.log-line { display: flex; align-items: center; gap: 8px; padding: 4px 0; font-size: 13px; }
.route-row {
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 0; border-bottom: 1px solid #f0f2f5;
}
.route-info { display: flex; flex-direction: column; gap: 2px; }
.route-service { font-size: 12px; color: #909399; }
</style>
