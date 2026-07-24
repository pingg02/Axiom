FROM node:20-alpine AS builder

WORKDIR /build
COPY package.json vite.config.ts index.html ./
COPY src/ src/
RUN npm install && npm run build

# Nginx runtime
FROM nginx:alpine
COPY --from=builder /build/dist/ /usr/share/nginx/html/
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
