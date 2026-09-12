import type { NextConfig } from "next";

const backend = process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8001";

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  async rewrites() {
    return [
      { source: "/docs", destination: `${backend}/docs` },
      { source: "/openapi.json", destination: `${backend}/openapi.json` },
    ];
  },
};

export default nextConfig;
