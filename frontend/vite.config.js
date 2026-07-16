import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // En desarrollo, redirige las llamadas /api al backend local (evita CORS).
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
});
