<template>
  <div class="settings-page">
    <h2>全局设置</h2>
    <el-card style="max-width: 600px">
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
        <el-form-item>
          <el-button type="primary" @click="saveConfig" :loading="saving">保存配置</el-button>
          <el-button @click="generateNginx" :loading="generating">重新生成 Nginx 配置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card style="max-width: 600px; margin-top: 20px">
      <template #header><span>SSL 证书状态</span></template>
      <div class="ssl-status">
        <el-tag :type="sslValid ? 'success' : 'warning'">{{ sslValid ? '有效' : '未配置' }}</el-tag>
        <span v-if="sslExpiry" style="margin-left: 12px; color: #666">到期: {{ sslExpiry }}</span>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api'

const form = ref({ domain: '', access_mode: 'domain', https_port: 8443, ssl_email: '', dns_provider: '' })
const saving = ref(false)
const generating = ref(false)
const sslValid = ref(false)
const sslExpiry = ref('')

const loadConfig = async () => {
  try {
    const { data } = await api.get('/api/config')
    const cfg = data.config || {}
    const env = data.env_summary || {}
    form.value.domain = env.DOMAIN || cfg.domain || ''
    form.value.access_mode = env.ACCESS_MODE || cfg.access_mode || 'domain'
    form.value.https_port = parseInt(env.HTTPS_PORT) || cfg.https_port || 8443
    form.value.ssl_email = cfg.ssl_email || ''
    form.value.dns_provider = cfg.dns_provider || ''
  } catch (e) { ElMessage.error('加载配置失败') }
}

const saveConfig = async () => {
  saving.value = true
  try {
    await api.put('/api/config', form.value)
    ElMessage.success('配置已保存')
  } catch (e) { ElMessage.error('保存失败') }
  saving.value = false
}

const generateNginx = async () => {
  generating.value = true
  try {
    await api.post('/api/nginx/generate')
    ElMessage.success('Nginx 配置已重新生成')
  } catch (e) { ElMessage.error('生成失败') }
  generating.value = false
}

onMounted(loadConfig)
</script>

<style scoped>
.ssl-status { display: flex; align-items: center; }
</style>
