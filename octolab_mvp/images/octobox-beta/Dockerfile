# TEST: made by Copilot
FROM debian:12-slim

# Set locale
RUN apt-get update && \
    apt-get install -y --no-install-recommends locales && \
    sed -i '/en_US.UTF-8/s/^# //g' /etc/locale.gen && \
    locale-gen en_US.UTF-8 && \
    rm -rf /var/lib/apt/lists/*

ENV LANG=en_US.UTF-8

# Install packages
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    xfce4 \
    xfce4-goodies \
    xfce4-terminal \
    dbus-x11 \
    xfonts-base \
    xfonts-75dpi \
    xfonts-100dpi \
    tigervnc-standalone-server \
    tigervnc-common \
    tigervnc-tools \
    sudo \
    ca-certificates \
    nmap \
    curl \
    wget \
    git \
    python3 \
    python3-pip \
    vim \
    nano \
    netcat-openbsd \
    bsdutils \
    iproute2 \
    && rm -rf /var/lib/apt/lists/*

# Create pentester user
RUN useradd -m -s /bin/bash pentester && \
    echo "pentester:pentester123" | chpasswd && \
    usermod -aG sudo pentester && \
    echo "pentester ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

# Create evidence directory
RUN mkdir -p /evidence && \
    chown pentester:pentester /evidence && \
    chmod 755 /evidence

# Copy VNC session startup script (stable, rarely changes)
COPY rootfs/usr/local/bin/start-vnc-session.sh /usr/local/bin/start-vnc-session.sh
RUN chmod +x /usr/local/bin/start-vnc-session.sh

# Copy healthcheck script (fast layer, re-run when script changes)
COPY rootfs/usr/local/bin/octobox-healthcheck /usr/local/bin/octobox-healthcheck
RUN chmod 0755 /usr/local/bin/octobox-healthcheck

# =============================================================================
# CMDLOG SECTION - KEEP AT END FOR CACHE HYGIENE
# These layers change frequently during development. Placing them last ensures
# apt-get and other slow layers remain cached when only cmdlog scripts change.
#
# To force rebuild of ONLY these layers during dev, pass:
#   --build-arg CMDLOG_BUST=$(date +%s)
# =============================================================================
ARG CMDLOG_BUST=0

# Copy command logging shell wrapper
COPY rootfs/usr/local/bin/octolog-shell /usr/local/bin/octolog-shell
RUN chmod 0755 /usr/local/bin/octolog-shell && \
    echo "/usr/local/bin/octolog-shell" >> /etc/shells

# Copy command logging hook for interactive shells
# Canonical script in /etc/profile.d/ (for login shells)
# Shim in /etc/octolab-cmdlog.sh sourced from /etc/bash.bashrc (for non-login shells like XFCE Terminal)
COPY rootfs/etc/profile.d/octolab-cmdlog.sh /etc/profile.d/octolab-cmdlog.sh
COPY rootfs/etc/octolab-cmdlog.sh /etc/octolab-cmdlog.sh
RUN chmod 0644 /etc/profile.d/octolab-cmdlog.sh /etc/octolab-cmdlog.sh && \
    if ! grep -q "octolab-cmdlog" /etc/bash.bashrc 2>/dev/null; then \
        echo '' >> /etc/bash.bashrc && \
        echo '# OctoLab command logging for interactive shells (XFCE Terminal)' >> /etc/bash.bashrc && \
        echo '[ -f /etc/octolab-cmdlog.sh ] && . /etc/octolab-cmdlog.sh' >> /etc/bash.bashrc; \
    fi

# Write build markers for verification (prove which image version is running)
# To verify: docker exec <container> cat /etc/octolab-cmdlog.build-id
#            docker exec <container> cat /etc/octolab-image.build-id
ARG BUILD_TIMESTAMP=unknown
RUN echo "cmdlog-bust=${CMDLOG_BUST}" > /etc/octolab-cmdlog.build-id && \
    echo "image=octobox-beta" > /etc/octolab-image.build-id && \
    echo "cmdlog-bust=${CMDLOG_BUST}" >> /etc/octolab-image.build-id && \
    echo "build-ts=${BUILD_TIMESTAMP}" >> /etc/octolab-image.build-id && \
    chmod 0644 /etc/octolab-cmdlog.build-id /etc/octolab-image.build-id

HEALTHCHECK --interval=5s --timeout=2s --start-period=15s --retries=12 \
    CMD ["/usr/local/bin/octobox-healthcheck"]

ENTRYPOINT ["/usr/local/bin/start-vnc-session.sh"]