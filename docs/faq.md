# 常见问题解答

## 服务无法启动怎么办？

### 排查步骤

1. **查看服务日志**：在「服务管理」页面点击对应服务的「查看日志」按钮
2. **检查端口冲突**：确认服务所需端口未被其他程序占用
3. **检查配置**：确认 `.env` 文件中的配置参数正确
4. **检查磁盘空间**：`df -h` 确认磁盘未满

### 常见原因及解决

| 原因 | 解决方法 |
|------|---------|
| 端口被占用 | 修改服务端口或停止占用端口的程序 |
| 内存不足 | 增加服务器内存或减少运行的服务数量 |
| 配置错误 | 检查模块配置参数，重新安装模块 |
| 镜像拉取失败 | 见下方「镜像拉取失败/网络超时」章节，应用商店安装失败时会直接提示原因 |
| Docker socket 权限 | 确保当前用户在 docker 用户组中 |

### 镜像拉取失败/网络超时

安装应用时若提示「无法连接 GitHub 容器仓库 ghcr.io」或「无法连接 Docker Hub」，说明服务器无法访问镜像仓库，常见原因及解决：

| 提示 | 原因 | 解决 |
|------|------|------|
| 无法连接 GitHub 容器仓库 ghcr.io | 国内网络直连 ghcr.io 不稳定（Frigate、NoteDiscovery 等镜像在此） | 配置 Docker 镜像加速器或代理后重试 |
| 无法连接 Docker Hub | 国内网络直连 Docker Hub 不稳定 | 配置镜像加速器后重试 |
| 镜像拉取网络超时/连接失败 | 服务器网络波动或防火墙拦截 | 检查网络连通性，稍后重试 |
| 镜像不存在或无拉取权限 | 镜像地址有误或已下架 | 检查模块配置中的镜像地址 |

**配置镜像加速器**（需在宿主机操作，EasyServer 容器内无法自动修改）：

```bash
# 编辑 Docker 守护进程配置
sudo tee /etc/docker/daemon.json <<'EOF'
{
  "registry-mirrors": ["https://docker.m.daocloud.io"]
}
EOF
# 重启 Docker 使配置生效
sudo systemctl restart docker
```

加速器地址以各服务商最新公告为准（如 DaoCloud、阿里云容器镜像服务等）。配置完成后回到应用商店重新安装即可。

### 重启服务

```bash
# 在管理面板中操作，或使用命令行
cd ~/easyserver
docker compose -f modules/<模块名>/docker-compose.yml restart
```

---

## 端口被占用怎么办？

### 查找占用端口的进程

```bash
# 查找占用指定端口的进程
sudo lsof -i :端口号

# 或使用 netstat
sudo netstat -tlnp | grep 端口号
```

### 解决方案

1. **停止占用端口的进程**（如果不重要）
2. **修改 EasyServer 服务端口**：
   - 进入「应用商店」卸载该服务
   - 重新安装，填写新的端口号
3. **使用域名反代模式**：Nginx 统一入口，避免端口冲突

---

## SSL 证书申请失败

### 常见原因

| 原因 | 说明 | 解决方法 |
|------|------|---------|
| DNS 未生效 | 域名解析尚未传播 | 等待 5-10 分钟，或检查 DNS 配置 |
| AccessKey 错误 | 阿里云密钥填写有误 | 检查 AccessKey 和 Secret 是否正确 |
| 域名格式错误 | 填写了子域名而非主域名 | 应填写主域名，如 `example.com` |
| API 权限不足 | AccessKey 无 DNS 管理权限 | 在阿里云 RAM 中授权 AliyunDNSFullAccess |

### 手动测试

```bash
# 进入 ACME 容器测试
docker exec -it easyserver-acme sh

# 手动申请证书
acme.sh --issue --dns dns_ali -d *.你的域名 -d 你的域名
```

### 证书续签问题

ACME 模块会自动续签证书。如果续签失败：
1. 检查阿里云 AccessKey 是否仍然有效
2. 查看 ACME 容器日志
3. 手动执行续签命令

