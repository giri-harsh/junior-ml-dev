import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Served by the API at /app/ (apps/api/main.py mounts apps/web/dist when it exists).
export default defineConfig({ base: "/app/", plugins: [react()], build: { outDir: "dist" } });
