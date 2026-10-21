import type { NextConfig } from "next";
import { loadEnvConfig } from "@next/env";
import { resolve } from "node:path";
loadEnvConfig(resolve(process.cwd(), "../.."));
const config: NextConfig = {
  transpilePackages: ["@clinic/ui", "@clinic/api-client", "@clinic/core", "@clinic/feature-reviews"],
  output: "standalone",
  // Next buffers a proxied (rewritten) request body and cuts it off at 10 MB by default, which then fails the
  // request. Dormant patients' Import CSV posts files up to 25 MB through /api/platform, so allow 30 MB.
  experimental: { proxyClientMaxBodySize: "30mb" },
  async rewrites() {
    const backend = process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8000";
    return [
      { source: "/api/v1/:path*", destination: `${backend}/api/v1/:path*` },
      { source: "/api/platform/:path*", destination: `${backend}/:path*` },
    ];
  },
};
export default config;
