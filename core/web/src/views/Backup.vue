<template>
  <div class="backup-page">
    <h2>备份中心</h2>

    <!-- 备份服务异常告警：service_ok=false 时醒目展示真实原因，不再当作正常“0 快照” -->
    <el-alert
      v-if="!statusLoading && !backupStatus.service_ok"
      type="error"
      show-icon
      :closable="false"
      :title="'备份服务异常：' + (backupStatus.error || '未知原因')"
      style="margin-bottom: 20px"
    />

    <!-- 备份仪表盘 -->
    <el-row :gutter="16" style="margin-bottom: 20px">
      <el-col :xs="24" :sm="8" style="margin-bottom: 12px">
        <el-card shadow="hover">
          <template #header><span>上次备份</span></template>
          <div class="stat-value">
            <span v-if="statusLoading" class="stat-placeholder">加载中…</span>
            <span v-else-if="!backupStatus.service_ok" class="stat-placeholder">—</span>
            <span v-else>{{ backupStatus.last_backup ? new Date(backupStatus.last_backup).toLocaleString() : '暂无备份' }}</span>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="8" style="margin-bottom: 12px">
        <el-card shadow="hover">
          <template #header><span>快照数量</span></template>
          <div class="stat-value">
            <!-- 用 snapshot_count（restic 真实总数），而非被截断为最近10条的 snapshots.length -->
            <span v-if="statusLoading" class="stat-placeholder">加载中…</span>
            <span v-else-if="!backupStatus.service_ok" class="stat-placeholder">—</span>
            <span v-else>{{ backupStatus.snapshot_count || 0 }} 个</span>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="8" style="margin-bottom: 12px">
        <el-card shadow="hover">
          <template #header><span>有效备份体量</span></template>
          <div class="stat-value">
            <!-- 仅展示当前活跃仓库 repo_size_mb；service_ok=false 时不可读，不以体量伪装有效 -->
            <span v-if="statusLoading" class="stat-placeholder">加载中…</span>
            <span v-else-if="!backupStatus.service_ok" class="stat-placeholder">—</span>
            <span v-else>{{ backupStatus.repo_size_mb || 0 }} MB</span>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 本地备份位置 -->
    <el-card style="margin-bottom: 20px">
      <template #header><span style="font-weight:600">本地备份存储</span></template>
      <el-descriptions :column="isMobile ? 1 : 2" border size="small">
        <el-descriptions-item label="备份仓库路径">{{ backupConfig.repo_path }}</el-descriptions-item>
        <el-descriptions-item label="数据源目录">{{ backupConfig.data_dir }}</el-descriptions-item>
        <el-descriptions-item label="备份密码">{{ backupConfig.password_set ? '已设置' : '未设置（使用默认）' }}</el-descriptions-item>
        <el-descriptions-item label="仓库状态">
          <span v-if="statusLoading">加载中…</span>
          <el-tag v-else-if="!backupConfig.initialized" type="info" size="small">未初始化</el-tag>
          <el-tag v-else-if="backupStatus.service_ok" type="success" size="small">正常</el-tag>
          <el-tag v-else type="danger" size="small">不可读</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="备份目录合计" :span="2">
          {{ backupStatus.total_size_mb || 0 }} MB
          <span style="color:#e6a23c;font-size:12px">（data/backups 全目录，含不可解密遗留旧库 restic-repo，非有效备份量）</span>
        </el-descriptions-item>
      </el-descriptions>
    </el-card>

    <!-- 操作区 -->
    <el-card style="margin-bottom: 20px">
      <template #header><span style="font-weight:600">备份操作</span></template>
      <div style="display: flex; gap: 12px; flex-wrap: wrap; align-items: center">
        <el-button type="primary" @click="doBackup" :loading="backupTriggering">立即备份</el-button>
        <el-button @click="loadBackupStatus" :loading="backupLoading">刷新状态</el-button>
      </div>
    </el-card>

    <!-- 备份计划 -->
    <el-card style="margin-bottom: 20px">
      <template #header><span style="font-weight:600">备份计划</span></template>
      <el-form label-width="100px" style="max-width: 500px">
        <el-form-item label="备份周期">
          <el-select v-model="backupForm.schedule" style="width: 220px">
            <el-option value="0 2 * * *" label="每天凌晨2点" />
            <el-option value="0 2 * * 0" label="每周日凌晨2点" />
            <el-option value="0 2 1 * *" label="每月1日凌晨2点" />
            <el-option value="0 */6 * * *" label="每6小时" />
          </el-select>
        </el-form-item>
        <el-form-item label="保留天数">
          <el-input-number v-model="backupForm.retain_days" :min="1" :max="90" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="saveBackupSchedule" :loading="backupSaving">保存计划</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 云端备份 -->
    <el-card style="margin-bottom: 20px">
      <template #header><span style="font-weight:600">云端备份（可选）</span></template>
      <el-form label-width="110px" style="max-width: 550px">
        <el-form-item label="云存储提供商">
          <el-select v-model="cloudForm.provider" style="width: 220px" placeholder="不使用云备份">
            <el-option value="none" label="不使用（仅本地备份）" />
            <el-option value="aliyun_oss" label="阿里云 OSS" />
            <el-option value="s3" label="AWS S3 / 兼容存储" />
            <el-option value="b2" label="Backblaze B2" />
          </el-select>
        </el-form-item>
        <template v-if="cloudForm.provider !== 'none'">
          <el-form-item label="Bucket 名称">
            <el-input v-model="cloudForm.bucket" placeholder="my-backup-bucket" />
          </el-form-item>
          <el-form-item label="Access Key">
            <el-input v-model="cloudForm.key" placeholder="Access Key ID" type="password" show-password />
          </el-form-item>
          <el-form-item label="Secret Key">
            <el-input v-model="cloudForm.secret" placeholder="Secret Access Key" type="password" show-password />
          </el-form-item>
          <el-form-item v-if="cloudForm.provider === 's3'" label="Endpoint">
            <el-input v-model="cloudForm.endpoint" placeholder="https://s3.amazonaws.com（可选）" />
          </el-form-item>
        </template>
        <el-form-item>
          <el-button type="primary" @click="saveCloudConfig" :loading="cloudSaving">保存云备份配置</el-button>
        </el-form-item>
        <el-alert v-if="cloudForm.provider === 'none'" type="info" :closable="false" style="margin-top: 8px">
          当前仅本地备份，建议配置云端存储以防止本地数据丢失。备份数据存储在 <code>data/backups/restic-repo-v2</code> 目录。
        </el-alert>
      </el-form>
    </el-card>

    <!-- 快照列表 -->
    <el-card>
      <template #header>
        <div style="display:flex;align-items:center;justify-content:space-between">
          <span style="font-weight:600">备份快照</span>
          <el-button size="small" @click="loadBackupStatus" :loading="backupLoading">刷新</el-button>
        </div>
      </template>
      <div v-if="statusLoading" style="color:#999;text-align:center;padding:20px">加载中…</div>
      <div v-else-if="!backupStatus.initialized" style="color:#999;text-align:center;padding:20px">
        备份模块未安装或未初始化，请先在应用商店安装「数据备份」模块。
      </div>
      <el-alert
        v-else-if="!backupStatus.service_ok"
        type="error"
        show-icon
        :closable="false"
        :title="'备份服务异常，无法读取快照：' + (backupStatus.error || '未知原因')"
      />
      <template v-else>
        <div v-if="backupStatus.snapshot_count > (backupStatus.snapshots?.length || 0)" style="color:#909399;font-size:12px;margin-bottom:8px">
          共 {{ backupStatus.snapshot_count }} 个快照，下表显示最近 {{ backupStatus.snapshots?.length || 0 }} 条
        </div>
        <el-table v-if="backupStatus.snapshots && backupStatus.snapshots.length > 0" :data="backupStatus.snapshots" stripe size="small" style="width:100%">
          <el-table-column label="时间" width="180">
            <template #default="{ row }">{{ new Date(row.time).toLocaleString() }}</template>
          </el-table-column>
          <el-table-column prop="hostname" label="主机" width="120" />
          <el-table-column label="标签" min-width="150">
            <template #default="{ row }">{{ (row.tags || []).join(', ') }}</template>
          </el-table-column>
          <el-table-column label="操作" width="120">
            <template #default="{ row }">
              <el-button size="small" type="warning" @click="confirmRestore(row)">恢复</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div v-else style="color:#999;text-align:center;padding:20px">暂无快照</div>
      </template>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useMobile } from '@/composables/useMobile'
