import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";
const dir = import.meta.dirname;
export default defineConfig({
  root: dir,
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(dir, "./src") } },
  build: {
    outDir: path.resolve(dir, ".verify/out"),
    emptyOutDir: true,
    sourcemap: true,
    rollupOptions: { input: path.resolve(dir, ".verify/index.html") },
  },
  server: { port: 4600, proxy: { "/api": "http://127.0.0.1:4599" } },
});
