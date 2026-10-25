FROM node:24.22.1-alpine AS build
WORKDIR /app
COPY services/web-ui/package.json services/web-ui/package-lock.json ./
RUN npm ci
COPY services/web-ui/index.html services/web-ui/vite.config.js ./
COPY services/web-ui/src ./src
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.31.7-alpine
# The base image trails Alpine's security updates, so apply them, then go back to the unprivileged user it runs as.
USER root
RUN apk upgrade --no-cache
USER 101
COPY services/web-ui/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