import api from '../api'

const { isMobile } = useMobile()

const backupStatus = ref({
  initialized: false, snapshots: [], snapshot_count: 0, last_backup: '',
  service_ok: false, error: '', total_size_mb: 0, repo_size_mb: 0
})
const backupLoading = ref(false)
// statusLoaded：首次拿到 /backup/status 响应（含业务异常）后置 true，用于区分“加载中”与“已加载但异常”
const statusLoaded = ref(false)
// 加载态：请求中或尚未首次加载完成，各卡片/列表显示占位而非默认值
const statusLoading = computed(() => backupLoading.value || !statusLoaded.value)
const backupTriggering = ref(false)
const backupSaving = ref(false)
const cloudSaving = ref(false)
const backupForm = ref({ schedule: '0 2 * * *', retain_days: 7 })
const backupConfig = ref({ repo_path: '/data/backups/restic-repo-v2', data_dir: '/data', password_set: false, initialized: false })
const cloudForm = ref({ provider: 'none', bucket: '', key: '', secret: '', endpoint: '' })

const loadBackupStatus = async () => {
  backupLoading.value = true
  try {
    const { data } = await api.get('/backup/status')
    // 向后兼容：旧契约不返回 service_ok 字段，接口正常响应(200)即视为服务可用；
    // 仅当 service_ok === false（明确布尔 false）才触发异常告警，避免 !undefined===true 的假阳性。
    if (data.service_ok === undefined) {
      data.service_ok = true
      // 旧契约可能缺少 snapshot_count / repo_size_mb，从已有字段推导
      if (data.snapshot_count === undefined) {
        data.snapshot_count = Array.isArray(data.snapshots) ? data.snapshots.length : 0
      }
      if (data.repo_size_mb === undefined) {
        data.repo_size_mb = data.total_size_mb || 0
      }
    }
    backupStatus.value = data
    // 同步本地备份配置
    if (data.repo_path) backupConfig.value.repo_path = data.repo_path
    if (data.data_dir) backupConfig.value.data_dir = data.data_dir
    backupConfig.value.initialized = data.initialized !== false
    backupConfig.value.password_set = !!data.password_set
    // 同步云备份配置
    if (data.cloud_provider) cloudForm.value.provider = data.cloud_provider
    if (data.cloud_bucket) cloudForm.value.bucket = data.cloud_bucket
    statusLoaded.value = true
  } catch (e) {
    // 后端业务异常（容器未运行/密码错误等）通过 service_ok/error 返回而非抛错；
    // 此处 catch 主要兜网络/请求错误，不再静默吞掉，转为异常态展示
    backupStatus.value = { ...backupStatus.value, service_ok: false, error: '无法连接备份服务，请检查网络或稍后重试' }
    statusLoaded.value = true
    ElMessage.error('加载备份状态失败')
  } finally {
    backupLoading.value = false
  }
}

