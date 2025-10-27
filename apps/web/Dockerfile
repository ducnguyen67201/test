# Build stage
FROM node:20-alpine AS builder

# Set working directory
WORKDIR /app

# Copy package files
COPY package*.json ./
COPY apps/web/package*.json ./apps/web/

# Install dependencies
RUN npm ci

# Copy application code
COPY apps/web/ ./apps/web/
COPY proto/gen/ts/ ./proto/gen/ts/

# Build the application
WORKDIR /app/apps/web
RUN npm run build

# Runtime stage
FROM node:20-alpine AS runner

# Install dumb-init for proper signal handling
RUN apk add --no-cache dumb-init

# Create non-root user
RUN addgroup -g 1000 -S nodejs && \
    adduser -u 1000 -S nextjs -G nodejs

# Set working directory
WORKDIR /app

# Copy built application
COPY --from=builder --chown=nextjs:nodejs /app/apps/web/.next ./apps/web/.next
COPY --from=builder --chown=nextjs:nodejs /app/apps/web/public ./apps/web/public
COPY --from=builder --chown=nextjs:nodejs /app/apps/web/package.json ./apps/web/
COPY --from=builder --chown=nextjs:nodejs /app/node_modules ./node_modules

# Set environment to production
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

# Switch to non-root user
USER nextjs

# Expose port
EXPOSE 3000

# Set working directory for the app
WORKDIR /app/apps/web

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD node -e "require('http').get('http://localhost:3000/api/trpc/health', (r) => {if (r.statusCode !== 200) throw new Error()})" || exit 1

# Run with dumb-init for proper signal handling
ENTRYPOINT ["dumb-init", "--"]
CMD ["npm", "start"]