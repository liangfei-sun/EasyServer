<template>
  <el-container style="height: 100vh" v-if="showLayout">
    <!-- 手机端遮罩 -->
    <div v-if="isMobile && sidebarOpen" class="overlay" @click="sidebarOpen = false"></div>
    <!-- 侧边栏 -->
    <el-aside
      :width="isMobile ? '220px' : '220px'"
      :class="{ 'mobile-sidebar': isMobile, 'sidebar-open': sidebarOpen }"
      style="background: #304156"
    >
      <div class="logo" @click="router.push('/dashboard'); isMobile && (sidebarOpen = false)">
        <span>EasyServer</span>
      </div>
      <el-menu
        :default-active="route.path"
        router
        background-color="#304156"
        text-color="#bfcbd9"
        active-text-color="#409EFF"
        @select="isMobile && (sidebarOpen = false)"
      >
        <el-menu-item index="/dashboard">
          <el-icon><Monitor /></el-icon>
          <span>仪表盘</span>
        </el-menu-item>
        <el-menu-item index="/services">
          <el-icon><Setting /></el-icon>
          <span>服务管理</span>
        </el-menu-item>
        <el-menu-item index="/network">
          <el-icon><Connection /></el-icon>
          <span>网络配置</span>
        </el-menu-item>
        <el-menu-item index="/market">
          <el-icon><ShoppingCart /></el-icon>
          <span>应用商店</span>
        </el-menu-item>
        <el-menu-item index="/backup">
          <el-icon><FolderOpened /></el-icon>
          <span>备份中心</span>
        </el-menu-item>
        <el-menu-item index="/settings">
          <el-icon><Tools /></el-icon>
          <span>全局设置</span>
        </el-menu-item>
        <el-menu-item index="/docs">
          <el-icon><Document /></el-icon>
          <span>使用文档</span>
        </el-menu-item>
      </el-menu>
    </el-aside>
    <!-- 主区域 -->
    <el-container>
      <el-header v-if="isMobile" class="mobile-header">
        <el-icon class="hamburger" @click="sidebarOpen = !sidebarOpen"><Menu /></el-icon>
        <span class="mobile-title">EasyServer</span>
      </el-header>
      <el-main style="padding: 20px; background: #f0f2f5">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
  <!-- 全屏页面（setup/login/network-guide） -->
  <router-view v-else />
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Menu } from '@element-plus/icons-vue'
import api from './api'

const route = useRoute()
const router = useRouter()
const isMobile = ref(false)
const sidebarOpen = ref(false)
const setupCompleted = ref(null) // null = 未检测, true/false
const isLoggedIn = ref(false)

// 无侧边栏的页面
const fullScreenPages = ['/setup', '/login']
const showLayout = computed(() => !fullScreenPages.includes(route.path))

const checkMobile = () => {
  isMobile.value = window.innerWidth < 768
  if (!isMobile.value) sidebarOpen.value = false
}

// 检测 setup 和 auth 状态
const checkAuth = async () => {
  try {
    const { data } = await api.get('/config/setup/status')
    setupCompleted.value = data.setup_completed
    if (!data.setup_completed && route.path !== '/setup') {
      router.replace('/setup')
      return
    }
    if (data.setup_completed) {
      const token = localStorage.getItem('easyserver_token')
      if (!token && route.path !== '/login') {
        router.replace('/login')
        return
      }
      isLoggedIn.value = !!token
    }
  } catch (e) {
    // API 不可达，可能在安装中
    if (route.path !== '/setup') {
      router.replace('/setup')
    }
  }
}

onMounted(() => {
  checkMobile()
  window.addEventListener('resize', checkMobile)
  checkAuth()
})

onUnmounted(() => {
  window.removeEventListener('resize', checkMobile)
})
</script>

<style>
body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }

.logo {
  padding: 20px;
  color: #fff;
  font-size: 20px;
  font-weight: bold;
  text-align: center;
  cursor: pointer;
}

.mobile-header {
  display: flex;
  align-items: center;
  gap: 12px;
  background: #304156;
  color: #fff;
  height: 50px !important;
  padding: 0 16px;
}

.mobile-header .hamburger {
  font-size: 22px;
  cursor: pointer;
}

.mobile-header .mobile-title {
  font-size: 17px;
  font-weight: 600;
}

/* 手机端侧边栏 */
@media (max-width: 768px) {
  .mobile-sidebar {
    position: fixed !important;
    z-index: 1000;
    height: 100vh;
    transform: translateX(-100%);
    transition: transform 0.3s ease;
  }
  .mobile-sidebar.sidebar-open {
    transform: translateX(0);
  }
}

.overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  z-index: 999;
}
</style>
