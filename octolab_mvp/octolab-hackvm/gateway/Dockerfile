# LabGateway - NAT router and packet capture gateway
# KVM-friendly: minimal Debian base for Docker now, VM later
FROM debian:bookworm-slim

# Install networking and capture tools
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        iptables \
        iproute2 \
        tcpdump \
        tshark \
        ca-certificates && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Create /pcap directory for legacy capture files (not exported to users)
RUN mkdir -p /pcap

# Create /evidence directory for structured network logs
RUN mkdir -p /evidence

# Copy entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Run as root (required for iptables/tcpdump)
# Will use cap_add: [NET_ADMIN, NET_RAW] in docker-compose, not --privileged
ENTRYPOINT ["/entrypoint.sh"]

