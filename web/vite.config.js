import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["icon.svg"],
      manifest: {
        name: "atravia · Hora Valle",
        short_name: "atravia",
        description: "Promociones según el flujo peatonal y el tipo de grupos que pasan por tu puerta.",
        lang: "es",
        theme_color: "#1d3b2f",
        background_color: "#f6f4ef",
        display: "standalone",
        start_url: "/",
        icons: [{ src: "icon.svg", sizes: "any", type: "image/svg+xml", purpose: "any maskable" }],
      },
      workbox: {
        // la API no se cachea: los datos deben ser frescos
        navigateFallbackDenylist: [/^\/api/],
      },
    }),
  ],
});