---

## 外网无法访问

### 逐步排查

#### 1. 检查服务是否运行

在管理面板的「仪表盘」确认所有服务状态为「运行中」。

#### 2. 检查防火墙

```bash
# 查看防火墙状态
sudo ufw status

# 开放所需端口
sudo ufw allow 8443/tcp    # HTTPS
sudo ufw allow 80/tcp      # HTTP
```

#### 3. 检查端口监听

```bash
# 查看端口是否正常监听
ss -tlnp | grep 端口号
```

#### 4. 检查 DNS 解析

```bash
# 测试域名是否解析正确
nslookup 你的域名
ping 你的域名
```

#### 5. 测试本地访问

```bash
# 在服务器上测试本地访问
curl http://127.0.0.1:9800/api/health
curl http://127.0.0.1:3001
```

#### 6. 检查 Nginx 配置

```bash
# 查看 Nginx 配置是否有语法错误
docker exec easyserver-nginx nginx -t
```

---

## 数据备份与恢复

### 备份中心

EasyServer 提供内置备份中心，支持本地和云端备份：

- **本地备份**：基于 restic 增量备份，存储在 `data/backups/restic-repo`
- **云端备份**：支持阿里云 OSS、AWS S3、Backblaze B2
- **自动备份**：可配置每日/每周/每月自动备份
- **快照恢复**：任意历史快照一键恢复

### 手动备份

也可手动备份 `data/` 目录：

```bash
# 完整备份（推荐定期执行）
tar -czf easyserver-backup-$(date +%Y%m%d).tar.gz \
  ~/easyserver/data/ \
  ~/easyserver/.env \
  ~/easyserver/modules/
```

### 各模块数据说明

| 模块 | 数据目录 | 说明 |
|------|---------|------|
| Jellyfin | data/jellyfin/ | 媒体库数据库、元数据、配置 |
| Joplin | data/joplin/ | 笔记数据、附件 |
| Calibre-Web | data/calibre-web/ | 电子书数据库、书籍文件 |
| Uptime Kuma | data/uptime-kuma/ | 监控数据、配置 |
| FileBrowser | data/filebrowser/ | 文件管理数据库 |
| NoteDiscovery | data/notediscovery/ | 笔记文件 |
| Nginx | modules/nginx/ssl、log | SSL 证书、访问/错误日志 |
| Frigate | data/frigate/ | 监控录像、检测配置 |
| Backup | data/backups/ | restic 备份仓库 |

### 恢复

```bash
# 停止所有服务
cd ~/easyserver
docker compose down

# 解压备份
tar -xzf easyserver-backup-20260101.tar.gz -C ~/

# 重新启动
docker compose up -d
```

### 自动备份建议

建议设置 crontab 定期自动备份：

```bash
# 每天凌晨 3 点自动备份
0 3 * * * cd ~/easyserver && tar -czf /backup/easyserver-$(date +\%Y\%m\%d).tar.gz data/ .env
```

---

## 其他问题

### 管理面板打不开？

1. 确认管理引擎容器正在运行：`docker ps | grep easyserver-core`
2. 检查 HTTPS 端口是否正确（在「网络配置」的域名反代配置中查看）
3. 查看引擎日志：`docker logs easyserver-core`

### 修改端口后外网无法访问？

修改 HTTPS 端口后，请检查：
1. 路由器端口转发规则是否同步更新为新端口
2. 防火墙是否放行了新端口
3. 运营商是否封锁了该端口（国内运营商通常封锁 443 和 80）

> 提示：IPv6 直连时 443 端口通常可用，IPv4 端口转发时建议先用 8443 测试。

### 如何更新 EasyServer？

```bash
cd ~/easyserver
git pull
docker compose build core
docker compose up -d
```

### 如何查看 Docker 日志？

```bash
# 查看指定容器最近 100 行日志
docker logs --tail 100 容器名

# 实时查看日志
docker logs -f 容器名
```
