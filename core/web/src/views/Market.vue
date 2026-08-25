<template>
  <div class="market-page">
    <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px">
      <h2 style="margin: 0">应用商店</h2>
      <el-input
        v-model="searchQuery"
        placeholder="搜索模块..."
        :prefix-icon="Search"
        clearable
        style="max-width: 260px"
        size="large"
      />
    </div>

    <!-- 筛选标签 -->
    <div class="filter-tags">
      <el-check-tag
        v-for="tag in filterTags"
        :key="tag.key"
        :checked="activeFilter === tag.key"
        @change="activeFilter = tag.key"
        style="margin-right: 8px; cursor: pointer"
      >
        {{ tag.label }}
      </el-check-tag>
    </div>

    <el-tabs v-model="activeCategory">
      <el-tab-pane v-for="cat in visibleCategories" :key="cat.key" :label="cat.label" :name="cat.key">
        <el-row :gutter="16">
          <el-col :xs="24" :sm="12" :md="8" v-for="mod in filteredModules(cat.key)" :key="mod.id" style="margin-bottom: 16px">
            <el-card shadow="hover">
              <template #header>
                <div class="card-header">
                  <span class="mod-name">{{ mod.name }}</span>
                  <el-tag v-if="mod.installed" type="success" size="small">已安装</el-tag>
                  <el-tag v-else type="info" size="small">可安装</el-tag>
                </div>
              </template>
              <div class="mod-desc">{{ mod.description }}</div>
              <div class="mod-meta">
                <span v-if="mod.access && mod.access.port">端口: {{ mod.access.port }}</span>
                <span>v{{ mod.version }}</span>
              </div>
              <div class="mod-deps" v-if="mod.depends_on && mod.depends_on.length">
                <el-tag size="small" type="warning" v-for="dep in mod.depends_on" :key="dep">依赖: {{ dep }}</el-tag>
              </div>
              <div class="mod-actions" style="margin-top: 12px">
                <el-button v-if="!mod.installed" type="primary" size="small" @click="installModule(mod)" :loading="installingId === mod.id">安装</el-button>
                <el-button v-else type="danger" size="small" @click="uninstallModule(mod)">卸载</el-button>
              </div>
            </el-card>
          </el-col>
        </el-row>
        <el-empty v-if="filteredModules(cat.key).length === 0" description="没有匹配的模块" />
      </el-tab-pane>
    </el-tabs>

    <!-- 安装中状态卡片 -->
    <el-card v-if="installTask" class="install-progress" shadow="never">
      <template #header>
        <div class="card-header">
          <span>安装「{{ moduleName(installTask.module_id) }}」</span>
          <el-tag :type="installTask.status === 'failed' ? 'danger' : 'primary'" size="small">
            {{ installTask.status === 'failed' ? '失败' : '进行中' }}
          </el-tag>
        </div>
      </template>
      <div v-if="installTask.status === 'pending' || installTask.status === 'running'" class="install-stage">
        <el-icon class="is-loading"><Loading /></el-icon>
        <span>{{ stageText }}</span>
      </div>
      <el-alert
        v-else-if="installTask.status === 'failed'"
        type="error"
        :title="installTask.error?.hint || '安装失败'"
        show-icon
        :closable="false"
      >
        <template #default>
          <div v-if="installTask.error?.detail" style="margin-top: 8px">
            <el-button link type="primary" size="small" @click="showErrorDetail = !showErrorDetail">
              {{ showErrorDetail ? '收起原始错误' : '查看原始错误' }}
            </el-button>
            <pre v-if="showErrorDetail" class="error-detail">{{ installTask.error.detail }}</pre>
          </div>
          <el-button type="primary" size="small" style="margin-top: 8px" @click="retryInstall">重新安装</el-button>
        </template>
      </el-alert>
    </el-card>

    <!-- 安装配置弹窗 -->
    <el-dialog v-model="configVisible" :title="'安装 ' + installingModule?.name" :width="isMobile ? '95%' : '500px'">
      <el-form :model="installConfig" label-width="120px">
        <el-form-item
          v-for="field in configFields"
          :key="field.key"
          :label="field.label || field.key"
          :required="field.required && !field.auto_generate"
        >
          <!-- 密码字段：显示/隐藏切换 + 随机生成 -->
          <div v-if="field.type === 'password'" style="width: 100%">
            <el-input v-model="installConfig[field.key]" type="password" show-password :placeholder="field.placeholder || '输入密码'" :disabled="installing">
              <template #append>
                <el-button @click="generateFieldPassword(field)" :disabled="installing">生成</el-button>
              </template>
            </el-input>
            <div class="field-hint">{{ field.auto_generate ? '留空将自动生成随机密码' : (field.description || '') }}</div>
          </div>
          <el-input v-else-if="field.type === 'text' || field.type === 'string'" v-model="installConfig[field.key]" :placeholder="field.description" :disabled="installing" />
          <el-input-number v-else-if="field.type === 'number'" v-model="installConfig[field.key]" :disabled="installing" />
          <el-switch v-else-if="field.type === 'bool' || field.type === 'boolean'" v-model="installConfig[field.key]" :disabled="installing" />
          <el-select v-else-if="field.type === 'select'" v-model="installConfig[field.key]" :disabled="installing">
            <el-option v-for="opt in field.options" :key="opt.value" :label="opt.label" :value="opt.value" />
          </el-select>
          <el-input v-else v-model="installConfig[field.key]" :placeholder="field.description" :disabled="installing" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="configVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmInstall" :loading="installing">确认安装</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Loading } from '@element-plus/icons-vue'
