<template>
  <div class="login-page">
    <el-card class="login-card">
      <div class="login-header">
        <h2>EasyServer</h2>
        <p class="login-subtitle">个人服务器管理面板</p>
      </div>
      <el-form @submit.prevent="doLogin">
        <el-form-item>
          <el-input
            v-model="password"
            type="password"
            show-password
            placeholder="请输入管理密码"
            size="large"
            @keyup.enter="doLogin"
            ref="pwdInput"
          />
        </el-form-item>
        <el-form-item>
          <el-button
            type="primary"
            :loading="loading"
            @click="doLogin"
            size="large"
            style="width: 100%"
          >
            登 录
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import api from '../api'

const router = useRouter()
const password = ref('')
const loading = ref(false)
const pwdInput = ref(null)

const doLogin = async () => {
  if (!password.value) {
    ElMessage.warning('请输入密码')
    return
  }
  loading.value = true
  try {
    const { data } = await api.post('/config/auth/login', { password: password.value })
    if (data.token) {
      localStorage.setItem('easyserver_token', data.token)
      ElMessage.success('登录成功')
      router.push('/dashboard')
    }
  } catch (e) {
    const msg = e.response?.data?.detail || '登录失败，请检查密码'
    ElMessage.error(msg)
  }
  loading.value = false
}

onMounted(() => {
  nextTick(() => {
    pwdInput.value?.focus()
  })
})
</script>

<style scoped>
.login-page {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}

.login-card {
  max-width: 400px;
  width: 100%;
  padding: 20px;
}

.login-header {
  text-align: center;
  margin-bottom: 32px;
}

.login-header h2 {
  margin: 0 0 8px;
  font-size: 28px;
  color: #303133;
}

.login-subtitle {
  color: #909399;
  font-size: 14px;
  margin: 0;
}
</style>
