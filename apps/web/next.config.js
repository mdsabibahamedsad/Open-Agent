/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  experimental: {
    optimizePackageImports: ['lucide-react'],
  },
  webpack: (config) => {
    config.module.rules.push({
      test: /vitest\.config\.ts$/,
      loader: 'ignore-loader',
    });
    return config;
  },
}

module.exports = nextConfig