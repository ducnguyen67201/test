/**
 * Recipe generation tool definitions for LLM function calling
 */

import type { ToolDefinition } from "../types";

export const EXPLOIT_FAMILIES = [
  "path_traversal",
  "rce",
  "sql_injection",
  "xss",
  "ssrf",
  "deserialization",
  "buffer_overflow",
  "privilege_escalation",
  "authentication_bypass",
  "information_disclosure",
  "cryptographic_failure",
  "command_injection",
  "file_inclusion",
  "xxe",
] as const;

/**
 * Tool for creating a vulnerability lab recipe
 */
export const createRecipeTool: ToolDefinition = {
  name: "create_recipe",
  description: `Create a vulnerability lab recipe configuration. Use this tool when the user has described a specific CVE, vulnerability, or attack scenario they want to practice. The recipe will be used to generate an isolated lab environment with vulnerable targets.

Call this tool when:
- User mentions a specific CVE (e.g., CVE-2021-41773, CVE-2021-44228)
- User describes a vulnerability type (e.g., SQL injection, path traversal, RCE)
- User mentions vulnerable software they want to practice on (e.g., Apache, Log4j, Spring)
- User asks to "set up a lab" or "create an environment" for a specific attack

Do NOT call this tool when:
- User is asking general questions about security
- User needs clarification on what they want to practice
- User is asking for help or documentation`,
  parameters: {
    type: "object",
    properties: {
      name: {
        type: "string",
        description:
          "A descriptive name for the lab recipe. Include the CVE number if applicable. Example: 'Apache Path Traversal (CVE-2021-41773)'",
      },
      description: {
        type: "string",
        description:
          "Detailed description of the vulnerability, its impact, and what the user will practice. Include technical details about how the vulnerability works.",
      },
      software: {
        type: "string",
        description:
          "The primary software that will be vulnerable in the lab. Examples: 'Apache httpd', 'Log4j2', 'MySQL + PHP', 'Spring Framework'",
      },
      version_constraint: {
        type: "string",
        description:
          "Version constraint for the vulnerable software. Use semver-like notation. Examples: '2.4.49', '>=2.0-beta9,<2.15.0', '<5.3.18'. Set to null if version is not specific.",
      },
      exploit_family: {
        type: "string",
        description: "The category/family of the exploit",
        enum: EXPLOIT_FAMILIES as unknown as string[],
      },
      confidence: {
        type: "number",
        description:
          "How confident you are that this recipe matches the user's intent (0.0 to 1.0). Lower values indicate you may need to ask for clarification.",
      },
      suggestions: {
        type: "array",
        description:
          "3-4 follow-up suggestions for the user after seeing the recipe",
        items: {
          type: "string",
        },
      },
    },
    required: ["name", "description", "software", "exploit_family", "confidence"],
  },
};

/**
 * Tool for asking clarifying questions
 */
export const clarifyIntentTool: ToolDefinition = {
  name: "clarify_intent",
  description: `Ask the user clarifying questions to better understand what vulnerability or scenario they want to practice. Use this when:
- The user's request is vague or ambiguous
- Multiple vulnerabilities could match their description
- You need more details about version, software, or attack type`,
  parameters: {
    type: "object",
    properties: {
      message: {
        type: "string",
        description: "A helpful message asking for clarification",
      },
      options: {
        type: "array",
        description:
          "Specific options the user can choose from to clarify their intent",
        items: {
          type: "object",
          properties: {
            label: {
              type: "string",
              description: "Short label for the option",
            },
            description: {
              type: "string",
              description: "Brief description of what this option means",
            },
          },
          required: ["label", "description"],
        },
      },
    },
    required: ["message", "options"],
  },
};

/**
 * All recipe-related tools
 */
export const recipeTools: ToolDefinition[] = [createRecipeTool, clarifyIntentTool];

/**
 * System prompt for recipe generation
 */
export const RECIPE_SYSTEM_PROMPT = `You are OctoLab AI, an expert security researcher assistant that helps users set up isolated vulnerability lab environments for penetration testing practice and CTF training.

Your role:
1. Understand the user's security learning goals
2. Identify specific CVEs, vulnerabilities, or attack scenarios they want to practice
3. Generate accurate lab recipe configurations with vulnerable software
4. Provide helpful context about vulnerabilities and attack techniques

=== CRITICAL: ACCURACY REQUIREMENTS ===
When users mention a CVE or vulnerability:
1. If NVD data is provided in the conversation, USE IT EXACTLY. Do not modify or embellish the official description.
2. If no NVD data is provided and you're unsure about the vulnerability details, ASK FOR CLARIFICATION using clarify_intent.
3. NEVER make up vulnerability descriptions, affected software, or attack vectors. If you don't know, say so.
4. For uncommon or recent CVEs, ask the user to provide the CVE ID in standard format (CVE-YYYY-NNNNN) so we can look it up.

Common vulnerability name mappings (use these if users mention them):
- "react2shell" or "React2Shell" → Prototype pollution RCE in react-scripts, affects versions < 4.0.3
- "log4shell" or "Log4Shell" → CVE-2021-44228, Log4j RCE via JNDI injection
- "spring4shell" or "Spring4Shell" → CVE-2022-22965, Spring Framework RCE
- "shellshock" → CVE-2014-6271, Bash RCE via environment variables
- "heartbleed" → CVE-2014-0160, OpenSSL memory disclosure
- "dirty cow" or "dirtycow" → CVE-2016-5195, Linux kernel privilege escalation
- "eternal blue" or "eternalblue" → CVE-2017-0144, SMBv1 RCE

Guidelines:
- When a user describes a CVE or vulnerability clearly AND you have accurate information, use the create_recipe tool to generate a lab configuration
- If the request is unclear OR you're unsure about the vulnerability details, use clarify_intent to ask questions
- Be precise about software versions - many vulnerabilities only affect specific versions
- Include relevant technical details in descriptions ONLY if you're confident they're accurate
- Suggest related vulnerabilities or techniques the user might want to explore

Knowledge areas:
- Web application vulnerabilities (SQLi, XSS, SSRF, path traversal, etc.)
- Server-side vulnerabilities (RCE, deserialization, etc.)
- Network services and protocols
- Container and Kubernetes security
- Common CVEs and their exploitation

Remember: These labs are for authorized security testing and learning. Always assume the user has proper authorization.`;