import { useMobile } from '@/composables/useMobile'
import api from '../api'

const { isMobile } = useMobile()

const modules = ref([])
const activeCategory = ref('infra')
const configVisible = ref(false)
const installingModule = ref(null)
const installConfig = ref({})
const configFields = ref([])
const installing = ref(false)
const installingId = ref('')
const searchQuery = ref('')
const activeFilter = ref('all')

// 安装任务状态（轮询）
const installTask = ref(null)
const showErrorDetail = ref(false)
let installPollTimer = null

const categories = ref([])

const filterTags = [
  { key: 'all', label: '全部' },
  { key: 'installed', label: '已安装' },
  { key: 'available', label: '可安装' }
]

const visibleCategories = computed(() => {
  // 搜索时只显示有匹配模块的分类
  if (!searchQuery.value && activeFilter.value === 'all') return categories.value
  return categories.value.filter(cat => {
    const mods = modules.value.filter(m => m.category === cat.key)
    return applyFilters(mods).length > 0
  })
})

const applyFilters = (mods) => {
  let result = mods
  // 搜索过滤
  if (searchQuery.value) {
    const q = searchQuery.value.toLowerCase()
    result = result.filter(m =>
      (m.name || '').toLowerCase().includes(q) ||
      (m.description || '').toLowerCase().includes(q) ||
      (m.id || '').toLowerCase().includes(q)
    )
  }
  // 状态过滤
  if (activeFilter.value === 'installed') {
    result = result.filter(m => m.installed)
  } else if (activeFilter.value === 'available') {
    result = result.filter(m => !m.installed)
  }
  return result
}

const filteredModules = (cat) => applyFilters(modules.value.filter(m => m.category === cat))

const loadModules = async () => {
  try {
    const { data } = await api.get('/modules')
    const allModules = []
    const cats = []
    for (const cat of (data.categories || [])) {
      cats.push({ key: cat.id, label: cat.name })
      for (const mod of (cat.modules || [])) {
        allModules.push({ ...mod, category: cat.id })
      }
    }
    categories.value = cats
    modules.value = allModules
    if (cats.length && !cats.find(c => c.key === activeCategory.value)) {
      activeCategory.value = cats[0].key
    }
  } catch (e) { ElMessage.error('加载模块列表失败') }
}

const installModule = (mod) => {
  installingModule.value = mod
  configFields.value = mod.config || []
  installConfig.value = {}
  ;(mod.config || []).forEach(f => { installConfig.value[f.key] = f.default ?? '' })
  if (configFields.value.length === 0) {
    // 无配置字段，直接开始安装
    startInstall(mod, {})
  } else {
    configVisible.value = true
  }
}

const moduleName = (id) => {
  const m = modules.value.find(x => x.id === id)
  return m ? m.name : id
}

const stageText = computed(() => {
  const t = installTask.value
  if (!t) return ''
  if (t.status === 'pending') return '准备中...'
  if (t.status === 'running') {
    if (t.stage === 'pull') return '正在拉取镜像，大镜像可能需要几分钟，请耐心等待...'
    if (t.stage === 'up') return '正在启动容器...'
    return '安装中...'
  }
  return ''
})

