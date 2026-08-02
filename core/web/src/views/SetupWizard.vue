<template>
  <div class="setup-wizard">
    <el-card class="wizard-card">
      <h2 style="text-align: center; margin-bottom: 8px">EasyServer 初始设置</h2>
      <p class="wizard-subtitle">只需 2 步，快速搭建你的个人服务器</p>

      <el-steps :active="step" align-center style="margin-bottom: 32px">
        <el-step title="基础信息" />
        <el-step title="管理员密码" />
      </el-steps>

      <!-- Step 0: 域名与邮箱 -->
      <div v-if="step === 0" class="step-content">
        <el-form label-width="100px">
          <el-form-item label="主域名" required>
            <el-input v-model="config.domain" placeholder="example.com" size="large" />
            <div class="form-help">你的服务器将使用此域名访问，如 panel.example.com</div>
          </el-form-item>
          <el-form-item label="SSL 邮箱" required>
            <el-input v-model="config.ssl_email" placeholder="admin@example.com" size="large" />
            <div class="form-help">用于申请 SSL 证书，Let's Encrypt 会发送验证邮件到此邮箱</div>
          </el-form-item>
        </el-form>
        <el-alert type="info" :closable="false" style="margin-top: 24px">
          <template #title>
            <strong>核心服务将自动安装</strong>
          </template>
          <div style="margin-top: 8px; font-size: 13px; color: #666">
            系统将自动安装 Nginx 反向代理、SSL 证书、动态域名解析等核心服务。<br/>
            网络访问配置可在进入管理面板后完成。
          </div>
        </el-alert>
      </div>

      <!-- Step 1: 管理密码 + 部署 -->
      <div v-if="step === 1" class="step-content">
        <el-form label-width="120px">
          <el-form-item label="管理密码" required>
            <el-input v-model="config.admin_password" type="password" show-password placeholder="设置管理面板密码（至少 8 位）" size="large" />
            <div class="form-help">用于登录 EasyServer 管理面板</div>
          </el-form-item>
          <el-form-item>
            <el-button @click="generatePassword" :loading="generatingPwd">生成随机密码</el-button>
          </el-form-item>
        </el-form>

        <!-- 部署状态 -->
        <div v-if="deploying || deployed" class="deploy-section">
          <div v-if="deploying" class="deploy-status">
            <el-icon class="is-loading" :size="48" color="#409EFF"><Loading /></el-icon>
            <h3>正在部署核心服务...</h3>
            <p class="deploy-hint">将安装 Nginx、SSL 证书、动态域名解析</p>
            <div class="deploy-log">
              <div v-for="(log, i) in deployLogs" :key="i" class="log-line">
                <span class="log-time">{{ log.time }}</span>
                <span :class="log.type">{{ log.message }}</span>
              </div>
            </div>
          </div>
          <div v-else-if="deployed" class="deploy-status">
            <el-icon :size="48" color="#67C23A"><SuccessFilled /></el-icon>
            <h3>部署完成！</h3>
            <p class="deploy-hint">核心服务已安装，请在管理面板中配置网络访问</p>
            <div class="deploy-summary">
              <el-tag type="success" size="large">Nginx 反向代理</el-tag>
              <el-tag type="success" size="large">SSL 证书管理</el-tag>
              <el-tag type="success" size="large">动态域名解析</el-tag>
            </div>
            <el-button type="primary" size="large" @click="goToLogin" style="margin-top: 24px">
              登录管理面板
            </el-button>
          </div>
        </div>
      </div>

      <!-- 底部按钮 -->
      <div class="wizard-footer" v-if="!deploying && !deployed">
        <el-button @click="step--" :disabled="step === 0" size="large">上一步</el-button>
        <el-button v-if="step === 0" type="primary" @click="step++" :disabled="!config.domain || !config.ssl_email" size="large">下一步</el-button>
        <el-button v-if="step === 1" type="success" @click="startDeploy" :disabled="config.admin_password.length < 8" :loading="deploying" size="large">
          开始部署
        </el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Loading, SuccessFilled } from '@element-plus/icons-vue'
import api from '../api'

const router = useRouter()
const step = ref(0)
const deploying = ref(false)
const deployed = ref(false)
const generatingPwd = ref(false)
const deployLogs = ref([])

const config = ref({
  domain: '',
  ssl_email: '',
  admin_password: ''
})

const generatePassword = async () => {
  generatingPwd.value = true
  try {
    const { data } = await api.post('/config/generate-password')
    config.value.admin_password = data.password
    ElMessage.success('密码已生成')
  } catch (e) {
    config.value.admin_password = Math.random().toString(36).slice(-16)
  }
  generatingPwd.value = false
}

const addLog = (message, type = 'info') => {
  const now = new Date()
  const time = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}:${now.getSeconds().toString().padStart(2, '0')}`
  deployLogs.value.push({ time, message, type })
}

const startDeploy = async () => {
  deploying.value = true
  deployLogs.value = []

  addLog('正在保存配置...', 'info')
  try {
    const { data } = await api.post('/config/setup', {
      domain: config.value.domain,
      ssl_email: config.value.ssl_email,
      admin_password: config.value.admin_password
    })

    addLog('配置已保存', 'success')

    if (data.install_results) {
      for (const result of data.install_results) {
        if (result.success) {
          addLog(`${result.module} 安装成功`, 'success')
        } else {
          addLog(`${result.module} 安装失败: ${result.error}`, 'error')
        }
      }
    }

    addLog('部署完成！', 'success')
    deployed.value = true
  } catch (e) {
    addLog(`部署失败: ${e.response?.data?.detail || e.message}`, 'error')
    deploying.value = false
  }
}

const goToLogin = () => {
  router.push('/login')
}
</script>

<style scoped>
.setup-wizard {
  display: flex;
  justify-content: center;
  padding: 40px 20px;
  min-height: calc(100vh - 60px);
}

.wizard-card {
  max-width: 640px;
  width: 100%;
  height: fit-content;
}

.wizard-subtitle {
  text-align: center;
  color: #909399;
  margin-bottom: 32px;
  font-size: 14px;
}

.step-content {
  min-height: 260px;
  padding: 20px 0;
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

.deploy-section {
  margin-top: 32px;
  padding: 24px;
  background: #f5f7fa;
  border-radius: 8px;
}

.deploy-status {
  text-align: center;
}

.deploy-status h3 {
  margin: 16px 0 8px;
  color: #303133;
}

.deploy-hint {
  color: #909399;
  font-size: 14px;
  margin-bottom: 16px;
}

.deploy-log {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 16px;
  border-radius: 6px;
  text-align: left;
  font-family: 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.6;
  max-height: 240px;
  overflow-y: auto;
  margin-top: 16px;
}

.log-line {
  display: flex;
  gap: 12px;
}

.log-time {
  color: #909399;
  flex-shrink: 0;
}

.log-line .success { color: #67c23a; }
.log-line .error { color: #f56c6c; }
.log-line .info { color: #d4d4d4; }

.deploy-summary {
  display: flex;
  gap: 12px;
  justify-content: center;
  flex-wrap: wrap;
  margin-top: 20px;
}

.wizard-footer {
  margin-top: 32px;
  display: flex;
  justify-content: center;
  gap: 16px;
  padding-top: 24px;
  border-top: 1px solid #ebeef5;
}
</style>
