<template>
  <div>
    <!-- Tunnel 状态卡片（已配置时显示在 cloudflare_tunnel 模式） -->
    <el-card v-if="showStatusCard" style="max-width: 800px; width: 100%; margin-bottom: 20px">
      <template #header>
        <div class="card-header-row">
          <span style="font-weight:600">隧道状态</span>
          <div style="display:flex;align-items:center;gap:8px">
            <el-tag :type="tunnelStatus.connected ? 'success' : 'danger'" size="small">
              {{ tunnelStatus.connected ? '已连接' : '未连接' }}
            </el-tag>
            <el-button size="small" @click="$emit('refresh-tunnel')">刷新</el-button>
          </div>
        </div>
      </template>
      <el-descriptions :column="isMobile ? 1 : 2" border>
        <el-descriptions-item label="隧道名称">{{ tunnelStatus.tunnel_name }}</el-descriptions-item>
        <el-descriptions-item label="隧道 ID">
          <span style="font-family:monospace;font-size:12px">{{ tunnelStatus.tunnel_id }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="API Token">
          <span style="font-family:monospace;font-size:12px">{{ tunnelStatus.api_token_masked }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="主域名">{{ tunnelStatus.domain }}</el-descriptions-item>
      </el-descriptions>
      <div v-if="tunnelStatus.error" class="form-help" style="color:#e6a23c; margin-top: 8px">
        状态查询提示：{{ tunnelStatus.error }}
      </div>
      <!-- 重新接入折叠 -->
      <el-collapse style="margin-top: 16px">
        <el-collapse-item title="重新接入（更换 Token 或重新配置隧道）">
          <el-form label-width="100px">
            <el-form-item label="API Token">
              <el-input v-model="reconnectToken" placeholder="粘贴新的 Cloudflare API Token" type="password" show-password />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" size="small" :loading="reconnecting" @click="handleReconnect">
                重新接入
              </el-button>
            </el-form-item>
          </el-form>
        </el-collapse-item>
      </el-collapse>
    </el-card>

    <!-- Tunnel 一键接入弹窗 -->
    <el-dialog v-model="dialogVisible" title="Cloudflare Tunnel 一键接入" :width="isMobile ? '95%' : '680px'" top="5vh" :close-on-click-modal="false">
      <el-steps :active="setupStep" align-center finish-status="success" style="margin-bottom: 20px">
        <el-step title="创建 API Token" />
        <el-step title="粘贴并验证" />
        <el-step title="自动接入" />
      </el-steps>
      <el-alert type="info" :closable="false" style="margin-bottom: 16px">
        <p style="margin: 0 0 8px"><b>只需在 Cloudflare 做一次操作</b>：创建一个 API Token，其余全部由 EasyServer 自动完成。</p>
        <ol style="margin: 0; padding-left: 20px; line-height: 1.8">
          <li>打开 <a href="https://dash.cloudflare.com/profile/api-tokens" target="_blank" style="color:#409eff">Cloudflare API Tokens</a></li>
          <li>点击 <b>Create Token</b> → 添加权限：<code>Account · Cloudflare Tunnel · Edit</code> + <code>Zone · DNS · Edit</code></li>
          <li>复制生成的 Token 粘贴到下方</li>
        </ol>
      </el-alert>
      <el-form label-width="100px">
        <el-form-item label="API Token" required>
          <el-input v-model="apiToken" placeholder="粘贴 Cloudflare API Token" type="password" show-password size="large" />
        </el-form-item>
        <el-form-item label="域名">
          <el-input :model-value="domain" disabled size="large" />
        </el-form-item>
        <el-collapse style="margin-bottom: 12px">
          <el-collapse-item title="高级选项（手动指定 Account ID，可选）">
            <el-input v-model="accountId" placeholder="如自动获取失败，粘贴 Account ID" />
          </el-collapse-item>
        </el-collapse>
        <el-form-item>
          <el-button type="primary" size="large" :loading="verifying" @click="handleVerify">验证 Token</el-button>
          <el-button type="success" size="large" :loading="settingUp" :disabled="!verified" @click="handleSetup">一键接入</el-button>
        </el-form-item>
      </el-form>
      <!-- 验证结果 -->
      <div v-if="verifyResult" style="margin-top: 8px">
        <el-result v-if="verifyResult.valid" icon="success" title="Token 有效" sub-title="点击「一键接入」自动创建隧道并发布服务" />
        <el-alert v-else type="error" :closable="false" :title="'Token 无效：' + (verifyResult.error || '未知错误')" />
      </div>
      <!-- 接入日志 -->
      <div v-if="setupLogs.length" style="margin-top: 12px">
        <div v-for="(log, i) in setupLogs" :key="i" class="log-line">
          <el-tag :type="log.ok ? 'success' : 'danger'" size="small">{{ log.ok ? '✓' : '✗' }}</el-tag>
          <span>{{ log.msg }}</span>
        </div>
        <el-alert v-if="setupDone" type="success" :closable="false" title="接入完成！" style="margin-top: 8px" />
        <el-alert v-if="setupWarning" type="warning" :closable="false" :title="setupWarning" style="margin-top: 8px" />
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { useMobile } from '@/composables/useMobile'
import api from '../../api'

const props = defineProps({
  tunnelStatus: { type: Object, required: true },
  domain: { type: String, default: '' },
  showStatusCard: { type: Boolean, default: false },
  modelValue: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'setup-complete', 'refresh-tunnel'])

const { isMobile } = useMobile()

const dialogVisible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

// ===== Tunnel 接入状态 =====
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

// ===== 重新接入 =====
const reconnectToken = ref('')
const reconnecting = ref(false)

const handleVerify = async () => {
  if (!apiToken.value) { ElMessage.warning('请先粘贴 API Token'); return }
  verifying.value = true
  verifyResult.value = null
  try {
    const { data } = await api.post('/cloudflare/verify', { api_token: apiToken.value })
    verifyResult.value = data
    if (data.valid) { verified.value = true; setupStep.value = 1 }
    if (data.account_id && !accountId.value) accountId.value = data.account_id
  } catch (e) {
    verifyResult.value = { valid: false, error: e.response?.data?.detail || e.message }
    verified.value = false
  }
  verifying.value = false
}

const handleSetup = async () => {
  if (!apiToken.value) return
  settingUp.value = true
  setupLogs.value = []
  setupDone.value = false
  setupWarning.value = ''
  setupStep.value = 2
  try {
    setupLogs.value.push({ msg: '正在创建/复用隧道...', ok: true })
    const payload = { api_token: apiToken.value }
    if (accountId.value) payload.account_id = accountId.value
    const { data } = await api.post('/cloudflare/setup', payload)
    setupLogs.value.push({ msg: `隧道就绪：${data.tunnel_name} (${data.tunnel_id})`, ok: true })
    if (data.zone_warning) {
      setupWarning.value = data.zone_warning
      setupLogs.value.push({ msg: data.zone_warning, ok: false })
    }
    const failed = (data.results || []).filter(r => !r.success)
    if (failed.length) {
      setupLogs.value.push({ msg: '容器启动失败: ' + (failed[0].error || '未知错误'), ok: false })
    } else {
      setupLogs.value.push({ msg: 'cloudflare-tunnel 容器已启动', ok: true })
    }
    setupDone.value = true
    setupStep.value = 3
    setTimeout(() => {
      emit('setup-complete')
    }, 3000)
    ElMessage.success('接入完成！请等待隧道连接后发布服务')
  } catch (e) {
    setupLogs.value.push({ msg: '接入失败: ' + (e.response?.data?.detail || e.message), ok: false })
    setupDone.value = false
  }
  settingUp.value = false
}

const handleReconnect = async () => {
  if (!reconnectToken.value) { ElMessage.warning('请输入新的 API Token'); return }
  reconnecting.value = true
  try {
    apiToken.value = reconnectToken.value
    verified.value = false
    setupStep.value = 0
    setupLogs.value = []
    await handleVerify()
    if (verified.value) {
      await handleSetup()
    }
    reconnectToken.value = ''
  } finally {
    reconnecting.value = false
  }
}
</script>

<style scoped>
.card-header-row { display: flex; justify-content: space-between; align-items: center; }
.form-help { font-size: 12px; color: #909399; margin-top: 4px; line-height: 1.5; }
.log-line { display: flex; align-items: center; gap: 8px; padding: 4px 0; font-size: 13px; }
</style>
