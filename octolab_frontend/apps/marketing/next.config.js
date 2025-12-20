/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  compress: true,

  experimental: {
    // Enable Turbopack for faster builds
    turbo: {},
  },
};

module.exports = nextConfig;
