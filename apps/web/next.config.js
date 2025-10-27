/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  swcMinify: true,
  experimental: {
    serverActions: true,
  },
  images: {
    domains: ['img.clerk.com', 'images.clerk.dev'],
  },
  async rewrites() {
    return [
      {
        source: '/api/grpc/:path*',
        destination: `${process.env.NEXT_PUBLIC_GRPC_URL || 'http://localhost:8080'}/:path*`,
      },
    ];
  },
  webpack: (config) => {
    // Handle protobuf imports
    config.resolve.extensionAlias = {
      '.js': ['.ts', '.tsx', '.js', '.jsx'],
    };
    return config;
  },
};

module.exports = nextConfig;