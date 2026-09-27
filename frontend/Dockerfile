# Build stage
ARG NODE_IMAGE=docker.m.daocloud.io/library/node:22-alpine
ARG NGINX_IMAGE=docker.m.daocloud.io/library/nginx:alpine
FROM ${NODE_IMAGE} AS builder

ARG NPM_REGISTRY=https://registry.npmmirror.com
RUN npm config set registry ${NPM_REGISTRY}

WORKDIR /app
COPY package*.json ./
RUN npm install

COPY . .
RUN rm -rf node_modules/.vite dist .vite
RUN npx vite build

# Production stage - serve with nginx
FROM ${NGINX_IMAGE}
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
