<template>
  <div class="settings-page">
    <h2>全局设置</h2>

    <el-tabs v-model="activeTab" class="settings-tabs">
      <!-- 基础设置标签页 -->
      <el-tab-pane label="基础设置" name="settings">
        <!-- 域名信息（只读展示） -->
        <el-card style="max-width: 700px; width: 100%; margin-bottom: 20px">
          <template #header><span style="font-weight:600">基础信息</span></template>
          <el-descriptions :column="isMobile ? 1 : 2" border>
            <el-descriptions-item label="域名">{{ domain }}</el-descriptions-item>
            <el-descriptions-item label="SSL 邮箱">{{ sslEmail }}</el-descriptions-item>
          </el-descriptions>
          <div class="form-help" style="margin-top: 12px">
            如需修改域名或网络访问方式，请前往 <el-button type="primary" link @click="$router.push('/network')">网络配置</el-button>
          </div>
        </el-card>

        <!-- 容器资源管理 -->
        <el-card style="max-width: 700px; width: 100%; margin-bottom: 20px">
          <template #header><span style="font-weight:600">容器资源管理</span></template>
          <el-form :model="resourceForm" label-width="140px">
            <el-form-item label="CPU 限制 (核)">
              <el-input-number v-model="resourceForm.cpu_limit" :min="0.5" :max="16" :step="0.5" :precision="1" />
            </el-form-item>
            <el-form-item label="内存限制 (MB)">
              <el-input-number v-model="resourceForm.memory_limit" :min="256" :max="32768" :step="256" />
            </el-form-item>
            <el-form-item label="自动重启">
              <el-switch v-model="resourceForm.auto_restart" active-text="开启" inactive-text="关闭" />
            </el-form-item>
            <el-form-item label="日志保留天数">
              <el-input-number v-model="resourceForm.log_retention_days" :min="1" :max="90" />
            </el-form-item>
            <el-form-item label="自动清理">
              <el-switch v-model="resourceForm.auto_cleanup" active-text="开启" inactive-text="关闭" />
              <span style="margin-left: 8px; color: #999; font-size: 12px">自动清理未使用的镜像和悬空容器</span>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="saveResources" :loading="savingResources">保存资源设置</el-button>
              <el-button type="warning" @click="cleanupDocker" :loading="cleaning">立即清理</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>

      <!-- 配置文件标签页 -->
      <el-tab-pane label="配置文件" name="files">
        <!-- 安全警告 -->
        <el-alert
          type="warning"
          :closable="false"
          show-icon
          style="margin-bottom: 20px"
        >
          <template #title>
            直接编辑配置文件可能影响系统运行，请确保了解各配置项的含义。保存后将自动检测变更并触发关联操作。
          </template>
        </el-alert>

        <!-- 文件选择器 -->
        <div class="file-selector">
          <span class="file-selector-label">选择文件：</span>
          <el-radio-group v-model="selectedFile" size="default">
            <el-radio-button
              v-for="f in files"
              :key="f.name"
              :value="f.name"
            >
              {{ f.name }}
              <span class="file-size-badge">{{ formatSize(f.size) }}</span>
            </el-radio-button>
          </el-radio-group>
        </div>

        <!-- 代码编辑器 -->
        <textarea
          ref="editorRef"
          v-model="fileContent"
          class="config-editor"
          spellcheck="false"
          autocomplete="off"
          @keydown.tab.prevent="handleTab"
        />

        <!-- 操作按钮栏 -->
        <div class="editor-actions">
          <el-button type="primary" :loading="saving" @click="saveFile">
            保存
          </el-button>
          <el-button @click="resetContent">
            重置
          </el-button>
          <span v-if="isDirty" class="dirty-hint">有未保存的修改</span>
        </div>

        <!-- 保存警告反馈 -->
        <el-alert
          v-for="(w, i) in warnings"
          :key="i"
          type="warning"
          :closable="false"
          style="margin-top: 10px"
        >
          {{ w }}
        </el-alert>

        <!-- 加载状态 -->
        <div v-if="loadingFile" class="loading-file">
          <el-icon class="is-loading"><Loading /></el-icon>
          加载中...
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 日志弹窗 -->
    <el-dialog v-model="logVisible" :title="'日志 - ' + logModule" :width="isMobile ? '95%' : '700px'" top="5vh">
      <pre class="log-content">{{ logContent }}</pre>
      <template #footer>
        <el-button @click="logVisible = false">关闭</el-button>
        <el-button type="primary" @click="viewLogs(logModule)">刷新</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'
import { useMobile } from '@/composables/useMobile'
import { getConfigFiles, getConfigFile, updateConfigFile } from '@/api'
import api from '../api'

const { isMobile } = useMobile()

// ===== 标签页 =====
const activeTab = ref('settings')

// ===== 基础信息 =====
const domain = ref('')
const sslEmail = ref('')

const loadConfig = async () => {
  try {
    const { data } = await api.get('/config')
    const cfg = data.config || {}
    const env = data.env_summary || {}
    domain.value = env.DOMAIN || cfg.domain || ''
    sslEmail.value = cfg.ssl_email || ''
    resourceForm.value.cpu_limit = cfg.cpu_limit || 2.0
    resourceForm.value.memory_limit = cfg.memory_limit || 2048
    resourceForm.value.auto_restart = cfg.auto_restart !== false
    resourceForm.value.log_retention_days = cfg.log_retention_days || 7
    resourceForm.value.auto_cleanup = cfg.auto_cleanup !== false
  } catch (e) { ElMessage.error('加载配置失败') }
}

