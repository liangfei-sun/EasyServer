<template>
  <div class="market-page">
    <h2>模块市场</h2>
    <el-tabs v-model="activeCategory">
      <el-tab-pane v-for="cat in categories" :key="cat.key" :label="cat.label" :name="cat.key">
        <el-row :gutter="16">
          <el-col :span="8" v-for="mod in filteredModules(cat.key)" :key="mod.id" style="margin-bottom: 16px">
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
                <el-button v-if="!mod.installed" type="primary" size="small" @click="installModule(mod)">安装</el-button>
                <el-button v-else type="danger" size="small" @click="uninstallModule(mod)">卸载</el-button>
              </div>
            </el-card>
          </el-col>
        </el-row>
      </el-tab-pane>
    </el-tabs>

    <!-- 安装配置弹窗 -->
    <el-dialog v-model="configVisible" :title="'安装 ' + installingModule?.name" width="500px">
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
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api'

const modules = ref([])
const activeCategory = ref('infra')
const configVisible = ref(false)
const installingModule = ref(null)
const installConfig = ref({})
const configFields = ref([])
const installing = ref(false)

const categories = ref([])

const filteredModules = (cat) => modules.value.filter(m => m.category === cat)

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
  try {
    await api.post('/modules/install', { module_id: installingModule.value.id, config: installConfig.value })
    ElMessage.success(`${installingModule.value.name} 安装成功`)
    configVisible.value = false
    loadModules()
  } catch (e) { ElMessage.error(`安装失败: ${e.response?.data?.detail || e.message}`) }
  installing.value = false
}

const uninstallModule = async (mod) => {
  await ElMessageBox.confirm(`确定卸载 ${mod.name}？数据将保留。`, '确认卸载')
  try {
    await api.post(`/modules/${mod.id}/uninstall`)
    ElMessage.success(`${mod.name} 已卸载`)
    loadModules()
  } catch (e) { ElMessage.error('卸载失败') }
}

onMounted(loadModules)
</script>

<style scoped>
.card-header { display: flex; justify-content: space-between; align-items: center; }
.mod-name { font-weight: 600; font-size: 15px; }
.mod-desc { color: #666; font-size: 13px; margin-bottom: 8px; }
.mod-meta { display: flex; gap: 16px; font-size: 12px; color: #999; margin-bottom: 6px; }
.mod-deps { display: flex; gap: 6px; flex-wrap: wrap; }
</style>
