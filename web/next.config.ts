import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  // Внутри docker-compose фронтенд ходит в API по имени сервиса.
  env: {
    API_INTERNAL_URL: process.env.API_INTERNAL_URL ?? "http://localhost:8000",
  },
};

export default nextConfig;
