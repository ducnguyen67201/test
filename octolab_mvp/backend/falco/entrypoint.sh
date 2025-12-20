#!/bin/sh
# Falco Entrypoint for OctoLab
# Substitutes environment variables and starts Falco
#
# Required environment variables:
#   BACKEND_URL - URL of the OctoLab backend (e.g., http://octolab-backend:8000)
#   INTERNAL_TOKEN - Token for authenticating with internal API
#
# SECURITY:
# - Never log the INTERNAL_TOKEN value
# - Validate required environment variables before starting

set -e

# Validate required environment variables
if [ -z "$BACKEND_URL" ]; then
    echo "ERROR: BACKEND_URL environment variable is required" >&2
    exit 1
fi

if [ -z "$INTERNAL_TOKEN" ]; then
    echo "ERROR: INTERNAL_TOKEN environment variable is required" >&2
    exit 1
fi

echo "Falco OctoLab entrypoint starting..."
echo "Backend URL: $BACKEND_URL"
# SECURITY: Never log INTERNAL_TOKEN

# Create Falco config from template
CONFIG_TEMPLATE="/etc/falco/falco.yaml.tmpl"
CONFIG_OUTPUT="/etc/falco/falco.yaml"

if [ ! -f "$CONFIG_TEMPLATE" ]; then
    echo "ERROR: Config template not found: $CONFIG_TEMPLATE" >&2
    exit 1
fi

# Substitute environment variables in template
# Using envsubst for safe variable substitution
envsubst < "$CONFIG_TEMPLATE" > "$CONFIG_OUTPUT"

echo "Generated Falco config at $CONFIG_OUTPUT"

# Export HTTP header for authentication
# Falco uses FALCO_HTTP_OUTPUT_HEADERS environment variable for custom headers
export FALCO_HTTP_OUTPUT_HEADERS="Authorization: Bearer $INTERNAL_TOKEN"

echo "Starting Falco with OctoLab configuration..."
exec /usr/bin/falco -c "$CONFIG_OUTPUT" "$@"
