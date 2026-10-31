import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  base: "/Smart-Money-IR-MVP/",
  server: { port: 5173, proxy: { "/api": "http://localhost:3001", "/health": "http://localhost:3001" } }
});
