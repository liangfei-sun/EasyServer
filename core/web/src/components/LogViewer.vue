<template>
  <el-dialog
    :model-value="visible"
    @update:model-value="$emit('update:visible', $event)"
    :title="`${moduleName} - 日志`"
    :width="isMobile ? '95%' : '760px'"
    top="5vh"
    destroy-on-close
    @closed="handleClosed"
  >
    <div class="log-toolbar">
      <div class="log-toolbar-left">
        <span class="log-label">行数:</span>
        <el-select v-model="lines" size="small" style="width: 90px" @change="fetchLogs">
          <el-option :value="50" label="50" />
          <el-option :value="100" label="100" />
          <el-option :value="200" label="200" />
          <el-option :value="500" label="500" />
        </el-select>
      </div>
      <div class="log-toolbar-right">
        <el-switch v-model="autoRefresh" active-text="自动刷新" size="small" style="margin-right: 10px" />
        <el-button size="small" :icon="Refresh" @click="fetchLogs" :loading="loading">刷新</el-button>
      </div>
    </div>

    <div class="log-container" v-loading="loading && !logContent">
      <pre class="log-content" ref="logContainer">{{ logContent || '暂无日志' }}</pre>
    </div>

    <template #footer>
      <el-button @click="$emit('update:visible', false)">关闭</el-button>
      <el-button type="primary" :icon="Refresh" @click="fetchLogs" :loading="loading">刷新</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, watch, onBeforeUnmount, nextTick } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { useMobile } from '@/composables/useMobile'
import { getServiceLogs } from '@/api'

const props = defineProps({
  moduleId: { type: String, default: '' },
  moduleName: { type: String, default: '' },
  visible: { type: Boolean, default: false }
})

const emit = defineEmits(['update:visible'])

const { isMobile } = useMobile()

const lines = ref(100)
const logContent = ref('')
const loading = ref(false)
const autoRefresh = ref(false)
const logContainer = ref(null)

let timer = null

const fetchLogs = async () => {
  if (!props.moduleId) return
  loading.value = true
  try {
    const { data } = await getServiceLogs(props.moduleId, lines.value)
    logContent.value = data.logs || ''
    await nextTick()
    scrollToBottom()
  } catch {
    logContent.value = '获取日志失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

const scrollToBottom = () => {
  if (logContainer.value) {
    logContainer.value.scrollTop = logContainer.value.scrollHeight
  }
}

const handleClosed = () => {
  autoRefresh.value = false
  logContent.value = ''
}

// 监听 visible 变化，打开时自动加载
watch(() => props.visible, (val) => {
  if (val && props.moduleId) {
    fetchLogs()
  }
})

// 自动刷新
watch(autoRefresh, (val) => {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
  if (val) {
    timer = setInterval(fetchLogs, 5000)
  }
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.log-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  flex-wrap: wrap;
  gap: 8px;
}
.log-toolbar-left {
  display: flex;
  align-items: center;
  gap: 6px;
}
.log-toolbar-right {
  display: flex;
  align-items: center;
}
.log-label {
  font-size: 13px;
  color: #606266;
}
.log-container {
  min-height: 200px;
}
.log-content {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 16px;
  border-radius: 6px;
  max-height: 500px;
  overflow-y: auto;
  font-family: 'Cascadia Code', 'Fira Code', 'JetBrains Mono', 'Consolas', 'Monaco', monospace;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0;
}
</style>
