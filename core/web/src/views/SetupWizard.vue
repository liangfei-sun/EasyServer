<template>
  <div class="setup-wizard">
    <el-card class="wizard-card">
      <h2>EasyServer 初始设置</h2>
      <el-steps :active="step" align-center style="margin-bottom: 30px">
        <el-step title="域名" />
        <el-step title="访问模式" />
        <el-step title="选择服务" />
        <el-step title="设置密码" />
        <el-step title="部署" />
      </el-steps>

      <!-- Step 0: 域名 -->
      <div v-if="step === 0">
        <el-form label-width="100px">
          <el-form-item label="域名">
            <el-input v-model="config.domain" placeholder="example.com" />
          </el-form-item>
          <el-form-item label="SSL 邮箱">
            <el-input v-model="config.ssl_email" placeholder="admin@example.com" />
          </el-form-item>
        </el-form>
      </div>

      <!-- Step 1: 访问模式 -->
      <div v-if="step === 1">
        <el-radio-group v-model="config.access_mode" style="display: flex; flex-direction: column; gap: 16px">
          <el-radio label="domain">
            <strong>域名反代 (推荐)</strong>
            <p style="color: #999; margin: 4px 0 0 24px">通过 Nginx 反向代理 + SSL 证书访问</p>
          </el-radio>
          <el-radio label="ipv6_direct">
            <strong>IPv6 直连</strong>
            <p style="color: #999; margin: 4px 0 0 24px">服务端口直接暴露在公网</p>
          </el-radio>
          <el-radio label="hybrid">
            <strong>混合模式</strong>
            <p style="color: #999; margin: 4px 0 0 24px">同时支持域名反代和 IPv6 直连</p>
          </el-radio>
        </el-radio-group>
      </div>

      <!-- Step 2: 选择服务 -->
      <div v-if="step === 2">
        <el-checkbox-group v-model="config.selected_services">
          <div v-for="mod in availableModules" :key="mod.id" class="module-checkbox">
            <el-checkbox :label="mod.id">
              <strong>{{ mod.name }}</strong>
              <span style="color: #999; margin-left: 8px">{{ mod.description }}</span>
            </el-checkbox>
          </div>
        </el-checkbox-group>
      </div>

      <!-- Step 3: 设置密码 -->
      <div v-if="step === 3">
        <el-form label-width="120px">
          <el-form-item label="管理密码">
            <el-input v-model="config.admin_password" type="password" show-password placeholder="设置管理面板密码" />
          </el-form-item>
          <el-form-item>
            <el-button @click="generatePassword">生成随机密码</el-button>
          </el-form-item>
        </el-form>
      </div>

      <!-- Step 4: 部署 -->
      <div v-if="step === 4">
        <div v-if="deploying" class="deploy-status">
          <el-icon class="is-loading" :size="40"><Loading /></el-icon>
          <p>正在部署，请稍候...</p>
          <div class="deploy-log">{{ deployLog }}</div>
        </div>
        <div v-else-if="deployed" class="deploy-status">
          <el-icon :size="40" color="#67C23A"><SuccessFilled /></el-icon>
          <p>部署完成！</p>
          <el-button type="primary" @click="$router.push('/dashboard')">进入管理面板</el-button>
        </div>
      </div>

      <div class="wizard-footer" v-if="step < 4">
        <el-button @click="step--" :disabled="step === 0">上一步</el-button>
        <el-button type="primary" @click="nextStep" :disabled="!canNext">下一步</el-button>
      </div>
      <div class="wizard-footer" v-if="step === 4 && !deployed && !deploying">
        <el-button type="success" @click="startDeploy">开始部署</el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Loading, SuccessFilled } from '@element-plus/icons-vue'
import api from '../api'

const router = useRouter()
const step = ref(0)
const availableModules = ref([])
const deploying = ref(false)
const deployed = ref(false)
const deployLog = ref('')

const config = ref({
  domain: '', ssl_email: '', access_mode: 'domain',
  selected_services: ['nginx'], admin_password: ''
})

const canNext = computed(() => {
  if (step.value === 0) return config.value.domain && config.value.ssl_email
  if (step.value === 1) return !!config.value.access_mode
  if (step.value === 2) return config.value.selected_services.length > 0
  if (step.value === 3) return config.value.admin_password.length >= 8
  return true
})

const nextStep = () => { step.value++ }

const loadModules = async () => {
  try {
    const { data } = await api.get('/modules')
    const allModules = []
    for (const cat of (data.categories || [])) {
      for (const mod of (cat.modules || [])) {
        allModules.push({ ...mod, category: cat.id })
      }
    }
    availableModules.value = allModules.filter(m => m.id !== 'nginx')
  } catch (e) {}
}

const generatePassword = async () => {
  try {
    const { data } = await api.post('/config/generate-password')
    config.value.admin_password = data.password
  } catch (e) {
    config.value.admin_password = Math.random().toString(36).slice(-16)
  }
}

const startDeploy = async () => {
  deploying.value = true
  deployLog.value = '正在保存配置...\n'
  try {
    await api.put('/config', {
      domain: config.value.domain,
      access_mode: config.value.access_mode,
      ssl_email: config.value.ssl_email
    })
    deployLog.value += '配置已保存\n'
    for (const svcId of config.value.selected_services) {
      deployLog.value += `安装 ${svcId}...\n`
      await api.post('/modules/install', { module_id: svcId, config: {} })
      deployLog.value += `${svcId} 安装完成\n`
    }
    deployLog.value += '生成 Nginx 配置...\n'
    await api.post('/nginx/generate')
    await api.post('/config/setup/complete')
    deployLog.value += '部署完成！\n'
    deployed.value = true
  } catch (e) {
    deployLog.value += `错误: ${e.response?.data?.detail || e.message}\n`
    deploying.value = false
  }
}

onMounted(loadModules)
</script>

<style scoped>
.setup-wizard { display: flex; justify-content: center; padding: 40px 20px; }
.wizard-card { max-width: 700px; width: 100%; }
.module-checkbox { padding: 8px 0; border-bottom: 1px solid #f0f0f0; }
.wizard-footer { margin-top: 24px; display: flex; justify-content: center; gap: 12px; }
.deploy-status { text-align: center; padding: 20px; }
.deploy-log { background: #1e1e1e; color: #d4d4d4; padding: 16px; border-radius: 6px; margin-top: 16px; text-align: left; font-size: 12px; line-height: 1.6; max-height: 200px; overflow: auto; white-space: pre-wrap; }
</style>