const startInstall = async (mod, config) => {
  installing.value = true
  installingId.value = mod.id
  try {
    const { data } = await api.post('/modules/install', { module_id: mod.id, config })
    if (data.success === false) {
      ElMessage.error(`安装失败: ${data.message || '未知错误'}`)
      return
    }
    configVisible.value = false
    showErrorDetail.value = false
    installTask.value = { module_id: mod.id, status: data.status || 'pending', stage: '', error: null, log: [] }
    startPolling(mod.id)
  } catch (e) {
    const detail = e.response?.data?.detail || e.message
    ElMessage.error(`安装失败: ${detail}`)
  } finally {
    installing.value = false
    installingId.value = ''
  }
}

const startPolling = (moduleId) => {
  stopPolling()
  let noneCount = 0
  installPollTimer = setInterval(async () => {
    try {
      const { data } = await api.get(`/modules/${moduleId}/install/status`)
      if (data.status === 'none') {
        // 任务丢失（如后端重启），连续多次后停止轮询
        if (++noneCount >= 5) {
          stopPolling()
          ElMessage.warning('安装状态查询失败（服务可能已重启），请刷新页面确认')
          installTask.value = null
        }
        return
      }
      installTask.value = data
      if (data.status === 'success') {
        stopPolling()
        ElMessage.success('安装成功')
        installTask.value = null
        loadModules()
      }
    } catch (e) {
      stopPolling()
      ElMessage.error('查询安装状态失败，请稍后在页面刷新确认结果')
    }
  }, 2000)
}

const stopPolling = () => {
  if (installPollTimer) {
    clearInterval(installPollTimer)
    installPollTimer = null
  }
}

const retryInstall = () => {
  const mod = modules.value.find(x => x.id === installTask.value?.module_id)
  if (!mod) return
  installTask.value = null
  showErrorDetail.value = false
  installModule(mod)
}

const generateFieldPassword = async (field) => {
  try {
    const { data } = await api.post('/config/generate-password')
    installConfig.value[field.key] = data.password
  } catch (e) {
    ElMessage.error('生成密码失败，请手动输入')
  }
}

const confirmInstall = async () => {
  // 必填校验（auto_generate 字段留空由后端自动生成）
  for (const f of configFields.value) {
    if (f.required && !f.auto_generate) {
      const v = installConfig.value[f.key]
      if (v === undefined || v === null || String(v).trim() === '') {
        ElMessage.warning(`字段「${f.label || f.key}」为必填项`)
        return
      }
    }
  }
  const mod = installingModule.value
  if (!mod) return
  await startInstall(mod, { ...installConfig.value })
}

const uninstallModule = async (mod) => {
  let removeData = false
  try {
    await ElMessageBox.confirm(
      `确定卸载 ${mod.name}？\n卸载将停止容器并删除镜像。是否同时删除该模块的数据目录？`,
      '卸载模块',
      {
        distinguishCancelAndClose: true,
        confirmButtonText: '删除数据',
        cancelButtonText: '仅卸载（保留数据）',
        type: 'warning'
      }
    )
    removeData = true
  } catch (action) {
    if (action === 'cancel') {
      removeData = false // 仅卸载，保留数据
    } else {
      return // 点击关闭（X/ESC），放弃卸载
    }
  }
  try {
    const { data } = await api.post(`/modules/${mod.id}/uninstall`, { remove_data: removeData })
    if (data.success === false) {
      ElMessage.error(`卸载失败: ${data.error || '未知错误'}`)
    } else {
      ElMessage.success(removeData ? `${mod.name} 已卸载，数据已删除` : `${mod.name} 已卸载，数据已保留`)
      loadModules()
    }
  } catch (e) {
    ElMessage.error(`卸载失败: ${e.response?.data?.detail || e.message}`)
  }
}

onMounted(loadModules)
onUnmounted(() => {
  stopPolling()
})
</script>

<style scoped>
.card-header { display: flex; justify-content: space-between; align-items: center; }
.mod-name { font-weight: 600; font-size: 15px; }
.mod-desc { color: #666; font-size: 13px; margin-bottom: 8px; }
.mod-meta { display: flex; gap: 16px; font-size: 12px; color: #999; margin-bottom: 6px; }
.mod-deps { display: flex; gap: 6px; flex-wrap: wrap; }
.filter-tags { margin: 16px 0; }
.install-progress { margin-bottom: 16px; }
.install-stage { display: flex; align-items: center; gap: 8px; color: #409EFF; font-size: 14px; }
.error-detail { background: #f5f7fa; padding: 10px; border-radius: 4px; font-size: 12px; max-height: 200px; overflow: auto; white-space: pre-wrap; word-break: break-all; }
.field-hint { font-size: 12px; color: #999; line-height: 1.4; margin-top: 4px; }
</style>
