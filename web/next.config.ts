import type { NextConfig } from "next";

const apiUrl = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  // Внутри docker-compose фронтенд ходит в API по имени сервиса.
  env: {
    API_INTERNAL_URL: apiUrl,
  },
  // Для разработки без Caddy (`npm run dev` + uvicorn): запросы /api/* и /health уходят в API.
  // В docker-compose эти пути перехватывает Caddy раньше, чем они дойдут до Next.
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${apiUrl}/api/:path*` },
      { source: "/health", destination: `${apiUrl}/health` },
    ];
  },
};

export default nextConfig;
