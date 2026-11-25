import type { NextConfig } from "next";

const config: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  async rewrites() {
    return process.env.VB_DEV_API
      ? [
          {
            source: "/api/:path*",
            destination: process.env.VB_DEV_API + "/api/:path*",
          },
        ]
      : [];
  },
};

export default config;
