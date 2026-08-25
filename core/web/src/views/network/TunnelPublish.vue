<template>
  <el-card style="max-width: 800px; width: 100%; margin-bottom: 20px">
    <template #header><span style="font-weight:600">服务发布</span></template>
    <el-table :data="groupedServices" size="small" empty-text="暂无可以发布的服务">
      <el-table-column prop="name" label="服务" min-width="120" />
      <el-table-column label="访问地址" min-width="240">
        <template #default="{ row }">
          <div style="line-height: 1.8">
            <div v-for="h in row.hostnames" :key="h.hostname" style="font-size: 12px">
              <span v-if="h.published" style="margin-right: 4px">✅</span>
              <span v-else style="margin-right: 4px; color: #c0c4cc">○</span>
              <span :style="h.published ? '' : 'color: #909399'">{{ h.hostname }}</span>
            </div>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="域名" width="140">
        <template #default="{ row }">
          <div style="font-size: 12px; line-height: 1.8">
            <div v-for="h in row.hostnames" :key="h.domain">
              <el-tag v-if="h.published" size="small" type="success" plain style="margin: 2px">{{ h.domain }}</el-tag>
              <span v-else style="color: #c0c4cc">{{ h.domain }}</span>
            </div>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="110">
        <template #default="{ row }">
          <el-button v-if="row.allPublished" type="danger" size="small" plain @click="handleUnpublishAll(row)">
            取消发布
          </el-button>
          <el-button v-else-if="row.nonePublished" type="primary" size="small" @click="handlePublishFirst(row)">
            发布
          </el-button>
          <el-button v-else type="warning" size="small" plain @click="handlePublishFirst(row)">
            管理
          </el-button>
        </template>
      </el-table-column>
    </el-table>
    <div class="form-help" style="margin-top: 8px">
      发布后自动创建路由和 DNS 记录，通过 https://子域名.域名 访问（免端口号）
    </div>
  </el-card>
</template>

<script setup>
import { computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../../api'

const props = defineProps({
  tunnelStatus: { type: Object, required: true },
  selectedTunnelDomain: { type: String, default: '' },
})

const emit = defineEmits(['refresh'])

// 按服务分组的数据（每个服务一行）
const groupedServices = computed(() => {
  const services = props.tunnelStatus?.services || []
  const routeHostnames = new Set((props.tunnelStatus?.routes || []).map(r => r.hostname))
  return services.map(svc => {
    const allHostnames = svc.all_hostnames?.length ? svc.all_hostnames : (svc.hostname ? [svc.hostname] : [])
    const hostnameDetails = allHostnames.map(h => ({
      hostname: h,
      domain: allHostnames.length > 1 ? h.split('.').slice(1).join('.') : '',
      published: routeHostnames.has(h),
    }))
    const publishedCount = hostnameDetails.filter(h => h.published).length
    const allPublished = hostnameDetails.length > 0 && publishedCount === hostnameDetails.length
    const nonePublished = publishedCount === 0
    return {
      module: svc.module,
      name: svc.name,
      subdomain: svc.subdomain,
      port: svc.port,
      hostnames: hostnameDetails,
      allPublished,
      nonePublished,
      partialPublished: !allPublished && !nonePublished,
    }
  })
})

const publishService = async (row) => {
  const targetDomain = row.domain || props.selectedTunnelDomain || ''
  const accessUrl = `https://${row.hostname}`
  try {
    await ElMessageBox.confirm(
      `即将发布服务：\n\n服务：${row.name}\n目标域名：${targetDomain}\n访问地址：${accessUrl}\n\n确认发布？`,
      '确认发布服务',
      { confirmButtonText: '确认发布', cancelButtonText: '取消', type: 'info' }
    )
  } catch {
    return
  }
  try {
    const { data } = await api.post('/cloudflare/publish', {
      subdomain: row.subdomain, port: row.port,
      domain: targetDomain
    })
    ElMessage.success(data.message || '发布成功')
    if (data.dns_warning) ElMessage.warning(data.dns_warning)
    emit('refresh')
  } catch (e) {
    ElMessage.error('发布失败: ' + (e.response?.data?.detail || e.message))
  }
}

const handleUnpublishAll = async (row) => {
  const hostnames = row.hostnames.filter(h => h.published).map(h => h.hostname)
  try {
    await ElMessageBox.confirm(
      `确定取消发布以下地址？\n\n${hostnames.join('\n')}`,
      '确认操作'
    )
  } catch { return }
  try {
    for (const hostname of hostnames) {
      const { data } = await api.post('/cloudflare/unpublish', { hostname })
      if (data.warnings?.length) data.warnings.forEach(w => ElMessage.warning(w))
    }
    ElMessage.success(`已取消发布 ${hostnames.length} 个地址`)
    emit('refresh')
  } catch (e) {
    ElMessage.error('操作失败: ' + (e.response?.data?.detail || e.message))
  }
}

const handlePublishFirst = async (row) => {
  const unpublished = row.hostnames.find(h => !h.published)
  if (!unpublished) {
    ElMessage.info('所有地址均已发布')
    return
  }
  const targetRow = {
    module: row.module,
    name: row.name,
    subdomain: row.subdomain,
    port: row.port,
    hostname: unpublished.hostname,
    domain: unpublished.domain,
  }
  await publishService(targetRow)
}
</script>

<style scoped>
.form-help { font-size: 12px; color: #909399; margin-top: 4px; line-height: 1.5; }
</style>
