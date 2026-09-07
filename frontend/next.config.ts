import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  agentRules: false,
  async headers() {
    const apiOrigin = new URL(process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001/api").origin;
    const policy = [
      "default-src 'self'", "base-uri 'none'", "object-src 'none'", "frame-ancestors 'none'",
      `connect-src 'self' ${apiOrigin} http://127.0.0.1:8001 http://localhost:8001 ws://127.0.0.1:* ws://localhost:*`,
      `script-src 'self' 'unsafe-inline'${process.env.NODE_ENV === 'development' ? " 'unsafe-eval'" : ""}`,
      "style-src 'self' 'unsafe-inline'", "img-src 'self' data: blob:", "font-src 'self' data:", "worker-src 'self' blob:",
    ].join('; ');
    return [{ source: '/:path*', headers: [{ key: 'Content-Security-Policy', value: policy }, { key: 'X-Content-Type-Options', value: 'nosniff' }] }];
  },
};

export default nextConfig;
