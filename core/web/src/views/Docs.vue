<template>
  <div class="docs-container">
    <!-- 左侧目录树 -->
    <div class="docs-sidebar">
      <div class="sidebar-title">文档目录</div>
      
      <!-- 全局文档 -->
      <div class="sidebar-section">
        <div class="section-label">全局指南</div>
        <div
          v-for="doc in globalDocs"
          :key="doc.id"
          class="sidebar-item"
          :class="{ active: currentDocId === doc.id }"
          @click="loadGlobalDoc(doc.id)"
        >
          <el-icon><component :is="doc.icon" /></el-icon>
          <span>{{ doc.title }}</span>
        </div>
      </div>

      <!-- 模块文档 -->
      <div class="sidebar-section" v-if="moduleDocs.length > 0">
        <div class="section-label">服务模块</div>
        <div
          v-for="doc in moduleDocs"
          :key="doc.id"
          class="sidebar-item"
          :class="{ active: currentDocId === doc.id }"
          @click="loadModuleDoc(doc.module_id)"
        >
          <el-icon><Box /></el-icon>
          <span>{{ doc.title }}</span>
        </div>
      </div>
    </div>

    <!-- 右侧内容区 -->
    <div class="docs-content">
      <div v-if="loading" class="loading-wrapper">
        <el-skeleton :rows="10" animated />
      </div>
      
      <div v-else-if="currentContent" class="content-wrapper">
        <h1 class="doc-title">{{ currentTitle }}</h1>
        <div class="markdown-body" v-html="renderedContent"></div>
      </div>

      <div v-else-if="moduleDocData" class="content-wrapper">
        <h1 class="doc-title">{{ moduleDocData.module_name }}</h1>
        
        <!-- 使用说明 -->
        <div v-if="moduleDocData.docs.usage" class="markdown-body" v-html="renderedModuleUsage"></div>
        
        <!-- FAQ -->
        <div v-if="moduleDocData.docs.faq && moduleDocData.docs.faq.length" class="module-faq">
          <h2>常见问题</h2>
          <el-collapse accordion>
            <el-collapse-item
              v-for="(item, index) in moduleDocData.docs.faq"
              :key="index"
              :title="item.q"
            >
              <p>{{ item.a }}</p>
            </el-collapse-item>
          </el-collapse>
        </div>

        <!-- 相关链接 -->
        <div v-if="moduleDocData.docs.links && moduleDocData.docs.links.length" class="module-links">
          <h2>相关链接</h2>
          <div v-for="(link, index) in moduleDocData.docs.links" :key="index" class="link-item">
            <el-icon><Link /></el-icon>
            <a :href="link.url" target="_blank" rel="noopener">{{ link.label }}</a>
          </div>
        </div>
      </div>

      <div v-else class="empty-wrapper">
        <el-empty description="请从左侧选择要查看的文档">
          <el-button type="primary" @click="loadGlobalDoc('quick-start')">阅读快速入门</el-button>
        </el-empty>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getDocList, getDoc, getModuleDocs } from '../api'
import { marked } from 'marked'

const route = useRoute()
const router = useRouter()

const globalDocs = ref([])
const moduleDocs = ref([])
const currentDocId = ref('')
const currentContent = ref('')
const currentTitle = ref('')
const moduleDocData = ref(null)
const loading = ref(false)

// Configure marked
marked.setOptions({
  breaks: true,
  gfm: true,
})

const renderedContent = computed(() => {
  if (!currentContent.value) return ''
  return marked(currentContent.value)
})

const renderedModuleUsage = computed(() => {
  if (!moduleDocData.value?.docs?.usage) return ''
  return marked(moduleDocData.value.docs.usage)
})

async function fetchDocList() {
  try {
    const res = await getDocList()
    globalDocs.value = res.data.global_docs || []
    moduleDocs.value = res.data.module_docs || []
  } catch (e) {
    console.error('Failed to fetch doc list:', e)
  }
}

async function loadGlobalDoc(docId) {
  loading.value = true
  currentDocId.value = docId
  moduleDocData.value = null
  currentContent.value = ''
  router.replace(`/docs/${docId}`)
  try {
    const res = await getDoc(docId)
    currentContent.value = res.data.content
    currentTitle.value = res.data.title
  } catch (e) {
    console.error('Failed to load doc:', e)
    currentContent.value = '# 文档加载失败\n\n请稍后重试。'
  } finally {
    loading.value = false
  }
}

async function loadModuleDoc(moduleId) {
  loading.value = true
  currentDocId.value = `module-${moduleId}`
  currentContent.value = ''
  moduleDocData.value = null
  router.replace(`/docs/module-${moduleId}`)
  try {
    const res = await getModuleDocs(moduleId)
    moduleDocData.value = res.data
  } catch (e) {
    console.error('Failed to load module doc:', e)
  } finally {
    loading.value = false
  }
}

