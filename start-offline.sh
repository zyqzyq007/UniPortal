#!/usr/bin/env bash
# UniPortal 离线启动脚本
# 用途：在无网络环境下从 uni-portal.tar 加载镜像并启动容器
# 用法：./start-offline.sh [--reset]
#   --reset  同时删除命名卷（会清空数据库与已上传文件）

set -euo pipefail

# ---------- 配置 ----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_TAR="${SCRIPT_DIR}/uni-portal.tar"
IMAGE_NAME="uni-portal:latest"
CONTAINER_NAME="uni-portal"
HOST_PORT="8080"
CONTAINER_PORT="8080"
VOLUME_STORAGE="uniportal_storage"
VOLUME_DB="uniportal_db"
JWT_SECRET="${JWT_SECRET:-dev_secret_key_change_me}"

# ---------- 颜色输出 ----------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ---------- 前置检查 ----------
if ! command -v docker >/dev/null 2>&1; then
  error "未检测到 docker，请先安装 Docker。"
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  error "Docker 守护进程未运行或当前用户无权限访问。请启动 Docker 或将用户加入 docker 组。"
  exit 1
fi

if [[ ! -f "${IMAGE_TAR}" ]]; then
  error "未找到镜像文件：${IMAGE_TAR}"
  exit 1
fi

# ---------- 参数解析 ----------
RESET_VOLUMES=0
for arg in "$@"; do
  case "${arg}" in
    --reset) RESET_VOLUMES=1 ;;
    -h|--help)
      sed -n '2,5p' "$0"; exit 0 ;;
    *) warn "未知参数：${arg}" ;;
  esac
done

# ---------- 1. 加载镜像 ----------
info "加载镜像：${IMAGE_TAR}"
LOAD_OUTPUT="$(docker load -i "${IMAGE_TAR}")"
echo "${LOAD_OUTPUT}"

# 自动识别 load 出来的镜像名（兼容 tar 内 tag 与 IMAGE_NAME 不一致的情况）
LOADED_IMAGE="$(echo "${LOAD_OUTPUT}" | sed -n 's/^Loaded image: //p' | head -n1)"
if [[ -n "${LOADED_IMAGE}" ]]; then
  IMAGE_NAME="${LOADED_IMAGE}"
fi
info "使用镜像：${IMAGE_NAME}"

# ---------- 2. 清理旧容器 ----------
if docker ps -a --format '{{.Names}}' | grep -qx "${CONTAINER_NAME}"; then
  info "停止并删除旧容器：${CONTAINER_NAME}"
  docker rm -f "${CONTAINER_NAME}" >/dev/null
fi

# ---------- 3. 可选：重置命名卷 ----------
if [[ "${RESET_VOLUMES}" -eq 1 ]]; then
  warn "--reset 已指定，将删除命名卷（数据丢失，不可恢复）"
  for v in "${VOLUME_STORAGE}" "${VOLUME_DB}"; do
    if docker volume inspect "${v}" >/dev/null 2>&1; then
      docker volume rm "${v}" >/dev/null && info "已删除卷：${v}"
    fi
  done
fi

# ---------- 4. 创建命名卷（幂等） ----------
for v in "${VOLUME_STORAGE}" "${VOLUME_DB}"; do
  docker volume inspect "${v}" >/dev/null 2>&1 || {
    docker volume create "${v}" >/dev/null
    info "已创建卷：${v}"
  }
done

# ---------- 5. 启动容器 ----------
info "启动容器：${CONTAINER_NAME}"
docker run -d \
  --name "${CONTAINER_NAME}" \
  --restart unless-stopped \
  -p "${HOST_PORT}:${CONTAINER_PORT}" \
  -v "${VOLUME_STORAGE}:/app/server/storage" \
  -v "${VOLUME_STORAGE}:/app/server/temp_uploads" \
  -v "${VOLUME_DB}:/app/server/data" \
  -e "PORT=${CONTAINER_PORT}" \
  -e "DATABASE_URL=file:../data/prod.db" \
  -e "JWT_SECRET=${JWT_SECRET}" \
  "${IMAGE_NAME}" >/dev/null

# ---------- 6. 状态确认 ----------
sleep 2
if docker ps --format '{{.Names}}' | grep -qx "${CONTAINER_NAME}"; then
  info "启动成功 ✅"
  echo
  echo "  访问地址：http://localhost:${HOST_PORT}"
  echo "  查看日志：docker logs -f ${CONTAINER_NAME}"
  echo "  停止容器：docker stop ${CONTAINER_NAME}"
  echo
else
  error "容器启动失败，最近日志："
  docker logs --tail 50 "${CONTAINER_NAME}" || true
  exit 1
fi