// ===== 容器资源管理 =====
const resourceForm = ref({
  cpu_limit: 2.0, memory_limit: 2048, auto_restart: true,
  log_retention_days: 7, auto_cleanup: false
})
const savingResources = ref(false)
const cleaning = ref(false)

const saveResources = async () => {
  savingResources.value = true
  try {
    await api.put('/config', resourceForm.value)
    ElMessage.success('资源设置已保存')
  } catch (e) { ElMessage.error('保存失败') }
  savingResources.value = false
}

const cleanupDocker = async () => {
  try {
    await ElMessageBox.confirm('确定清理未使用的 Docker 镜像和悬停容器？', '确认清理')
  } catch { return }
  cleaning.value = true
  try {
    await api.post('/services/cleanup')
    ElMessage.success('清理完成')
  } catch (e) {
    ElMessage.warning('清理接口暂未实现，请手动执行 docker system prune')
  }
  cleaning.value = false
}

// ===== 日志查看 =====
const logVisible = ref(false)
const logModule = ref('')
const logContent = ref('')

const viewLogs = async (moduleId) => {
  logModule.value = moduleId
  try {
    const { data } = await api.get(`/services/${moduleId}/logs`, { params: { lines: 200 } })
    logContent.value = data.logs || '无日志'
  } catch (e) {
    logContent.value = '加载日志失败'
  }
  logVisible.value = true
}

// ===== 配置文件编辑 =====
const editorRef = ref(null)
const files = ref([])
const selectedFile = ref('config.yaml')
const fileContent = ref('')
const originalContent = ref('')
const saving = ref(false)
const warnings = ref([])
const loadingFile = ref(false)

const isDirty = computed(() => fileContent.value !== originalContent.value)

function formatSize(bytes) {
  if (bytes < 1024) return bytes + ' B'
  return (bytes / 1024).toFixed(1) + ' KB'
}

async function loadFileList() {
  try {
    const { data } = await getConfigFiles()
    files.value = data.files || []
    if (files.value.length && !files.value.find(f => f.name === selectedFile.value)) {
      selectedFile.value = files.value[0].name
    }
  } catch (e) {
    ElMessage.error('加载文件列表失败')
  }
}

async function loadFileContent(filename) {
  loadingFile.value = true
  warnings.value = []
  try {
    const { data } = await getConfigFile(filename)
    fileContent.value = data.content || ''
    originalContent.value = data.content || ''
  } catch (e) {
    ElMessage.error('加载文件内容失败')
    fileContent.value = ''
    originalContent.value = ''
  }
  loadingFile.value = false
}

async function saveFile() {
  saving.value = true
  warnings.value = []
  try {
    const { data } = await updateConfigFile(selectedFile.value, fileContent.value)
    originalContent.value = fileContent.value
    ElMessage.success('保存成功')
    if (data.warnings && data.warnings.length) {
      warnings.value = data.warnings
    }
    // 刷新文件列表（大小可能变了）
    await loadFileList()
  } catch (e) {
    const msg = e.response?.data?.detail || '保存失败'
    ElMessage.error(msg)
  }
  saving.value = false
}

function resetContent() {
  fileContent.value = originalContent.value
  warnings.value = []
}

function handleTab(e) {
  const ta = e.target
  const start = ta.selectionStart
  const end = ta.selectionEnd
  const val = ta.value
  // 插入两个空格
  fileContent.value = val.substring(0, start) + '  ' + val.substring(end)
  // 下一 tick 恢复光标位置
  setTimeout(() => { ta.selectionStart = ta.selectionEnd = start + 2 }, 0)
}

// 切换到配置文件标签时加载
watch(activeTab, (tab) => {
  if (tab === 'files') loadFileList()
})

// 切换文件时加载内容
watch(selectedFile, (file) => {
  if (file) loadFileContent(file)
})

onMounted(() => {
  loadConfig()
})
</script>

<style scoped>
.settings-page { max-width: 800px; }
.settings-tabs :deep(.el-tabs__content) {
  padding-top: 16px;
}
.log-content {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 16px;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.6;
  max-height: 500px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
}
.form-help {
  font-size: 12px;
  color: #909399;
  line-height: 1.5;
}

/* 文件选择器 */
.file-selector {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.file-selector-label {
  font-size: 14px;
  color: #606266;
  flex-shrink: 0;
}
.file-size-badge {
  font-size: 11px;
  color: #909399;
  margin-left: 4px;
}

/* 代码编辑器 */
.config-editor {
  width: 100%;
  min-height: 500px;
  font-family: 'Courier New', Consolas, monospace;
  font-size: 13px;
  line-height: 1.5;
  background: #1e1e1e;
  color: #d4d4d4;
  border: 1px solid #333;
  border-radius: 4px;
  padding: 12px;
  resize: vertical;
  tab-size: 2;
  white-space: pre;
  overflow-wrap: normal;
  overflow: auto;
  box-sizing: border-box;
}
.config-editor:focus {
  outline: none;
  border-color: #409eff;
}

/* 操作按钮栏 */
.editor-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 14px;
}
.dirty-hint {
  font-size: 12px;
  color: #e6a23c;
  margin-left: 8px;
}

/* 加载状态 */
.loading-file {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 16px;
  color: #909399;
  font-size: 13px;
}
</style>
