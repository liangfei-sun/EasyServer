<template>
  <div class="network-guide">
    <el-card class="guide-card">
      <h2 style="text-align: center; margin-bottom: 8px">网络配置引导</h2>
      <p class="guide-subtitle">选择你的服务器访问方式，系统将自动配置对应服务</p>

      <!-- 方案选择 -->
      <div v-if="!configuring && !configured" class="scheme-list">
        <div
          v-for="scheme in schemes"
          :key="scheme.key"
          class="scheme-card"
          :class="{ selected: selectedScheme === scheme.key }"
          @click="selectScheme(scheme)"
        >
          <div class="scheme-header">
            <span class="scheme-name">{{ scheme.name }}</span>
            <el-tag v-if="scheme.recommended" type="success" size="small">推荐</el-tag>
          </div>
          <div class="scheme-desc">{{ scheme.description }}</div>
          <div class="scheme-tags">
            <el-tag v-for="tag in scheme.tags" :key="tag" size="small" type="info">{{ tag }}</el-tag>
          </div>
          <div class="scheme-suit" v-if="scheme.suitable">
            适用: {{ scheme.suitable }}
          </div>
        </div>
      </div>

      <!-- 配置表单 -->
      <div v-if="configuring && !configured" class="config-form">
        <el-page-header @back="configuring = false" title="返回选择" style="margin-bottom: 24px" />

        <el-form label-width="130px">
          <!-- 域名反代（阿里云） -->
          <template v-if="selectedScheme === 'domain_aliyun'">
            <el-form-item label="DNS 提供商">
              <el-tag type="info">阿里云</el-tag>
            </el-form-item>
            <el-form-item label="AccessKey ID" required>
              <el-input v-model="formData.ali_key" placeholder="LTAI5t..." type="password" show-password size="large" />
              <div class="form-help">
                <a href="https://ram.console.aliyun.com/manage/ak" target="_blank">前往创建</a>
                ，需授予 AliyunDNSFullAccess 权限
              </div>
            </el-form-item>
            <el-form-item label="AccessKey Secret" required>
              <el-input v-model="formData.ali_secret" placeholder="AccessKey Secret" type="password" show-password size="large" />
            </el-form-item>
          </template>

          <!-- 域名反代（Cloudflare） -->
          <template v-if="selectedScheme === 'domain_cf'">
            <el-form-item label="DNS 提供商">
              <el-tag type="info">Cloudflare</el-tag>
            </el-form-item>
            <el-form-item label="API Token" required>
              <el-input v-model="formData.cf_token" placeholder="Cloudflare API Token" type="password" show-password size="large" />
              <div class="form-help">
                <a href="https://dash.cloudflare.com/profile/api-tokens" target="_blank">前往创建</a>
                ，权限选择 Zone > DNS > Edit
              </div>
            </el-form-item>
          </template>

          <!-- Cloudflare Tunnel -->
          <template v-if="selectedScheme === 'cloudflare_tunnel'">
            <el-form-item label="Tunnel Token" required>
              <el-input v-model="formData.cf_tunnel_token" placeholder="Cloudflare Tunnel Token" type="password" show-password size="large" />
              <div class="form-help">
                在 Cloudflare Zero Trust 面板创建 Tunnel 后获取 Token
              </div>
            </el-form-item>
          </template>

          <!-- IPv6 直连 无需额外配置 -->
          <template v-if="selectedScheme === 'ipv6_direct'">
            <el-alert type="info" :closable="false">
              IPv6 直连模式无需额外配置，服务端口将直接暴露在公网。
              请确保你的服务器有固定 IPv6 地址，并在路由器中放行对应端口。
            </el-alert>
          </template>

          <el-form-item label="HTTPS 端口">
            <el-input-number v-model="formData.https_port" :min="1" :max="65535" size="large" />
            <div class="form-help">国内运营商通常封锁 443 端口，建议使用 8443</div>
          </el-form-item>
        </el-form>

        <el-alert type="info" :closable="false" style="margin-top: 8px">
          确认配置后将自动安装对应网络模块：域名反代 → Nginx / SSL / DDNS，隧道 → Cloudflare Tunnel。
          若已安装则直接启动。
        </el-alert>

        <div class="form-actions">
          <el-button @click="configuring = false">返回</el-button>
          <el-button type="primary" @click="applyConfig" :loading="applying" :disabled="!canApply">
            确认配置
          </el-button>
        </div>
      </div>

      <!-- 配置完成 -->
      <div v-if="configured" class="config-done">
        <el-icon :size="64" color="#67C23A"><SuccessFilled /></el-icon>
        <h3>网络配置完成！</h3>
        <p class="guide-subtitle">{{ appliedSchemeName }} 已启用</p>
        <div v-if="applyResults.length" class="apply-log">
          <div v-for="(r, i) in applyResults" :key="i" class="log-line">
            <el-tag :type="r.success ? 'success' : 'danger'" size="small">
              {{ r.success ? '✓' : '✗' }}
            </el-tag>
            <span>{{ r.module }} {{ r.action === 'start' ? '已启动' : '已停止' }}</span>
          </div>
        </div>
        <el-button type="primary" size="large" @click="$router.push('/dashboard')" style="margin-top: 24px">
          进入管理面板
        </el-button>
      </div>

      <!-- 底部跳过 -->
      <div class="guide-footer" v-if="!configuring && !configured">
        <el-button type="primary" size="large" @click="selectScheme(schemes[0])" style="min-width: 200px">
          使用推荐方案
        </el-button>
        <el-button size="large" @click="$router.push('/settings')">
          跳过，稍后自行配置
        </el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { SuccessFilled } from '@element-plus/icons-vue'
