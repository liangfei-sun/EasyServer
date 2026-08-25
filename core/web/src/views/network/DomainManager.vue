<template>
  <div>
    <el-card style="max-width: 800px; width: 100%; margin-bottom: 20px" shadow="hover">
      <template #header>
        <div class="card-header-row">
          <span style="font-weight:600">🌐 域名管理</span>
          <el-button type="primary" size="small" @click="showAddDomain = true">
            <el-icon><Plus /></el-icon> 添加域名
          </el-button>
        </div>
      </template>
      <div v-for="(d, idx) in domains" :key="d.domain" class="domain-item">
        <div class="domain-item-row">
          <div>
            <span style="font-weight:500">{{ d.domain }}</span>
            <el-tag :type="d.status === 'active' ? 'success' : d.status === 'warning' ? 'warning' : 'danger'" size="small" style="margin-left: 8px">
              {{ d.status === 'active' ? '✅ 正常' : d.status === 'warning' ? '⚠️ 警告' : '❌ 异常' }}
            </el-tag>
          </div>
          <div class="domain-item-actions">
            <span class="domain-item-meta">
              DNS: {{ dnsProviderLabel(d.dns_provider) }} | 用途: {{ purposeLabel(d.purpose) }}
            </span>
            <el-button size="small" @click="handleVerify(d.domain)" :loading="d.verifying">
              验证
            </el-button>
          </div>
        </div>
        <div v-if="d.checks" class="domain-verify-detail">
          <div v-for="(check, key) in d.checks" :key="key" class="verify-check-item">
            <span :class="check.ok ? 'text-green' : 'text-red'">{{ check.ok ? '✅' : '❌' }}</span>
            <span class="ml-1">{{ check.message }}</span>
          </div>
          <div v-if="d.errors && d.errors.length > 0" class="verify-errors">
            <div v-for="(err, i) in d.errors" :key="i" class="verify-error-item">
              ⚠️ {{ err }}
              <a href="/docs/network-config#troubleshooting" class="text-blue underline ml-1" target="_blank">查看修复指南</a>
            </div>
          </div>
        </div>
        <el-divider v-if="idx < domains.length - 1" />
      </div>
      <div v-if="domains.length === 0" class="domain-empty">暂无域名配置</div>
    </el-card>
    <el-dialog v-model="showAddDomain" title="添加域名" width="500px">
      <el-form :model="newDomainForm" label-width="100px">
        <el-form-item label="域名">
          <el-input v-model="newDomainForm.domain" placeholder="例如：mytunnel.dpdns.org" />
        </el-form-item>
        <el-form-item label="DNS 提供商">
          <el-select v-model="newDomainForm.dns_provider" placeholder="选择 DNS 提供商">
            <el-option v-for="p in dnsProviders" :key="p.id" :label="p.name" :value="p.id" />
            <el-option v-if="!dnsProviders.length" label="阿里云" value="aliyun" />
            <el-option v-if="!dnsProviders.length" label="Cloudflare" value="cloudflare" />
          </el-select>
        </el-form-item>
        <el-form-item label="用途">
          <el-select v-model="newDomainForm.purpose" placeholder="选择用途">
            <el-option label="域名反代（Nginx）" value="nginx" />
            <el-option label="Tunnel 中转" value="tunnel" />
            <el-option label="两者兼用" value="both" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAddDomain = false">取消</el-button>
        <el-button type="primary" @click="handleAddDomain" :loading="addingDomain">添加</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import api from '../../api'

const props = defineProps({
  domains: { type: Array, required: true },
  dnsProviders: { type: Array, default: () => [] },
})
const emit = defineEmits(['refresh'])

const showAddDomain = ref(false)
const addingDomain = ref(false)
const newDomainForm = ref({ domain: '', dns_provider: 'cloudflare', purpose: 'tunnel' })

const dnsProviderLabel = (provider) => {
  const map = { aliyun: '阿里云', cloudflare: 'Cloudflare', dnspod: 'DNSPod' }
  return map[provider] || provider
}
const purposeLabel = (purpose) => {
  const map = { nginx: '域名反代', tunnel: 'Tunnel 中转', both: '反代 + Tunnel' }
  return map[purpose] || purpose
}

const handleVerify = async (domain) => {
  const d = props.domains.find(x => x.domain === domain)
  if (d) d.verifying = true
  try {
    const res = await api.post(`/config/domains/${domain}/verify`)
    const result = res.data
    if (d) { d.status = result.status; d.checks = result.checks; d.errors = result.errors }
    if (result.status === 'active') {
      ElMessage.success(`${domain} 验证通过`)
    } else {
      ElMessage.warning(`${domain} 验证发现问题：${result.errors.join('; ')}`)
    }
  } catch (e) {
    ElMessage.error('验证失败: ' + (e.response?.data?.detail || '未知错误'))
  } finally {
    if (d) d.verifying = false
  }
}

const handleAddDomain = async () => {
  addingDomain.value = true
  try {
    const res = await api.post('/config/domains', newDomainForm.value)
    const verify = res.data.verify
    if (verify && verify.status === 'active') {
      ElMessage.success(`域名 ${newDomainForm.value.domain} 添加成功，验证通过！`)
    } else if (verify) {
      ElMessage.warning(`域名已添加，但验证发现问题：${verify.errors?.join('; ') || '请手动验证'}`)
    } else {
      ElMessage.success('域名添加成功')
    }
    showAddDomain.value = false
    newDomainForm.value = { domain: '', dns_provider: 'cloudflare', purpose: 'tunnel' }
    emit('refresh')
  } catch (e) {
    ElMessage.error('添加失败: ' + (e.response?.data?.detail || '未知错误'))
  } finally {
    addingDomain.value = false
  }
}
</script>

<style scoped>
.card-header-row { display: flex; justify-content: space-between; align-items: center; }
.domain-item { padding: 2px 0; }
.domain-item-row { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }
.domain-item-actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.domain-item-meta { font-size: 12px; color: #909399; }
.domain-empty { text-align: center; padding: 16px 0; color: #c0c4cc; font-size: 14px; }
.domain-verify-detail { margin-top: 8px; padding: 8px 12px; background: #f5f7fa; border-radius: 6px; font-size: 13px; line-height: 1.6; }
.verify-check-item { display: flex; align-items: center; gap: 4px; }
.verify-errors { margin-top: 6px; }
.verify-error-item { color: #f56c6c; font-size: 12px; line-height: 1.6; }
.text-green { color: #67c23a; }
.text-red { color: #f56c6c; }
.text-blue { color: #409eff; }
.ml-1 { margin-left: 4px; }
.underline { text-decoration: underline; }
</style>
