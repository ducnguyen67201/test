/**
 * Mock LLM Provider for development and testing
 */

import type { Message, LLMResponse, LLMRequestOptions } from "../types";
import { BaseLLMProvider } from "./base";

export class MockLLMProvider extends BaseLLMProvider {
  get name(): string {
    return "mock";
  }

  async isAvailable(): Promise<boolean> {
    return true;
  }

  async chat(
    messages: Message[],
    options?: LLMRequestOptions
  ): Promise<LLMResponse> {
    // Simulate network delay
    await new Promise((resolve) => setTimeout(resolve, 500 + Math.random() * 500));

    const lastMessage = messages[messages.length - 1];
    const userInput = lastMessage?.content.toLowerCase() ?? "";

    // Check if tools are provided and we should call one
    if (options?.tools?.length) {
      const recipeResult = this.detectRecipeIntent(userInput);

      if (recipeResult) {
        return {
          content: "",
          toolCalls: [
            {
              id: `call_${Date.now()}`,
              name: "create_recipe",
              arguments: recipeResult,
            },
          ],
          finishReason: "tool_calls",
          provider: "mock",
          model: "mock-gpt-4",
          usage: {
            promptTokens: 100,
            completionTokens: 50,
            totalTokens: 150,
          },
        };
      }
    }

    // Generate conversational response
    const response = this.generateResponse(userInput);

    return {
      content: response.message,
      finishReason: "stop",
      provider: "mock",
      model: "mock-gpt-4",
      usage: {
        promptTokens: 100,
        completionTokens: 50,
        totalTokens: 150,
      },
    };
  }

  private detectRecipeIntent(input: string): Record<string, unknown> | null {
    // Apache Path Traversal
    if (
      input.includes("apache") ||
      input.includes("httpd") ||
      input.includes("path traversal") ||
      input.includes("cve-2021-41773")
    ) {
      return {
        name: "Apache Path Traversal (CVE-2021-41773)",
        description:
          "Apache HTTP Server 2.4.49 and 2.4.50 path traversal vulnerability allowing access to files outside document root, potentially leading to RCE if CGI is enabled.",
        software: "Apache httpd",
        version_constraint: "2.4.49",
        exploit_family: "path_traversal",
        confidence: 0.92,
        suggestions: [
          "Deploy this lab",
          "Show me the exploit payload",
          "What tools should I use?",
        ],
      };
    }

    // Log4Shell
    if (
      input.includes("log4j") ||
      input.includes("log4shell") ||
      input.includes("cve-2021-44228") ||
      input.includes("jndi")
    ) {
      return {
        name: "Log4Shell RCE (CVE-2021-44228)",
        description:
          "Critical RCE vulnerability in Apache Log4j2 via JNDI injection. Affects versions 2.0-beta9 to 2.14.1. Allows arbitrary code execution through crafted log messages.",
        software: "Apache Log4j2",
        version_constraint: ">=2.0-beta9,<2.15.0",
        exploit_family: "rce",
        confidence: 0.95,
        suggestions: [
          "Deploy this lab",
          "Explain JNDI injection",
          "What's the attack chain?",
        ],
      };
    }

    // SQL Injection
    if (
      input.includes("sql injection") ||
      input.includes("sqli") ||
      input.includes("sql attack")
    ) {
      return {
        name: "SQL Injection Lab",
        description:
          "Classic SQL injection vulnerability in a PHP web application with MySQL backend. Includes union-based, error-based, and blind injection scenarios.",
        software: "MySQL + PHP",
        version_constraint: null,
        exploit_family: "sql_injection",
        confidence: 0.88,
        suggestions: [
          "Deploy basic SQLi lab",
          "Blind SQL injection",
          "Union-based injection",
        ],
      };
    }

    // Deserialization
    if (
      input.includes("deserialization") ||
      input.includes("ysoserial") ||
      input.includes("java serial")
    ) {
      return {
        name: "Java Deserialization RCE",
        description:
          "Insecure Java deserialization vulnerability allowing remote code execution. Lab includes common gadget chains compatible with ysoserial payloads.",
        software: "Java Application Server",
        version_constraint: null,
        exploit_family: "deserialization",
        confidence: 0.85,
        suggestions: [
          "Deploy this lab",
          "List gadget chains",
          "How to detect vulnerable apps?",
        ],
      };
    }

    // Spring4Shell
    if (
      input.includes("spring4shell") ||
      input.includes("spring") ||
      input.includes("cve-2022-22965")
    ) {
      return {
        name: "Spring4Shell RCE (CVE-2022-22965)",
        description:
          "Remote code execution in Spring Framework through data binding on JDK 9+. Requires specific conditions: Spring MVC, Tomcat, WAR deployment.",
        software: "Spring Framework",
        version_constraint: "<5.3.18",
        exploit_family: "rce",
        confidence: 0.90,
        suggestions: [
          "Deploy this lab",
          "What are the prerequisites?",
          "Compare to Log4Shell",
        ],
      };
    }

    // XSS
    if (
      input.includes("xss") ||
      input.includes("cross-site scripting") ||
      input.includes("cross site scripting")
    ) {
      return {
        name: "XSS Vulnerability Lab",
        description:
          "Cross-site scripting vulnerabilities including reflected, stored, and DOM-based XSS. Practice payload crafting and filter bypass techniques.",
        software: "Node.js + Express",
        version_constraint: null,
        exploit_family: "xss",
        confidence: 0.87,
        suggestions: [
          "Deploy this lab",
          "Stored vs Reflected XSS",
          "DOM-based XSS techniques",
        ],
      };
    }

    return null;
  }

  private generateResponse(input: string): { message: string; suggestions: string[] } {
    // Deploy intent
    if (input.includes("deploy") || input.includes("start") || input.includes("spin up")) {
      return {
        message:
          "I'll deploy the lab environment for you. The container will be ready in about 30 seconds. You'll get a connection URL to access your attacker box via VNC.",
        suggestions: ["Check lab status", "How do I connect?", "Lab safety tips"],
      };
    }

    // Help/intro
    if (
      input.includes("help") ||
      input.includes("hello") ||
      input.includes("hi") ||
      input === ""
    ) {
      return {
        message:
          "Hello! I'm the OctoLab assistant. I can help you set up isolated vulnerability labs for penetration testing practice.\n\nTell me what CVE, software, or attack technique you want to rehearse, and I'll generate the appropriate lab configuration.\n\nFor example:\n• \"I need to practice Apache path traversal\"\n• \"Set up a Log4Shell lab\"\n• \"I want to test SQL injection\"",
        suggestions: [
          "Apache CVE-2021-41773",
          "Log4Shell (CVE-2021-44228)",
          "SQL Injection",
          "Java Deserialization",
        ],
      };
    }

    // Generic fallback - ask for more details
    return {
      message:
        "I'd be happy to help you set up a lab for that scenario. Could you provide more details about:\n\n• Which specific CVE or vulnerability type?\n• What software/version should the target run?\n• Any specific attack techniques you want to practice?\n\nThis helps me configure the most appropriate vulnerable environment.",
      suggestions: [
        "Apache vulnerabilities",
        "Java/Spring exploits",
        "Web application attacks",
        "Network services",
      ],
    };
  }
}
