# EasyServer - Nextcloud 镜像扩展
# 官方 nextcloud:stable 镜像不包含 ffmpeg，而视频缩略图/预览生成依赖该二进制，
# 故在此基于官方镜像安装。升级时请执行 docker compose build --pull 拉取最新基础镜像。
FROM nextcloud:stable

# 国内网络环境：apt 源切换为阿里云镜像加速（官方 deb.debian.org 极慢，清华源部分 IP 403）
# 安装 ffmpeg 以支持视频缩略图/预览生成
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