const doBackup = async () => {
  try {
    await ElMessageBox.confirm('确定立即执行一次全量备份？', '确认备份')
  } catch { return }
  backupTriggering.value = true
  try {
    const { data } = await api.post('/backup/trigger')
    if (data.success) {
      ElMessage.success('备份完成')
      loadBackupStatus()
    } else {
      ElMessage.error('备份失败: ' + (data.error || '未知错误'))
    }
  } catch (e) {
    ElMessage.error('备份失败: ' + (e.response?.data?.detail || e.message))
  }
  backupTriggering.value = false
}

const saveBackupSchedule = async () => {
  backupSaving.value = true
  try {
    await api.put('/backup/schedule', { schedule: backupForm.value.schedule, retain_days: backupForm.value.retain_days })
    ElMessage.success('备份计划已更新')
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
  }
  backupSaving.value = false
}

const confirmRestore = async (snapshot) => {
  try {
    await ElMessageBox.confirm(
      `确定从 ${new Date(snapshot.time).toLocaleString()} 的快照恢复？当前数据将被覆盖！`,
      '确认恢复',
      { type: 'warning', confirmButtonText: '确认恢复', cancelButtonText: '取消' }
    )
  } catch { return }
  try {
    const { data } = await api.post('/backup/restore', { snapshot_id: snapshot.id || snapshot.time })
    if (data.success) {
      ElMessage.success('恢复完成，请重启相关服务')
    } else {
      ElMessage.error('恢复失败: ' + (data.error || '未知错误'))
    }
  } catch (e) {
    ElMessage.error('恢复失败: ' + (e.response?.data?.detail || e.message))
  }
}

const saveCloudConfig = async () => {
  cloudSaving.value = true
  try {
    await api.put('/backup/cloud', {
      provider: cloudForm.value.provider,
      bucket: cloudForm.value.bucket,
      key: cloudForm.value.key,
      secret: cloudForm.value.secret,
      endpoint: cloudForm.value.endpoint
    })
    ElMessage.success('云备份配置已保存')
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
  }
  cloudSaving.value = false
}

onMounted(() => {
  loadBackupStatus()
})
</script>

<style scoped>
.backup-page { max-width: 800px; }
.stat-value { font-size: 20px; font-weight: 600; color: #303133; }
.stat-placeholder { font-size: 16px; font-weight: 400; color: #909399; }
</style>
