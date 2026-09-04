# ===== VerdictAI 前端镜像 =====
# 多阶段构建：node 构建静态产物 -> nginx 托管 + 反代后端
FROM node:20-alpine AS build

WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
ARG PACKAGE_VERSION=0.2.0
ENV VITE_PACKAGE_VERSION=$PACKAGE_VERSION
RUN npm run build

# ---------- 运行时 ----------
FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /build/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -qO- http://localhost/ >/dev/null 2>&1 || exit 1