# Campo Crítico — imagen del frontend (build con Vite, servido por Nginx)

# --- Etapa 1: build ---------------------------------------------------------
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json ./
# Sin package-lock.json: usamos npm install (genera el árbol de dependencias).
RUN npm install
COPY . .
RUN npm run build

# --- Etapa 2: servir estáticos ---------------------------------------------
FROM nginx:1.27-alpine AS runtime
# Config que sirve la SPA y hace proxy de /api al backend.
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
