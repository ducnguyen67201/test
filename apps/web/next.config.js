const path = require('path');
const fs = require('fs');

// Find root directory by looking for .git or go.work
function findRootDir(startDir) {
  let currentDir = startDir;

  while (true) {
    // Check for .git or go.work to identify root
    if (fs.existsSync(path.join(currentDir, '.git')) ||
        fs.existsSync(path.join(currentDir, 'go.work'))) {
      return currentDir;
    }

    const parentDir = path.dirname(currentDir);
    if (parentDir === currentDir) {
      // Reached filesystem root
      return startDir;
    }
    currentDir = parentDir;
  }
}

// Load environment variables from root .env.local using absolute path
const rootDir = findRootDir(__dirname);
const envPath = path.join(rootDir, '.env.local');

// Parse .env.local file manually
if (fs.existsSync(envPath)) {
  const envContent = fs.readFileSync(envPath, 'utf-8');
  envContent.split('\n').forEach(line => {
    const trimmedLine = line.trim();
    // Skip comments and empty lines
    if (trimmedLine && !trimmedLine.startsWith('#')) {
      const [key, ...valueParts] = trimmedLine.split('=');
      if (key && valueParts.length > 0) {
        const value = valueParts.join('=').trim();
        // Only set if not already set (allows override)
        if (!process.env[key.trim()]) {
          process.env[key.trim()] = value;
        }
      }
    }
  });
  console.log(`[Next.js] Loaded environment from: ${envPath}`);
} else {
  console.warn(`[Next.js] Warning: .env.local not found at: ${envPath}`);
}

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  swcMinify: true,
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
  // Turbopack configuration (Next.js 16+)
  turbopack: {},
  // Webpack fallback for compatibility
  webpack: (config) => {
    // Handle protobuf imports
    config.resolve.extensionAlias = {
      '.js': ['.ts', '.tsx', '.js', '.jsx'],
    };
    return config;
  },
};

module.exports = nextConfig;