import api from '../api'

const router = useRouter()
const selectedScheme = ref('')
const configuring = ref(false)
const configured = ref(false)
const applying = ref(false)
const appliedSchemeName = ref('')
const applyResults = ref([])

const formData = ref({
  ali_key: '',
  ali_secret: '',
  cf_token: '',
  cf_tunnel_token: '',
  https_port: 8443
})

const schemes = [
  {
    key: 'domain_aliyun',
    name: '域名反代（阿里云）',
    description: '通过 Nginx 反向代理 + SSL 证书访问，使用阿里云 DNS 自动解析',
    recommended: true,
    tags: ['Nginx', 'SSL', 'DDNS'],
    suitable: '域名在阿里云解析的用户'
  },
  {
    key: 'domain_cf',
    name: '域名反代（Cloudflare）',
    description: '通过 Nginx 反向代理 + SSL 证书访问，使用 Cloudflare DNS 自动解析',
    recommended: false,
    tags: ['Nginx', 'SSL', 'DDNS'],
    suitable: '域名在 Cloudflare 解析的用户'
  },
  {
    key: 'cloudflare_tunnel',
    name: 'Cloudflare Tunnel',
    description: '无需公网 IP，通过 Cloudflare Tunnel 穿透访问，自带 SSL 和反代',
    recommended: false,
    tags: ['无需公网IP', 'SSL', 'Tunnel'],
    suitable: '无公网 IP 或不想开放端口的用户'
  },
  {
    key: 'ipv6_direct',
    name: 'IPv6 直连',
    description: '服务端口直接暴露在公网，适合有固定 IPv6 地址的用户',
    recommended: false,
    tags: ['IPv6', '直连'],
    suitable: '有固定 IPv6 地址的用户'
  }
]

const canApply = computed(() => {
  if (selectedScheme.value === 'domain_aliyun') {
    return formData.value.ali_key && formData.value.ali_secret
  }
  if (selectedScheme.value === 'domain_cf') {
    return formData.value.cf_token
  }
  if (selectedScheme.value === 'cloudflare_tunnel') {
    return formData.value.cf_tunnel_token
  }
  return true
})

const selectScheme = (scheme) => {
  selectedScheme.value = scheme.key
  configuring.value = true
}

const applyConfig = async () => {
  applying.value = true
  applyResults.value = []

  const accessModeMap = {
    'domain_aliyun': 'domain',
    'domain_cf': 'domain',
    'cloudflare_tunnel': 'cloudflare_tunnel',
    'ipv6_direct': 'ipv6_direct'
  }

  const dnsProviderMap = {
    'domain_aliyun': 'aliyun',
    'domain_cf': 'cloudflare'
  }

  const payload = {
    access_mode: accessModeMap[selectedScheme.value],
    https_port: formData.value.https_port
  }

  if (dnsProviderMap[selectedScheme.value]) {
    payload.dns_provider = dnsProviderMap[selectedScheme.value]
  }

  if (selectedScheme.value === 'domain_aliyun') {
    payload.dns_credentials = {
      aliyun: { key: formData.value.ali_key, secret: formData.value.ali_secret }
    }
  } else if (selectedScheme.value === 'domain_cf') {
    payload.dns_credentials = {
      cloudflare: { token: formData.value.cf_token }
    }
  } else if (selectedScheme.value === 'cloudflare_tunnel') {
    payload.cf_tunnel_token = formData.value.cf_tunnel_token
  }

  try {
    const { data } = await api.post('/config/network', payload)
    applyResults.value = data.results || []
    appliedSchemeName.value = schemes.find(s => s.key === selectedScheme.value)?.name || ''
    configured.value = true
  } catch (e) {
    ElMessage.error('配置失败: ' + (e.response?.data?.detail || e.message))
  }
  applying.value = false
}
</script>

<style scoped>
.network-guide {
  display: flex;
  justify-content: center;
  padding: 40px 20px;
  min-height: calc(100vh - 60px);
}

.guide-card {
  max-width: 720px;
  width: 100%;
  height: fit-content;
}

.guide-subtitle {
  text-align: center;
  color: #909399;
  margin-bottom: 32px;
  font-size: 14px;
}

.scheme-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.scheme-card {
  padding: 20px;
  border: 2px solid #e4e7ed;
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.3s;
}

.scheme-card:hover {
  border-color: #409eff;
  background: #f5f7fa;
}

.scheme-card.selected {
  border-color: #409eff;
  background: #ecf5ff;
}

.scheme-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.scheme-name {
  font-weight: 600;
  font-size: 16px;
  color: #303133;
}

.scheme-desc {
  color: #666;
  font-size: 13px;
  margin-bottom: 8px;
  line-height: 1.5;
}

.scheme-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}

.scheme-suit {
  font-size: 12px;
  color: #909399;
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

.form-actions {
  margin-top: 32px;
  display: flex;
  justify-content: center;
  gap: 16px;
  padding-top: 24px;
  border-top: 1px solid #ebeef5;
}

.config-done {
  text-align: center;
  padding: 40px 0;
}

.config-done h3 {
  margin: 16px 0 8px;
  color: #303133;
}

.apply-log {
  text-align: left;
  max-width: 400px;
  margin: 20px auto;
}

.log-line {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  font-size: 13px;
}

.guide-footer {
  margin-top: 32px;
  display: flex;
  justify-content: center;
  gap: 16px;
  padding-top: 24px;
  border-top: 1px solid #ebeef5;
}

@media (max-width: 768px) {
  .guide-card { max-width: 100%; }
}
</style>
