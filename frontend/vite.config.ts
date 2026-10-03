import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": new URL("./src", import.meta.url).pathname } },
  server: {
    proxy: {
      "/ui": "http://127.0.0.1:8517",
      "/health": "http://127.0.0.1:8517",
      "/openapi.json": "http://127.0.0.1:8517",
    },
  },
});
