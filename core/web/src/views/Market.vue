<template>
  <div class="market-page">
    <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px">
      <h2 style="margin: 0">模块市场</h2>
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

    <!-- 安装配置弹窗 -->
    <el-dialog v-model="configVisible" :title="'安装 ' + installingModule?.name" :width="isMobile ? '95%' : '500px'">
      <el-form :model="installConfig" label-width="120px">
        <el-form-item v-for="field in configFields" :key="field.key" :label="field.label || field.key">
          <el-input v-if="field.type === 'text' || field.type === 'password'" v-model="installConfig[field.key]" :type="field.type" :placeholder="field.description" />
          <el-input-number v-else-if="field.type === 'number'" v-model="installConfig[field.key]" />
          <el-switch v-else-if="field.type === 'bool'" v-model="installConfig[field.key]" />
          <el-select v-else-if="field.type === 'select'" v-model="installConfig[field.key]">
            <el-option v-for="opt in field.options" :key="opt.value" :label="opt.label" :value="opt.value" />
          </el-select>
          <el-input v-else v-model="installConfig[field.key]" :placeholder="field.description" />
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
import { Search } from '@element-plus/icons-vue'
import api from '../api'

const isMobile = ref(false)
const checkMobile = () => { isMobile.value = window.innerWidth < 768 }
onMounted(() => { checkMobile(); window.addEventListener('resize', checkMobile) })
onUnmounted(() => { window.removeEventListener('resize', checkMobile) })

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
  configVisible.value = true
}

const confirmInstall = async () => {
  installing.value = true
  installingId.value = installingModule.value.id
  try {
    const { data } = await api.post('/modules/install', { module_id: installingModule.value.id, config: installConfig.value })
    if (data.success === false) {
      ElMessage.error(`安装失败: ${data.error || data.message || '未知错误'}`)
    } else {
      ElMessage.success(`${installingModule.value.name} 安装成功`)
      configVisible.value = false
      loadModules()
    }
  } catch (e) {
    const detail = e.response?.data?.detail || e.response?.data?.detail || e.message
    ElMessage.error(`安装失败: ${detail}`)
  } finally {
    installing.value = false
    installingId.value = ''
  }
}

const uninstallModule = async (mod) => {
  await ElMessageBox.confirm(`确定卸载 ${mod.name}？数据将保留。`, '确认卸载')
  try {
    const { data } = await api.post(`/modules/${mod.id}/uninstall`)
    if (data.success === false) {
      ElMessage.error(`卸载失败: ${data.error || '未知错误'}`)
    } else {
      ElMessage.success(`${mod.name} 已卸载`)
      loadModules()
    }
  } catch (e) {
    ElMessage.error(`卸载失败: ${e.response?.data?.detail || e.message}`)
  }
}

onMounted(loadModules)
</script>

<style scoped>
.card-header { display: flex; justify-content: space-between; align-items: center; }
.mod-name { font-weight: 600; font-size: 15px; }
.mod-desc { color: #666; font-size: 13px; margin-bottom: 8px; }
.mod-meta { display: flex; gap: 16px; font-size: 12px; color: #999; margin-bottom: 6px; }
.mod-deps { display: flex; gap: 6px; flex-wrap: wrap; }
.filter-tags { margin: 16px 0; }
</style>
