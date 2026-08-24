<template>
  <div class="network-page">
    <h2>网络配置</h2>
    <p class="page-desc">管理域名、访问方式与服务发布</p>

    <!-- 区块1：网络状态总览 -->
    <el-card style="max-width: 800px; width: 100%; margin-bottom: 20px">
      <template #header>
        <div class="card-header-row">
          <span style="font-weight:600">网络状态</span>
          <el-tag v-if="isConfigured" :type="statusConnected ? 'success' : 'warning'" size="small">
            {{ statusConnected ? '已连接' : '已配置' }}
          </el-tag>
          <el-tag v-else type="info" size="small">未配置</el-tag>
        </div>
      </template>
      <el-descriptions :column="isMobile ? 1 : 2" border>
        <el-descriptions-item label="访问方式">{{ accessModeLabel }}</el-descriptions-item>
        <el-descriptions-item label="域名">{{ domain || '未设置' }}</el-descriptions-item>
        <el-descriptions-item v-if="currentMode === 'cloudflare_tunnel' || currentMode === 'hybrid'" label="隧道状态">
          <el-tag :type="tunnelStatus.connected ? 'success' : 'danger'" size="small">
            {{ tunnelStatus.connected ? '已连接' : '未连接' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item v-if="currentMode === 'cloudflare_tunnel' || currentMode === 'hybrid'" label="Tunnel 中转服务">
          {{ tunnelStatus.routes?.length || 0 }} 个
        </el-descriptions-item>
      </el-descriptions>
    </el-card>

    <!-- 域名管理 -->
    <el-card style="max-width: 800px; width: 100%; margin-bottom: 20px" shadow="hover">
      <template #header>
        <div class="card-header-row">
          <span style="font-weight:600">🌐 域名管理</span>
          <el-button type="primary" size="small" @click="showAddDomain = true">
            <el-icon><Plus /></el-icon> 添加域名
          </el-button>
        </div>
      </template>
      <div v-for="(d, idx) in domains" :key="d.domain" class="domain-item">
        <div class="domain-item-row">
          <div>
            <span style="font-weight:500">{{ d.domain }}</span>
            <el-tag :type="d.status === 'active' ? 'success' : d.status === 'warning' ? 'warning' : 'danger'" size="small" style="margin-left: 8px">
              {{ d.status === 'active' ? '✅ 正常' : d.status === 'warning' ? '⚠️ 警告' : '❌ 异常' }}
            </el-tag>
          </div>
          <div class="domain-item-actions">
            <span class="domain-item-meta">
              DNS: {{ dnsProviderLabel(d.dns_provider) }} | 用途: {{ purposeLabel(d.purpose) }}
            </span>
            <el-button size="small" @click="verifyDomain(d.domain)" :loading="d.verifying">
              验证
            </el-button>
          </div>
        </div>
        <!-- 验证结果详情 -->
        <div v-if="d.checks" class="domain-verify-detail">
          <div v-for="(check, key) in d.checks" :key="key" class="verify-check-item">
            <span :class="check.ok ? 'text-green' : 'text-red'">
              {{ check.ok ? '✅' : '❌' }}
            </span>
            <span class="ml-1">{{ check.message }}</span>
          </div>
          <div v-if="d.errors && d.errors.length > 0" class="verify-errors">
            <div v-for="(err, i) in d.errors" :key="i" class="verify-error-item">
              ⚠️ {{ err }}
              <a href="/docs/network-config#troubleshooting" class="text-blue underline ml-1" target="_blank">
                查看修复指南
              </a>
            </div>
          </div>
        </div>
        <el-divider v-if="idx < domains.length - 1" />
      </div>
      <div v-if="domains.length === 0" class="domain-empty">暂无域名配置</div>
    </el-card>

    <!-- 区块2：当前配置管理 / 智能推荐 -->

    <!-- 场景A：未配置网络 - 智能推荐 -->
    <template v-if="!isConfigured">
      <el-card style="max-width: 800px; width: 100%; margin-bottom: 20px">
        <template #header><span style="font-weight:600">推荐方案</span></template>

        <!-- Tunnel 推荐卡片 -->
        <div class="scheme-card recommended" :class="{ active: selectedScheme === 'tunnel' }" @click="selectedScheme = 'tunnel'">
          <div class="scheme-header">
            <span class="scheme-name">Cloudflare Tunnel</span>
            <el-tag type="success" size="small">推荐</el-tag>
          </div>
          <div class="scheme-desc">无需开放端口，免公网 IP，访问不带端口号</div>
          <div class="scheme-detect" v-if="detectInfo">
            <el-tag size="small" type="info">检测到: {{ detectInfo }}</el-tag>
          </div>
          <el-button type="primary" size="large" @click.stop="showTunnelSetup = true" style="margin-top: 12px">
            一键接入
          </el-button>
        </div>

        <!-- 域名反代备选卡片 -->
        <div class="scheme-card" :class="{ active: selectedScheme === 'domain' }" @click="selectedScheme = 'domain'">
          <div class="scheme-header">
            <span class="scheme-name">域名反代 (Nginx)</span>
            <el-tag size="small">备选</el-tag>
          </div>
          <div class="scheme-desc">需开放端口，访问需带端口号（如 :8443）</div>
          <el-button size="large" @click.stop="showDomainSetup = true" style="margin-top: 12px">
            展开配置
          </el-button>
        </div>
      </el-card>
    </template>

    <!-- 场景B：Tunnel 已配置 - 管理界面 -->
    <template v-if="currentMode === 'cloudflare_tunnel' && isConfigured">
      <!-- 隧道状态卡片 -->
      <el-card style="max-width: 800px; width: 100%; margin-bottom: 20px">
        <template #header>
          <div class="card-header-row">
            <span style="font-weight:600">隧道状态</span>
            <div style="display:flex;align-items:center;gap:8px">
              <el-tag :type="tunnelStatus.connected ? 'success' : 'danger'" size="small">
                {{ tunnelStatus.connected ? '已连接' : '未连接' }}
              </el-tag>
              <el-button size="small" @click="loadTunnelStatus">刷新</el-button>
            </div>
          </div>
        </template>
        <el-descriptions :column="isMobile ? 1 : 2" border>
          <el-descriptions-item label="隧道名称">{{ tunnelStatus.tunnel_name }}</el-descriptions-item>
          <el-descriptions-item label="隧道 ID">
            <span style="font-family:monospace;font-size:12px">{{ tunnelStatus.tunnel_id }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="API Token">
            <span style="font-family:monospace;font-size:12px">{{ tunnelStatus.api_token_masked }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="主域名">{{ tunnelStatus.domain }}</el-descriptions-item>
        </el-descriptions>
        <div v-if="tunnelStatus.error" class="form-help" style="color:#e6a23c; margin-top: 8px">
          状态查询提示：{{ tunnelStatus.error }}
        </div>
        <!-- 重新接入折叠 -->
        <el-collapse style="margin-top: 16px">
          <el-collapse-item title="重新接入（更换 Token 或重新配置隧道）">
            <el-form label-width="100px">
              <el-form-item label="API Token">
                <el-input v-model="reconnectToken" placeholder="粘贴新的 Cloudflare API Token" type="password" show-password />
              </el-form-item>
              <el-form-item>
                <el-button type="primary" size="small" :loading="reconnecting" @click="handleReconnect">
                  重新接入
                </el-button>
              </el-form-item>
            </el-form>
          </el-collapse-item>
        </el-collapse>
      </el-card>

      <!-- 服务发布卡片 -->
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
              <el-button v-if="row.allPublished" type="danger" size="small" plain @click="unpublishAllHostnames(row)">
                取消发布
              </el-button>
              <el-button v-else-if="row.nonePublished" type="primary" size="small" @click="publishFirstAvailable(row)">
                发布
              </el-button>
              <el-button v-else type="warning" size="small" plain @click="publishFirstAvailable(row)">
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

    <!-- 场景C：域名反代 / 智能混合路由已配置 - 管理界面 -->
    <template v-if="(currentMode === 'domain' || currentMode === 'hybrid') && isConfigured">
      <el-alert
        v-if="currentMode === 'hybrid'"
        type="info"
        :closable="false"
        style="max-width: 800px; width: 100%; margin-bottom: 20px"
        title="智能混合路由：域名反代 + Tunnel 中转并存。大带宽服务走域名反代，轻量服务走 Tunnel 中转，可在下方「Tunnel 中转服务」中按服务切换。"
      />
      <el-card style="max-width: 800px; width: 100%; margin-bottom: 20px">
        <template #header><span style="font-weight:600">域名反代配置</span></template>
        <el-form :model="domainForm" label-width="120px">
          <el-form-item label="DNS 提供商">
            <el-select v-model="domainForm.dns_provider" style="width: 100%" @change="onDnsProviderChange">
              <el-option v-for="p in dnsProviders" :key="p.id" :label="p.name" :value="p.id">
                <span>{{ p.name }}</span>
                <span style="color: #909399; font-size: 12px; margin-left: 8px">{{ p.acme_plugin || '自定义插件' }}</span>
              </el-option>
            </el-select>
            <div class="form-help">{{ currentDnsProvider?.description }}</div>
          </el-form-item>
          <template v-if="currentDnsProvider">
            <el-form-item v-for="f in currentDnsProvider.fields" :key="f.key" :label="f.label">
              <el-input
                v-if="f.type !== 'textarea'"
                v-model="dnsCredentials[domainForm.dns_provider][f.key]"
                type="password" show-password
                :placeholder="dnsConfigured[domainForm.dns_provider]?.[f.key] ? '已配置，留空保持不变' : (f.placeholder || '请输入')"
              />
              <el-input v-else v-model="dnsCredentials[domainForm.dns_provider][f.key]" type="textarea" :rows="4" :placeholder="f.placeholder" />
              <div class="form-help" v-if="f.help">
                {{ f.help }}
                <a v-if="currentDnsProvider.help_url" :href="currentDnsProvider.help_url" target="_blank" style="margin-left:4px;color:#409eff">前往创建</a>
              </div>
              <el-tag v-if="dnsConfigured[domainForm.dns_provider]?.[f.key]" type="success" size="small" style="margin-top: 4px">
                已配置（留空则不修改）
              </el-tag>
            </el-form-item>
          </template>
          <el-form-item label="HTTPS 端口">
            <el-input-number v-model="domainForm.https_port" :min="1" :max="65535" />
          </el-form-item>
          <el-form-item label="管理面板子域名">
            <el-input v-model="domainForm.panel_subdomain" placeholder="panel">
              <template #append>.{{ domain }}</template>
            </el-input>
          </el-form-item>
          <el-form-item label="SSL 证书">
            <div style="display:flex;align-items:center;gap:8px">
              <el-tag :type="sslValid ? 'success' : 'warning'" size="small">{{ sslValid ? '有效' : '未配置' }}</el-tag>
              <span v-if="sslExpiry" style="font-size:12px;color:#909399">到期: {{ sslExpiry }}</span>
              <el-button size="small" @click="checkSSL" :loading="sslChecking">刷新</el-button>
            </div>
          </el-form-item>
          <el-form-item label="DNS 记录同步">
            <div style="width:100%">
              <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
                <el-tag v-if="dnsSync.ipv4" type="success" size="small">IPv4: {{ dnsSync.ipv4 }}</el-tag>
                <el-tag v-if="dnsSync.ipv6" type="info" size="small">IPv6: {{ dnsSync.ipv6 }}</el-tag>
                <el-button size="small" type="success" @click="syncDns" :loading="dnsSyncing">
                  立即同步 DNS 记录
                </el-button>
              </div>
              <div class="form-help" style="margin-top:4px">
                自动为所有服务子域名创建 A / AAAA 解析记录（指向服务器公网 IP），无需登录 DNS 网站手动配置
              </div>
              <!-- 同步结果 -->
              <el-alert
                v-if="dnsSyncResult.summary"
                :type="(dnsSyncResult.summary.failed || dnsSyncResult.summary.skipped) ? 'warning' : 'success'"
                :closable="false"
                style="margin-top:8px"
                :title="`同步完成：新建 ${dnsSyncResult.summary.created} 条，更新 ${dnsSyncResult.summary.updated} 条，无变化 ${dnsSyncResult.summary.unchanged} 条，跳过 ${dnsSyncResult.summary.skipped || 0} 条，失败 ${dnsSyncResult.summary.failed} 条`"
              />
              <div v-if="dnsSyncResult.summary && dnsSyncResult.summary.skipped" class="form-help" style="color:#e6a23c">
                {{ dnsSyncResult.summary.skipped }} 个子域名因已存在 CNAME 记录被跳过（可能已通过 Tunnel 中转发布）
              </div>
              <div v-if="dnsSyncResult.skippedList?.length" style="margin-top:6px">
                <div v-for="(s, i) in dnsSyncResult.skippedList" :key="i" class="form-help" style="color:#e6a23c">
                  {{ s.subdomain }}：{{ s.reason || '已存在 CNAME 记录，已跳过' }}
                </div>
              </div>
              <div v-if="dnsSyncResult.failures?.length" style="margin-top:6px">
                <div v-for="(f, i) in dnsSyncResult.failures" :key="i" class="form-help" style="color:#f56c6c">
                  {{ f.subdomain }} ({{ f.type }}): {{ f.error }}
                </div>
              </div>
            </div>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="saveDomainConfig" :loading="savingDomain">保存并应用</el-button>
            <el-button @click="regenerateNginx">重新生成 Nginx 配置</el-button>
          </el-form-item>
        </el-form>
      </el-card>

      <!-- Tunnel 中转服务卡片（域名反代 / 智能混合路由模式） -->
      <el-card style="max-width: 800px; width: 100%; margin-bottom: 20px">
        <template #header>
          <div class="card-header-row">
            <span style="font-weight:600">Tunnel 中转服务</span>
            <div style="display:flex;align-items:center;gap:8px">
              <el-button
                v-if="tunnelStatus.configured"
                size="small" type="success" plain
                :loading="smartConfiguring"
                :disabled="!!routeSwitchingId || smartConfiguring"
                @click="applySmartRouting"
              >
                智能推荐
              </el-button>
              <el-button size="small" :loading="tunnelLoading" @click="loadTunnelStatus">刷新</el-button>
            </div>
          </div>
        </template>

        <!-- Tunnel 未接入：友好引导 -->
        <div v-if="!tunnelStatus.configured" class="tunnel-guide">
          <div class="tunnel-guide-title">尚未接入 Cloudflare Tunnel</div>
          <p class="tunnel-guide-desc">
            当前所有服务都通过域名反代访问。接入 Cloudflare Tunnel 后，即可按服务选择路由方式：
            大带宽服务继续走域名反代，轻量服务改走 Tunnel 中转（免端口号、无需开放端口）。
          </p>
          <el-button type="primary" size="small" @click="showTunnelSetup = true">接入 Cloudflare Tunnel</el-button>
        </div>

        <!-- 已接入：服务路由列表 -->
        <template v-else>
          <el-table :data="tunnelStatus.services" size="small" v-loading="tunnelLoading" empty-text="暂无已安装的服务">
            <el-table-column label="服务" min-width="130">
              <template #default="{ row }">
                <span>{{ row.name }}</span>
              </template>
            </el-table-column>
            <el-table-column label="路由方式" width="110">
              <template #default="{ row }">
                <el-tag :type="row.published ? 'primary' : 'success'" size="small">
                  {{ row.published ? 'Tunnel 中转' : '域名反代' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="访问地址" min-width="200">
              <template #default="{ row }">
                <a v-if="row.hostname" :href="serviceUrl(row)" target="_blank" class="route-link">{{ serviceUrl(row) }}</a>
                <span v-else style="color:#909399">未配置域名</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="160">
              <template #default="{ row }">
                <el-button
                  :type="row.published ? 'success' : 'primary'"
                  size="small" plain
                  :loading="routeSwitchingId === row.module"
                  :disabled="!!routeSwitchingId || smartConfiguring"
                  @click="switchServiceRoute(row)"
                >
                  {{ row.published ? '切换为域名反代' : '切换为 Tunnel 中转' }}
                </el-button>
              </template>
            </el-table-column>
          </el-table>
          <div class="form-help" style="margin-top: 8px">
            域名反代：DNS AAAA → 服务器 IPv6 → Nginx SSL，适合大带宽服务（访问需带端口）；
            Tunnel 中转：DNS CNAME → Cloudflare 边缘，免端口号。切换后自动更新 DNS 记录。
          </div>
        </template>
      </el-card>
    </template>

    <!-- 场景D：IPv6 直连已配置 -->
    <template v-if="currentMode === 'ipv6_direct' && isConfigured">
      <el-card style="max-width: 800px; width: 100%; margin-bottom: 20px">
        <template #header><span style="font-weight:600">IPv6 直连</span></template>
        <el-alert type="info" :closable="false" style="margin-bottom: 16px">
          服务端口直接暴露在公网，通过 <code>http://[公网IPv6]:端口</code> 访问各服务，无需域名和 DNS。
        </el-alert>
        <el-table :data="serviceList" size="small" empty-text="暂无已安装的服务">
          <el-table-column prop="name" label="服务" min-width="120" />
          <el-table-column prop="port" label="端口" width="80" />
          <el-table-column label="访问地址" min-width="200">
            <template #default="{ row }">
              <span v-if="ipv6Addr" style="font-family:monospace;font-size:12px">http://[{{ ipv6Addr }}]:{{ row.port }}</span>
              <span v-else style="color:#909399">未检测到 IPv6 地址</span>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </template>

    <!-- 场景E：自由配置已配置 -->
    <template v-if="currentMode === 'custom' && isConfigured">
      <el-card style="max-width: 800px; width: 100%; margin-bottom: 20px">
        <template #header><span style="font-weight:600">自由配置</span></template>
        <el-alert type="info" :closable="false" style="margin-bottom: 16px">
          自由配置模式不会自动管理网络模块，你可以从应用商店自行安装和配置所需服务。
        </el-alert>
        <div style="margin-bottom: 12px; display: flex; gap: 8px">
          <el-button type="primary" size="small" @click="$router.push('/market')">前往应用商店</el-button>
          <el-button size="small" @click="regenerateNginx">重新生成 Nginx 配置</el-button>
        </div>
        <el-table :data="networkModules" size="small" empty-text="暂无网络模块">
          <el-table-column prop="name" label="模块" min-width="120" />
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="row.running ? 'success' : 'info'" size="small">{{ row.running ? '运行中' : '已停止' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="160">
            <template #default="{ row }">
              <el-button v-if="row.running" type="warning" size="small" @click="stopModule(row.id)">停止</el-button>
              <el-button v-else type="primary" size="small" @click="startModule(row.id)">启动</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </template>

    <!-- 区块3：高级选项（折叠区） -->
    <el-card style="max-width: 800px; width: 100%; margin-bottom: 20px">
      <el-collapse>
        <el-collapse-item title="高级选项">
          <div class="advanced-section">
            <div class="advanced-item">
              <div class="advanced-title">IPv6 直连</div>
              <div class="advanced-desc">直接用公网 IPv6 地址访问，无需域名和 DNS。通过 <code>http://[IPv6]:端口</code> 访问各服务。</div>
              <el-button size="small" :disabled="currentMode === 'ipv6_direct'" @click="switchMode('ipv6_direct')">
                {{ currentMode === 'ipv6_direct' ? '当前使用' : '切换到 IPv6 直连' }}
              </el-button>
            </div>
            <el-divider />
            <div class="advanced-item">
              <div class="advanced-title">自由配置</div>
              <div class="advanced-desc">不自动管理网络模块，自行从应用商店安装和配置所需服务。</div>
              <el-button size="small" :disabled="currentMode === 'custom'" @click="switchMode('custom')">
                {{ currentMode === 'custom' ? '当前使用' : '切换到自由配置' }}
              </el-button>
            </div>
            <el-divider v-if="isConfigured" />
            <div class="advanced-item" v-if="isConfigured">
              <div class="advanced-title">切换访问方式</div>
              <div class="advanced-desc">更改当前的访问方式，切换后可能会停止或启动相关模块。</div>
              <div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap">
                <el-button size="small" :disabled="currentMode === 'cloudflare_tunnel'" @click="switchMode('cloudflare_tunnel')">
                  Cloudflare Tunnel
                </el-button>
                <el-button size="small" :disabled="currentMode === 'domain'" @click="switchMode('domain')">
                  域名反代
                </el-button>
                <el-button size="small" :disabled="currentMode === 'hybrid'" @click="switchMode('hybrid')">
                  智能混合路由
                </el-button>
              </div>
              <div class="form-help" style="margin-top:8px">
                智能混合路由：域名反代 + Tunnel 中转并存，大带宽服务走域名反代，轻量服务走 Tunnel
              </div>
            </div>
          </div>
        </el-collapse-item>
      </el-collapse>
    </el-card>

    <!-- 区块4：SSL 配置（底部） -->
    <el-card style="max-width: 800px; width: 100%; margin-bottom: 20px">
      <template #header><span style="font-weight:600">🔒 SSL 配置</span></template>
      <el-form label-width="100px">
        <el-form-item label="SSL 邮箱">
          <el-input v-model="sslEmailInput" placeholder="admin@example.com" />
          <div class="form-help">用于 Let's Encrypt 自动签发 / 续签 SSL 证书</div>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="saveDomain" :loading="savingDomainInfo">保存</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- Tunnel 一键接入弹窗 -->
    <el-dialog v-model="showTunnelSetup" title="Cloudflare Tunnel 一键接入" :width="isMobile ? '95%' : '680px'" top="5vh" :close-on-click-modal="false">
      <el-steps :active="setupStep" align-center finish-status="success" style="margin-bottom: 20px">
        <el-step title="创建 API Token" />
        <el-step title="粘贴并验证" />
        <el-step title="自动接入" />
      </el-steps>
      <el-alert type="info" :closable="false" style="margin-bottom: 16px">
        <p style="margin: 0 0 8px"><b>只需在 Cloudflare 做一次操作</b>：创建一个 API Token，其余全部由 EasyServer 自动完成。</p>
        <ol style="margin: 0; padding-left: 20px; line-height: 1.8">
          <li>打开 <a href="https://dash.cloudflare.com/profile/api-tokens" target="_blank" style="color:#409eff">Cloudflare API Tokens</a></li>
          <li>点击 <b>Create Token</b> → 添加权限：<code>Account · Cloudflare Tunnel · Edit</code> + <code>Zone · DNS · Edit</code></li>
          <li>复制生成的 Token 粘贴到下方</li>
        </ol>
      </el-alert>
      <el-form label-width="100px">
        <el-form-item label="API Token" required>
          <el-input v-model="apiToken" placeholder="粘贴 Cloudflare API Token" type="password" show-password size="large" />
        </el-form-item>
        <el-form-item label="域名">
          <el-input :model-value="domain" disabled size="large" />
        </el-form-item>
        <el-collapse style="margin-bottom: 12px">
          <el-collapse-item title="高级选项（手动指定 Account ID，可选）">
            <el-input v-model="accountId" placeholder="如自动获取失败，粘贴 Account ID" />
          </el-collapse-item>
        </el-collapse>
        <el-form-item>
          <el-button type="primary" size="large" :loading="verifying" @click="handleVerify">验证 Token</el-button>
          <el-button type="success" size="large" :loading="settingUp" :disabled="!verified" @click="handleSetup">一键接入</el-button>
        </el-form-item>
      </el-form>
      <!-- 验证结果 -->
      <div v-if="verifyResult" style="margin-top: 8px">
        <el-result v-if="verifyResult.valid" icon="success" title="Token 有效" sub-title="点击「一键接入」自动创建隧道并发布服务" />
        <el-alert v-else type="error" :closable="false" :title="'Token 无效：' + (verifyResult.error || '未知错误')" />
      </div>
      <!-- 接入日志 -->
      <div v-if="setupLogs.length" style="margin-top: 12px">
        <div v-for="(log, i) in setupLogs" :key="i" class="log-line">
          <el-tag :type="log.ok ? 'success' : 'danger'" size="small">{{ log.ok ? '✓' : '✗' }}</el-tag>
          <span>{{ log.msg }}</span>
        </div>
        <el-alert v-if="setupDone" type="success" :closable="false" title="接入完成！" style="margin-top: 8px" />
        <el-alert v-if="setupWarning" type="warning" :closable="false" :title="setupWarning" style="margin-top: 8px" />
      </div>
    </el-dialog>

    <!-- 添加域名对话框 -->
    <el-dialog v-model="showAddDomain" title="添加域名" width="500px">
      <el-form :model="newDomainForm" label-width="100px">
        <el-form-item label="域名">
          <el-input v-model="newDomainForm.domain" placeholder="例如：mytunnel.dpdns.org" />
        </el-form-item>
        <el-form-item label="DNS 提供商">
          <el-select v-model="newDomainForm.dns_provider" placeholder="选择 DNS 提供商">
            <el-option v-for="p in dnsProviders" :key="p.id" :label="p.name" :value="p.id" />
            <el-option v-if="!dnsProviders.length" label="阿里云" value="aliyun" />
            <el-option v-if="!dnsProviders.length" label="Cloudflare" value="cloudflare" />
          </el-select>
        </el-form-item>
        <el-form-item label="用途">
          <el-select v-model="newDomainForm.purpose" placeholder="选择用途">
            <el-option label="域名反代（Nginx）" value="nginx" />
            <el-option label="Tunnel 中转" value="tunnel" />
            <el-option label="两者兼用" value="both" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAddDomain = false">取消</el-button>
        <el-button type="primary" @click="addDomain" :loading="addingDomain">添加</el-button>
      </template>
    </el-dialog>

    <!-- 域名反代配置弹窗 -->
    <el-dialog v-model="showDomainSetup" title="域名反代配置" :width="isMobile ? '95%' : '680px'" top="5vh" :close-on-click-modal="false">
      <el-form :model="domainForm" label-width="120px">
        <el-form-item label="DNS 提供商">
          <el-select v-model="domainForm.dns_provider" style="width: 100%" @change="onDnsProviderChange">
            <el-option v-for="p in dnsProviders" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <template v-if="currentDnsProvider">
          <el-form-item v-for="f in currentDnsProvider.fields" :key="f.key" :label="f.label">
            <el-input
              v-if="f.type !== 'textarea'"
              v-model="dnsCredentials[domainForm.dns_provider][f.key]"
              type="password" show-password
              :placeholder="f.placeholder || '请输入'"
            />
            <el-input v-else v-model="dnsCredentials[domainForm.dns_provider][f.key]" type="textarea" :rows="3" :placeholder="f.placeholder" />
            <div class="form-help" v-if="f.help">{{ f.help }}</div>
          </el-form-item>
        </template>
        <el-form-item label="HTTPS 端口">
          <el-input-number v-model="domainForm.https_port" :min="1" :max="65535" />
        </el-form-item>
        <el-form-item label="SSL 邮箱">
          <el-input v-model="domainForm.ssl_email" placeholder="admin@example.com" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="applyDomainMode" :loading="savingDomain">保存并应用</el-button>
        </el-form-item>
      </el-form>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox, ElLoading } from 'element-plus'
import { Plus, TopRight } from '@element-plus/icons-vue'
import api from '../api'

// 网络模式切换涉及模块安装与启动，首次切换耗时较长，单独放宽超时（10 分钟），
// 其他普通 API 请求仍保持全局 30s 超时不受影响
const NETWORK_SWITCH_TIMEOUT = 10 * 60 * 1000
const SWITCH_LOADING_TEXT = '正在切换访问方式，首次切换需安装并启动相关模块，可能需要几分钟，请勿关闭页面'

const isMobile = ref(false)
const checkMobile = () => { isMobile.value = window.innerWidth < 768 }
onMounted(() => { checkMobile(); window.addEventListener('resize', checkMobile) })
onUnmounted(() => { window.removeEventListener('resize', checkMobile) })

// ===== 基础状态 =====
const domain = ref('')
const sslEmailInput = ref('')
const currentMode = ref('domain')
const isConfigured = ref(false)
const savingDomainInfo = ref(false)

const accessModeLabels = {
  cloudflare_tunnel: 'Cloudflare Tunnel',
  domain: '域名反代 (Nginx)',
  ipv6_direct: 'IPv6 直连',
  custom: '自由配置',
  hybrid: '智能混合路由'
}
const accessModeLabel = computed(() => accessModeLabels[currentMode.value] || '未配置')

// ===== 域名管理 =====
const domains = ref([])
const showAddDomain = ref(false)
const addingDomain = ref(false)
const newDomainForm = ref({ domain: '', dns_provider: 'cloudflare', purpose: 'tunnel' })
const selectedTunnelDomain = ref('')

const tunnelDomains = computed(() =>
  domains.value.filter(d => d.purpose === 'tunnel' || d.purpose === 'both')
)

// 将服务列表展开为每行一个 hostname 的格式
const publishableRows = computed(() => {
  const services = tunnelStatus.value?.services || []
  const routeHostnames = new Set((tunnelStatus.value?.routes || []).map(r => r.hostname))
  const rows = []
  for (const svc of services) {
    const hostnames = svc.all_hostnames?.length ? svc.all_hostnames : (svc.hostname ? [svc.hostname] : [])
    for (const h of hostnames) {
      rows.push({
        module: svc.module,
        name: svc.name,
        subdomain: svc.subdomain,
        port: svc.port,
        hostname: h,
        // 提取该 hostname 对应的域名
        domain: hostnames.length > 1 ? h.split('.').slice(1).join('.') : '',
        published: routeHostnames.has(h),
      })
    }
  }
  return rows
})

// 按服务分组的数据（每个服务一行）
const groupedServices = computed(() => {
  const services = tunnelStatus.value?.services || []
  const routeHostnames = new Set((tunnelStatus.value?.routes || []).map(r => r.hostname))
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

const loadDomains = async () => {
  try {
    const res = await api.get('/config/domains')
    domains.value = res.data.domains || []
    if (tunnelDomains.value.length > 0 && !selectedTunnelDomain.value) {
      selectedTunnelDomain.value = tunnelDomains.value[0].domain
    }
  } catch (e) {
    console.error('加载域名失败:', e)
  }
}

const verifyDomain = async (domain) => {
  const d = domains.value.find(x => x.domain === domain)
  if (d) d.verifying = true
  try {
    const res = await api.post(`/config/domains/${domain}/verify`)
    const result = res.data
    if (d) {
      d.status = result.status
      d.checks = result.checks
      d.errors = result.errors
    }
    if (result.status === 'active') {
      ElMessage.success(`${domain} 验证通过`)
    } else {
      ElMessage.warning(`${domain} 验证发现问题：${result.errors.join('; ')}`)
    }
  } catch (e) {
    ElMessage.error('验证失败: ' + (e.response?.data?.detail || '未知错误'))
  } finally {
    if (d) d.verifying = false
  }
}

const addDomain = async () => {
  addingDomain.value = true
  try {
    const res = await api.post('/config/domains', newDomainForm.value)
    const verify = res.data.verify
    if (verify && verify.status === 'active') {
      ElMessage.success(`域名 ${newDomainForm.value.domain} 添加成功，验证通过！`)
    } else if (verify) {
      ElMessage.warning(`域名已添加，但验证发现问题：${verify.errors?.join('; ') || '请手动验证'}`)
    } else {
      ElMessage.success('域名添加成功')
    }
    showAddDomain.value = false
    newDomainForm.value = { domain: '', dns_provider: 'cloudflare', purpose: 'tunnel' }
    await loadDomains()
  } catch (e) {
    ElMessage.error('添加失败: ' + (e.response?.data?.detail || '未知错误'))
  } finally {
    addingDomain.value = false
  }
}

const dnsProviderLabel = (provider) => {
  const map = { aliyun: '阿里云', cloudflare: 'Cloudflare', dnspod: 'DNSPod' }
  return map[provider] || provider
}
const purposeLabel = (purpose) => {
  const map = { nginx: '域名反代', tunnel: 'Tunnel 中转', both: '反代 + Tunnel' }
  return map[purpose] || purpose
}

// ===== 智能推荐 =====
const selectedScheme = ref('tunnel')
const detectInfo = ref('')
const showTunnelSetup = ref(false)
const showDomainSetup = ref(false)

// ===== Tunnel 状态 =====
const tunnelStatus = ref({ configured: false, connected: false, routes: [], services: [] })
const tunnelLoading = ref(false)
const publishingId = ref('')
const reconnectToken = ref('')
const reconnecting = ref(false)

// Tunnel 接入状态
const apiToken = ref('')
const accountId = ref('')
const verifying = ref(false)
const settingUp = ref(false)
const verified = ref(false)
const verifyResult = ref(null)
const setupStep = ref(0)
const setupLogs = ref([])
const setupDone = ref(false)
const setupWarning = ref('')

const statusConnected = computed(() => {
  if (currentMode.value === 'cloudflare_tunnel') return tunnelStatus.value.connected
  return isConfigured.value
})

// ===== 域名反代配置 =====
const domainForm = ref({
  dns_provider: 'aliyun', https_port: 8443, ssl_email: '', panel_subdomain: 'panel'
})
const dnsProviders = ref([])
const dnsCredentials = ref({ aliyun: {}, cloudflare: {} })
const dnsConfigured = ref({})
const savingDomain = ref(false)
const sslValid = ref(false)
const sslExpiry = ref('')
const sslChecking = ref(false)

const currentDnsProvider = computed(() =>
  dnsProviders.value.find(p => p.id === domainForm.value.dns_provider) || null
)

// ===== DNS 记录同步 =====
const dnsSync = ref({ ipv4: '', ipv6: '' })
const dnsSyncing = ref(false)
const dnsSyncResult = ref({})

const loadDnsStatus = async () => {
  try {
    const { data } = await api.get('/dns/status')
    dnsSync.value = { ipv4: data.public_ipv4 || '', ipv6: data.public_ipv6 || '' }
  } catch { /* 忽略 */ }
}

const syncDns = async () => {
  dnsSyncing.value = true
  try {
    const { data } = await api.post('/dns/sync')
    const summary = data.summary || {}
    // skipped 为后端新增字段，旧版本缺失时按 0 容错
    summary.skipped = summary.skipped || 0
    dnsSyncResult.value = {
      summary,
      failures: (data.results || []).filter(r => !r.success && r.action !== 'skipped'),
      skippedList: (data.results || []).filter(r => r.action === 'skipped')
    }
    if (summary.failed) {
      ElMessage.warning(`DNS 同步完成，但 ${summary.failed} 条记录失败，请检查凭证`)
    } else if (summary.skipped) {
      ElMessage.warning(`DNS 同步完成：${summary.skipped} 个子域名因已存在 CNAME 记录被跳过（可能已通过 Tunnel 发布）`)
    } else {
      ElMessage.success(`DNS 同步完成：新建 ${summary.created} 条，更新 ${summary.updated} 条，无变化 ${summary.unchanged} 条`)
    }
    loadDnsStatus()
  } catch (e) {
    ElMessage.error('DNS 同步失败: ' + (e.response?.data?.detail || e.message))
  }
  dnsSyncing.value = false
}

// ===== IPv6 =====
const ipv6Addr = ref('')
const serviceList = ref([])

// ===== 自由配置 =====
const networkModules = ref([])

// ===== 数据加载 =====
const loadConfig = async () => {
  try {
    const { data } = await api.get('/config')
    const cfg = data.config || {}
    const env = data.env_summary || {}
    domain.value = env.DOMAIN || cfg.domain || ''
    sslEmailInput.value = cfg.ssl_email || ''
    // hybrid 模式作为「智能混合路由」正常展示，不再归一化
    const rawMode = env.ACCESS_MODE || cfg.access_mode || 'domain'
    currentMode.value = rawMode
    isConfigured.value = !!data.network_configured || !!cfg.network_configured

    // DNS 提供商
    dnsProviders.value = data.dns_providers || []
    const masked = data.dns_credentials || {}
    const configured = data.dns_credentials_configured || {}
    dnsProviders.value.forEach(p => {
      if (!dnsCredentials.value[p.id]) dnsCredentials.value[p.id] = {}
      if (!dnsConfigured.value[p.id]) dnsConfigured.value[p.id] = {}
      p.fields.forEach(f => {
        dnsCredentials.value[p.id][f.key] = masked[p.id]?.[f.key] || ''
        dnsConfigured.value[p.id][f.key] = !!configured[p.id]?.[f.key]
      })
    })

    domainForm.value.dns_provider = cfg.dns_provider || 'aliyun'
    domainForm.value.https_port = parseInt(env.HTTPS_PORT) || cfg.https_port || 8443
    domainForm.value.ssl_email = cfg.ssl_email || ''
    domainForm.value.panel_subdomain = cfg.panel_subdomain || 'panel'

    // 检测信息
    if (domain.value) {
      detectInfo.value = `域名 ${domain.value} 已配置`
    }

    // SSL 状态
    const ssl = data.ssl_status || {}
    sslValid.value = !!ssl.ssl_valid
    sslExpiry.value = ssl.ssl_expiry || ''

    // 多域名列表（直接从 config 响应中提取，避免额外 API 调用）
    domains.value = data.domains || []
    if (tunnelDomains.value.length > 0 && !selectedTunnelDomain.value) {
      selectedTunnelDomain.value = tunnelDomains.value[0].domain
    }
  } catch (e) {
    ElMessage.error('加载配置失败')
  }
}

const loadTunnelStatus = async () => {
  tunnelLoading.value = true
  try {
    const { data } = await api.get('/cloudflare/status')
    tunnelStatus.value = data
  } catch (e) {
    // Tunnel 未配置时忽略错误
  } finally {
    tunnelLoading.value = false
  }
}

const loadServices = async () => {
  try {
    const { data } = await api.get('/services')
    serviceList.value = (data.services || [])
      .filter(s => s.port)
      .map(s => ({ name: s.name || s.module, port: s.port }))

    // 加载网络模块状态（自由配置模式用）
    const netIds = ['nginx', 'acme', 'ddns-go', 'cloudflare-tunnel']
    networkModules.value = (data.services || [])
      .filter(s => netIds.includes(s.module))
      .map(s => ({ id: s.module, name: s.name || s.module, running: s.running }))
  } catch (e) { /* ignore */ }
}

const detectIPv6 = async () => {
  // 简单检测：尝试获取 IPv6 地址
  try {
    const { data } = await api.get('/config')
    // 从环境检测，或调用外部接口
    // 这里简单用 config 数据判断
    ipv6Addr.value = '' // 暂时留空，后续可扩展
  } catch { /* ignore */ }
}

// ===== Tunnel 接入逻辑（迁移自 TunnelManager）=====
const handleVerify = async () => {
  if (!apiToken.value) { ElMessage.warning('请先粘贴 API Token'); return }
  verifying.value = true
  verifyResult.value = null
  try {
    const { data } = await api.post('/cloudflare/verify', { api_token: apiToken.value })
    verifyResult.value = data
    if (data.valid) { verified.value = true; setupStep.value = 1 }
    if (data.account_id && !accountId.value) accountId.value = data.account_id
  } catch (e) {
    verifyResult.value = { valid: false, error: e.response?.data?.detail || e.message }
    verified.value = false
  }
  verifying.value = false
}

const handleSetup = async () => {
  if (!apiToken.value) return
  settingUp.value = true
  setupLogs.value = []
  setupDone.value = false
  setupWarning.value = ''
  setupStep.value = 2
  try {
    setupLogs.value.push({ msg: '正在创建/复用隧道...', ok: true })
    const payload = { api_token: apiToken.value }
    if (accountId.value) payload.account_id = accountId.value
    const { data } = await api.post('/cloudflare/setup', payload)
    setupLogs.value.push({ msg: `隧道就绪：${data.tunnel_name} (${data.tunnel_id})`, ok: true })
    if (data.zone_warning) {
      setupWarning.value = data.zone_warning
      setupLogs.value.push({ msg: data.zone_warning, ok: false })
    }
    const failed = (data.results || []).filter(r => !r.success)
    if (failed.length) {
      setupLogs.value.push({ msg: '容器启动失败: ' + (failed[0].error || '未知错误'), ok: false })
    } else {
      setupLogs.value.push({ msg: 'cloudflare-tunnel 容器已启动', ok: true })
    }
    setupDone.value = true
    setupStep.value = 3
    setTimeout(() => {
      loadTunnelStatus()
      loadConfig()
    }, 3000)
    ElMessage.success('接入完成！请等待隧道连接后发布服务')
  } catch (e) {
    setupLogs.value.push({ msg: '接入失败: ' + (e.response?.data?.detail || e.message), ok: false })
    setupDone.value = false
  }
  settingUp.value = false
}

const handleReconnect = async () => {
  if (!reconnectToken.value) { ElMessage.warning('请输入新的 API Token'); return }
  reconnecting.value = true
  try {
    apiToken.value = reconnectToken.value
    verified.value = false
    setupStep.value = 0
    setupLogs.value = []
    await handleVerify()
    if (verified.value) {
      await handleSetup()
    }
    reconnectToken.value = ''
  } finally {
    reconnecting.value = false
  }
}

const publishService = async (row) => {
  // row 已经包含具体的 hostname 和 domain
  const targetDomain = row.domain || selectedTunnelDomain.value || tunnelDomains.value[0]?.domain || ''
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
  publishingId.value = row.module + row.hostname
  try {
    const { data } = await api.post('/cloudflare/publish', {
      subdomain: row.subdomain, port: row.port,
      domain: targetDomain
    })
    ElMessage.success(data.message || '发布成功')
    if (data.dns_warning) ElMessage.warning(data.dns_warning)
    loadTunnelStatus()
  } catch (e) {
    ElMessage.error('发布失败: ' + (e.response?.data?.detail || e.message))
  }
  publishingId.value = ''
}

const unpublishRoute = async (hostname) => {
  try { await ElMessageBox.confirm(`确定取消发布 ${hostname}？`, '确认操作') } catch { return }
  try {
    const { data } = await api.post('/cloudflare/unpublish', { hostname })
    ElMessage.success(`已取消发布 ${hostname}`)
    if (data.warnings?.length) data.warnings.forEach(w => ElMessage.warning(w))
    loadTunnelStatus()
  } catch (e) {
    ElMessage.error('操作失败: ' + (e.response?.data?.detail || e.message))
  }
}

// 取消发布服务的所有 hostname
const unpublishAllHostnames = async (row) => {
  const hostnames = row.hostnames.filter(h => h.published).map(h => h.hostname)
  try {
    await ElMessageBox.confirm(
      `确定取消发布以下地址？\n\n${hostnames.join('\n')}`,
      '确认操作'
    )
  } catch { return }
  publishingId.value = 'unpublish-' + row.module
  try {
    for (const hostname of hostnames) {
      const { data } = await api.post('/cloudflare/unpublish', { hostname })
      if (data.warnings?.length) data.warnings.forEach(w => ElMessage.warning(w))
    }
    ElMessage.success(`已取消发布 ${hostnames.length} 个地址`)
    loadTunnelStatus()
  } catch (e) {
    ElMessage.error('操作失败: ' + (e.response?.data?.detail || e.message))
  }
  publishingId.value = ''
}

// 发布服务的第一个未发布的 hostname（或全部未发布时发布第一个）
const publishFirstAvailable = async (row) => {
  // 找到第一个未发布的 hostname
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

// ===== 混合路由：按服务切换路由方式 =====
const routeSwitchingId = ref('')
const smartConfiguring = ref(false)

// 智能推荐分组：大带宽服务走域名反代，轻量服务走 Tunnel 中转
const SMART_DIRECT_MODULES = ['frigate', 'nextcloud', 'jellyfin', 'filebrowser', 'calibre-web']
const SMART_TUNNEL_MODULES = ['notediscovery', 'joplin', 'uptime-kuma']

// 服务访问地址：Tunnel 中转免端口，域名反代带 https_port（动态读取配置，不硬编码）
const serviceUrl = (row) => {
  if (row.published) return `https://${row.hostname}`
  return `https://${row.hostname}:${domainForm.value.https_port}`
}

const switchServiceRoute = async (row) => {
  routeSwitchingId.value = row.module
  try {
    if (row.published) {
      const { data } = await api.post('/cloudflare/unpublish', { hostname: row.hostname })
      ElMessage.success(`${row.name} 已切换为域名反代`)
      if (data.warnings?.length) data.warnings.forEach(w => ElMessage.warning(w))
    } else {
      const { data } = await api.post('/cloudflare/publish', { subdomain: row.subdomain, port: row.port, ...(selectedTunnelDomain.value ? { domain: selectedTunnelDomain.value } : {}) })
      ElMessage.success(`${row.name} 已切换为 Tunnel 中转`)
      if (data.dns_warning) ElMessage.warning(data.dns_warning)
    }
    await loadTunnelStatus()
  } catch (e) {
    ElMessage.error('切换失败: ' + (e.response?.data?.detail || e.message))
  }
  routeSwitchingId.value = ''
}

const applySmartRouting = async () => {
  const services = tunnelStatus.value.services || []
  const toTunnel = services.filter(s => SMART_TUNNEL_MODULES.includes(s.module) && !s.published)
  const toDirect = services.filter(s => SMART_DIRECT_MODULES.includes(s.module) && s.published)
  if (!toTunnel.length && !toDirect.length) {
    ElMessage.info('当前路由配置已符合智能推荐，无需调整')
    return
  }
  const lines = []
  if (toTunnel.length) lines.push(`切换为 Tunnel 中转：${toTunnel.map(s => s.name).join('、')}`)
  if (toDirect.length) lines.push(`切换为域名反代：${toDirect.map(s => s.name).join('、')}`)
  try {
    await ElMessageBox.confirm(
      `智能推荐将按以下规则调整服务路由：\n${lines.join('\n')}\n其余服务保持当前路由方式不变。`,
      '智能推荐',
      { confirmButtonText: '开始配置', cancelButtonText: '取消', type: 'info' }
    )
  } catch { return }

  smartConfiguring.value = true
  const failed = []
  let okCount = 0
  for (const s of toTunnel) {
    try {
      const { data } = await api.post('/cloudflare/publish', { subdomain: s.subdomain, port: s.port, ...(selectedTunnelDomain.value ? { domain: selectedTunnelDomain.value } : {}) })
      okCount++
      if (data.dns_warning) ElMessage.warning(`${s.name}: ${data.dns_warning}`)
    } catch (e) {
      failed.push(`${s.name}（Tunnel 中转）`)
    }
  }
  for (const s of toDirect) {
    try {
      await api.post('/cloudflare/unpublish', { hostname: s.hostname })
      okCount++
    } catch (e) {
      failed.push(`${s.name}（域名反代）`)
    }
  }
  smartConfiguring.value = false
  await loadTunnelStatus()
  if (failed.length) {
    ElMessage.warning(`智能配置完成：成功 ${okCount} 项，失败 ${failed.length} 项（${failed.join('、')}），可单独重试`)
  } else {
    ElMessage.success('智能配置完成：大带宽服务走域名反代，轻量服务走 Tunnel 中转')
  }
}

// ===== 域名反代配置 =====
const onDnsProviderChange = () => {
  if (!dnsCredentials.value[domainForm.value.dns_provider]) {
    dnsCredentials.value[domainForm.value.dns_provider] = {}
    dnsConfigured.value[domainForm.value.dns_provider] = {}
    const p = currentDnsProvider.value
    if (p) {
      p.fields.forEach(f => {
        dnsCredentials.value[domainForm.value.dns_provider][f.key] = ''
        dnsConfigured.value[domainForm.value.dns_provider][f.key] = false
      })
    }
  }
}

const applyDomainMode = async () => {
  savingDomain.value = true
  const loading = ElLoading.service({ lock: true, text: SWITCH_LOADING_TEXT, background: 'rgba(0, 0, 0, 0.6)' })
  try {
    const provider = domainForm.value.dns_provider
    const creds = {}
    const p = currentDnsProvider.value
    if (p) {
      p.fields.forEach(f => {
        const v = dnsCredentials.value[provider]?.[f.key]
        if (v && !v.startsWith('***')) creds[f.key] = v
      })
    }
    await api.post('/config/network', {
      access_mode: 'domain',
      dns_provider: provider,
      dns_credentials: { [provider]: creds },
      https_port: domainForm.value.https_port
    }, { timeout: NETWORK_SWITCH_TIMEOUT })
    showDomainSetup.value = false
    ElMessage.success('域名反代已配置并应用')
    loadConfig()
    loadDnsStatus()
  } catch (e) {
    ElMessage.error('配置失败: ' + (e.response?.data?.detail || e.message))
  }
  loading.close()
  savingDomain.value = false
}

const saveDomainConfig = async () => {
  savingDomain.value = true
  try {
    const provider = domainForm.value.dns_provider
    const creds = {}
    const p = currentDnsProvider.value
    if (p) {
      p.fields.forEach(f => {
        const v = dnsCredentials.value[provider]?.[f.key]
        if (v && !v.startsWith('***')) creds[f.key] = v
      })
    }
    await api.put('/config', {
      dns_provider: provider,
      dns_credentials: { [provider]: creds },
      https_port: domainForm.value.https_port,
      panel_subdomain: domainForm.value.panel_subdomain,
      ssl_email: domainForm.value.ssl_email
    })
    await api.post('/nginx/generate')
    ElMessage.success('配置已保存并应用')
    loadConfig()
    loadDnsStatus()
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
  }
  savingDomain.value = false
}

const regenerateNginx = async () => {
  try {
    await api.post('/nginx/generate')
    ElMessage.success('Nginx 配置已重新生成')
  } catch (e) {
    ElMessage.error('生成失败: ' + (e.response?.data?.detail || e.message))
  }
}

const checkSSL = async () => {
  sslChecking.value = true
  try {
    const { data } = await api.get('/config')
    const ssl = data.ssl_status || {}
    sslValid.value = !!ssl.ssl_valid
    sslExpiry.value = ssl.ssl_expiry || ''
  } catch {
    sslValid.value = false; sslExpiry.value = ''
  }
  sslChecking.value = false
}

// ===== SSL 邮箱保存 =====
const saveDomain = async () => {
  savingDomainInfo.value = true
  try {
    await api.put('/config', { ssl_email: sslEmailInput.value })
    ElMessage.success('SSL 邮箱已保存')
    loadConfig()
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
  }
  savingDomainInfo.value = false
}

// ===== 切换模式 =====
const switchMode = async (mode) => {
  const modeLabel = accessModeLabels[mode] || mode
  try {
    await ElMessageBox.confirm(
      `确定切换到「${modeLabel}」？\n切换后可能会停止当前正在使用的网络模块。`,
      '切换访问方式',
      { confirmButtonText: '确认切换', cancelButtonText: '取消', type: 'warning' }
    )
  } catch { return }

  const loading = ElLoading.service({ lock: true, text: SWITCH_LOADING_TEXT, background: 'rgba(0, 0, 0, 0.6)' })
  try {
    await api.post('/config/network', { access_mode: mode }, { timeout: NETWORK_SWITCH_TIMEOUT })
    ElMessage.success(`已切换到 ${modeLabel}`)
    loadConfig()
    loadTunnelStatus()
    loadServices()
  } catch (e) {
    ElMessage.error('切换失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    loading.close()
  }
}

// ===== 自由配置模块操作 =====
const startModule = async (moduleId) => {
  try {
    await api.post(`/services/${moduleId}/start`)
    ElMessage.success(`${moduleId} 已启动`)
    loadServices()
  } catch (e) { ElMessage.error('启动失败: ' + (e.response?.data?.detail || e.message)) }
}

const stopModule = async (moduleId) => {
  try {
    await ElMessageBox.confirm(`确定停止 ${moduleId}？`, '确认操作')
  } catch { return }
  try {
    await api.post(`/services/${moduleId}/stop`)
    ElMessage.success(`${moduleId} 已停止`)
    loadServices()
  } catch (e) { ElMessage.error('停止失败: ' + (e.response?.data?.detail || e.message)) }
}

// ===== 初始化 =====
onMounted(async () => {
  await loadConfig()
  loadTunnelStatus()
  loadServices()
  detectIPv6()
  loadDnsStatus()
})
</script>

<style scoped>
.network-page { max-width: 840px; }
.page-desc { color: #909399; margin: 4px 0 20px; font-size: 14px; }
.card-header-row { display: flex; justify-content: space-between; align-items: center; }

.scheme-card {
  padding: 20px; border: 2px solid #e4e7ed; border-radius: 12px;
  cursor: pointer; transition: all 0.2s; margin-bottom: 12px;
}
.scheme-card:hover { border-color: #409eff; background: #f5f7fa; }
.scheme-card.active { border-color: #409eff; background: #ecf5ff; }
.scheme-card.recommended { border-color: #67c23a; }
.scheme-card.recommended.active { border-color: #67c23a; background: #f0f9eb; }
.scheme-header { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.scheme-name { font-weight: 600; font-size: 15px; }
.scheme-desc { font-size: 13px; color: #909399; }
.scheme-detect { margin-top: 8px; }

.route-row {
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 0; border-bottom: 1px solid #f0f2f5;
}
.route-row:last-child { border-bottom: none; }
.route-info { display: flex; flex-direction: column; gap: 2px; }
.route-link { color: #409eff; font-weight: 600; font-size: 13px; }
.route-service { font-size: 12px; color: #909399; font-family: monospace; }

.tunnel-guide { padding: 12px 4px; }
.tunnel-guide-title { font-weight: 600; font-size: 14px; color: #606266; margin-bottom: 6px; }
.tunnel-guide-desc { font-size: 13px; color: #909399; line-height: 1.6; margin: 0 0 12px; }

.log-line { display: flex; align-items: center; gap: 8px; padding: 4px 0; font-size: 13px; }

.form-help { font-size: 12px; color: #909399; margin-top: 4px; line-height: 1.5; }
.form-help a { color: #409eff; text-decoration: none; }

.advanced-section { padding: 4px 0; }
.advanced-item { padding: 8px 0; }
.advanced-title { font-weight: 600; font-size: 14px; margin-bottom: 4px; }
.advanced-desc { font-size: 13px; color: #909399; margin-bottom: 8px; line-height: 1.5; }
.advanced-desc code { background: #f0f2f5; padding: 1px 4px; border-radius: 3px; font-size: 12px; }

.domain-item { padding: 2px 0; }
.domain-item-row { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }
.domain-item-actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.domain-item-meta { font-size: 12px; color: #909399; }
.domain-empty { text-align: center; padding: 16px 0; color: #c0c4cc; font-size: 14px; }
.domain-selector-bar { display: flex; align-items: center; margin-bottom: 12px; }
.domain-selector-label { font-size: 13px; color: #909399; white-space: nowrap; margin-right: 8px; }

.domain-verify-detail {
  margin-top: 8px; padding: 8px 12px; background: #f5f7fa; border-radius: 6px;
  font-size: 13px; line-height: 1.6;
}
.verify-check-item { display: flex; align-items: center; gap: 4px; }
.verify-errors { margin-top: 6px; }
.verify-error-item { color: #f56c6c; font-size: 12px; line-height: 1.6; }
.text-green { color: #67c23a; }
.text-red { color: #f56c6c; }
.text-blue { color: #409eff; }
.ml-1 { margin-left: 4px; }
.underline { text-decoration: underline; }
</style>