// Handle route params
function handleRouteParam() {
  const docId = route.params.docId
  if (!docId) return
  if (docId.startsWith('module-')) {
    const moduleId = docId.replace('module-', '')
    loadModuleDoc(moduleId)
  } else {
    loadGlobalDoc(docId)
  }
}

onMounted(async () => {
  await fetchDocList()
  if (route.params.docId) {
    handleRouteParam()
  }
})

watch(() => route.params.docId, (newVal) => {
  if (newVal) handleRouteParam()
})
</script>

<style scoped>
.docs-container {
  display: flex;
  height: 100%;
  min-height: calc(100vh - 80px);
  gap: 0;
}

.docs-sidebar {
  width: 240px;
  min-width: 240px;
  background: #fff;
  border-right: 1px solid #e4e7ed;
  padding: 16px 0;
  overflow-y: auto;
}

.sidebar-title {
  font-size: 16px;
  font-weight: 600;
  padding: 0 20px 12px;
  color: #303133;
  border-bottom: 1px solid #ebeef5;
  margin-bottom: 8px;
}

.sidebar-section {
  margin-bottom: 8px;
}

.section-label {
  font-size: 12px;
  color: #909399;
  padding: 8px 20px 4px;
  text-transform: uppercase;
  letter-spacing: 1px;
}

.sidebar-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  cursor: pointer;
  color: #606266;
  font-size: 14px;
  transition: all 0.2s;
}

.sidebar-item:hover {
  background: #f5f7fa;
  color: #409eff;
}

.sidebar-item.active {
  background: #ecf5ff;
  color: #409eff;
  font-weight: 500;
}

.docs-content {
  flex: 1;
  padding: 24px 32px;
  background: #fff;
  overflow-y: auto;
}

.loading-wrapper {
  padding: 20px;
}

.empty-wrapper {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 60vh;
}

.doc-title {
  font-size: 28px;
  font-weight: 600;
  color: #303133;
  margin: 0 0 24px 0;
  padding-bottom: 16px;
  border-bottom: 2px solid #409eff;
}

/* Markdown styles */
.markdown-body {
  font-size: 15px;
  line-height: 1.7;
  color: #333;
}

.markdown-body :deep(h1) { font-size: 24px; margin: 24px 0 12px; }
.markdown-body :deep(h2) { font-size: 20px; margin: 20px 0 10px; border-bottom: 1px solid #ebeef5; padding-bottom: 8px; }
.markdown-body :deep(h3) { font-size: 17px; margin: 16px 0 8px; }
.markdown-body :deep(h4) { font-size: 15px; margin: 12px 0 6px; }

.markdown-body :deep(p) { margin: 8px 0; }
.markdown-body :deep(ul), .markdown-body :deep(ol) { padding-left: 24px; margin: 8px 0; }
.markdown-body :deep(li) { margin: 4px 0; }

.markdown-body :deep(code) {
  background: #f5f7fa;
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 13px;
  color: #e45649;
}

.markdown-body :deep(pre) {
  background: #282c34;
  color: #abb2bf;
  padding: 16px;
  border-radius: 6px;
  overflow-x: auto;
  margin: 12px 0;
}

.markdown-body :deep(pre code) {
  background: none;
  color: inherit;
  padding: 0;
}

.markdown-body :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 12px 0;
}

.markdown-body :deep(th), .markdown-body :deep(td) {
  border: 1px solid #dcdfe6;
  padding: 10px 14px;
  text-align: left;
}

.markdown-body :deep(th) {
  background: #f5f7fa;
  font-weight: 600;
}

.markdown-body :deep(blockquote) {
  border-left: 4px solid #409eff;
  padding: 8px 16px;
  margin: 12px 0;
  background: #ecf5ff;
  color: #606266;
}

.markdown-body :deep(a) {
  color: #409eff;
  text-decoration: none;
}

.markdown-body :deep(a:hover) {
  text-decoration: underline;
}

.markdown-body :deep(hr) {
  border: none;
  border-top: 1px solid #ebeef5;
  margin: 20px 0;
}

.markdown-body :deep(strong) { color: #303133; }

/* Module FAQ */
.module-faq {
  margin-top: 24px;
}

.module-faq h2 {
  font-size: 20px;
  margin: 20px 0 12px;
  border-bottom: 1px solid #ebeef5;
  padding-bottom: 8px;
}

/* Module Links */
.module-links {
  margin-top: 24px;
}

.module-links h2 {
  font-size: 20px;
  margin: 20px 0 12px;
  border-bottom: 1px solid #ebeef5;
  padding-bottom: 8px;
}

.link-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 0;
}

.link-item a {
  color: #409eff;
  text-decoration: none;
}

.link-item a:hover {
  text-decoration: underline;
}

.content-wrapper {
  max-width: 860px;
}
</style>
