import { ScrollReveal } from '../components/scroll-reveal';

export default function HomePage() {
  return (
    <div className="min-h-screen bg-black text-white relative overflow-hidden">
      <ScrollReveal />
      {/* Grid background pattern */}
      <div className="absolute inset-0 bg-grid-pattern opacity-20"></div>

      {/* Navigation */}
      <nav className="relative z-10 border-b border-white/10 bg-black/50 backdrop-blur-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            {/* Logo */}
            <div className="flex items-center gap-2">
              <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-[#00ffaa] to-[#4a90e2] flex items-center justify-center">
                <span className="text-sm font-bold text-black">ZZ</span>
              </div>
              <span className="text-xl font-bold">ZeroZero</span>
            </div>

            {/* Nav Links */}
            <div className="hidden md:flex items-center gap-8">
              <a href="#" className="text-gray-300 hover:text-white transition-colors">
                Home
              </a>
              <a href="#" className="text-gray-300 hover:text-white transition-colors">
                Features
              </a>
              <a href="#" className="text-gray-300 hover:text-white transition-colors">
                Pricing
              </a>
            </div>

            {/* CTA Buttons */}
            <div className="flex items-center gap-3">
              <button className="text-gray-300 hover:text-white transition-colors px-4 py-2">
                Log in
              </button>
              <button className="px-6 py-2 rounded-lg font-semibold text-black transition-all hover:scale-105" style={{ background: 'linear-gradient(135deg, #00ffaa 0%, #4a90e2 100%)' }}>
                Sign up
              </button>
            </div>
          </div>
        </div>
      </nav>

      {/* Hero Section */}
      <div className="relative z-10 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-20 pb-32">
        <div className="grid lg:grid-cols-2 gap-12 items-center">
          {/* Left Column - Content */}
          <div className="space-y-8">
            {/* Badge */}
            <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full border border-[#00ffaa]/30 bg-[#00ffaa]/5 backdrop-blur-sm scroll-fade-in">
              <span className="text-sm text-gray-400">Backed by</span>
              <span className="text-sm font-semibold" style={{ color: '#00ffaa' }}>AI Technology</span>
            </div>

            {/* Headline */}
            <div className="space-y-4">
              <h1 className="text-5xl md:text-6xl lg:text-7xl font-bold leading-tight scroll-slide-up delay-100">
                <span className="text-white">SKIP THE SET UP,</span>
                <br />
                <span className="glow-text" style={{ color: '#00ffaa' }}>START BUILDING!</span>
              </h1>
              <p className="text-xl text-gray-400 max-w-lg scroll-slide-up delay-200">
                Turn your ideas into production-ready applications with our AI-powered monorepo template. Built for speed, scale, and simplicity.
              </p>
            </div>

            {/* CTA Section */}
            <div className="space-y-6">
              <div className="flex flex-col sm:flex-row gap-4">
                <div className="flex-1 relative">
                  <input
                    type="text"
                    placeholder="Find your stack here..."
                    className="w-full px-6 py-4 rounded-lg bg-white/5 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:border-[#00ffaa]/50 focus:ring-2 focus:ring-[#00ffaa]/20 transition-all"
                  />
                  <button className="absolute right-2 top-1/2 -translate-y-1/2 p-2 text-gray-400 hover:text-white">
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                    </svg>
                  </button>
                </div>
              </div>

              <button className="w-full sm:w-auto px-8 py-4 rounded-lg font-semibold text-black text-lg transition-all hover:scale-105 hover:shadow-lg hover:shadow-[#00ffaa]/50 flex items-center justify-center gap-2" style={{ background: 'linear-gradient(135deg, #00ffaa 0%, #4a90e2 100%)' }}>
                Launch
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
                </svg>
              </button>

              <p className="text-sm text-gray-500">
                e.g. Next.js, Go, PostgreSQL, TypeScript, tRPC...
              </p>
            </div>
          </div>

          {/* Right Column - Contact Form */}
          <div className="relative">
            <div className="relative bg-white/5 backdrop-blur-sm border border-white/10 rounded-2xl p-8 hover:border-[#00ffaa]/30 transition-all">
              <div className="space-y-6">
                <div>
                  <h3 className="text-2xl font-bold mb-2">Not sure where to start?</h3>
                  <p className="text-gray-400">
                    Let our experts guide you to the right development environment
                  </p>
                </div>

                <div className="space-y-4">
                  <div className="grid grid-cols-2 gap-4">
                    <input
                      type="text"
                      placeholder="First name"
                      className="px-4 py-3 rounded-lg bg-white/5 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:border-[#00ffaa]/50 focus:ring-2 focus:ring-[#00ffaa]/20 transition-all"
                    />
                    <input
                      type="text"
                      placeholder="Last name"
                      className="px-4 py-3 rounded-lg bg-white/5 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:border-[#00ffaa]/50 focus:ring-2 focus:ring-[#00ffaa]/20 transition-all"
                    />
                  </div>

                  <input
                    type="email"
                    placeholder="Email address"
                    className="w-full px-4 py-3 rounded-lg bg-white/5 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:border-[#00ffaa]/50 focus:ring-2 focus:ring-[#00ffaa]/20 transition-all"
                  />

                  <button className="w-full px-6 py-3 rounded-lg font-semibold text-black transition-all hover:scale-105 hover:shadow-lg hover:shadow-[#00ffaa]/50" style={{ background: 'linear-gradient(135deg, #00ffaa 0%, #4a90e2 100%)' }}>
                    Contact us
                  </button>
                </div>
              </div>
            </div>

            {/* Floating Icons */}
            <div className="absolute -top-8 -right-8 w-16 h-16 rounded-full bg-gradient-to-br from-[#00ffaa]/20 to-[#4a90e2]/20 backdrop-blur-sm flex items-center justify-center float-animation">
              <svg className="w-8 h-8 text-[#00ffaa]" fill="currentColor" viewBox="0 0 24 24">
                <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
              </svg>
            </div>

            <div className="absolute -bottom-8 -left-8 w-20 h-20 rounded-full bg-gradient-to-br from-[#4a90e2]/20 to-[#00ffaa]/20 backdrop-blur-sm flex items-center justify-center float-animation float-delay-1">
              <svg className="w-10 h-10 text-[#4a90e2]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
            </div>

            <div className="absolute top-1/2 -right-12 w-12 h-12 rounded-full bg-gradient-to-br from-[#00ffaa]/20 to-[#4a90e2]/20 backdrop-blur-sm flex items-center justify-center float-animation float-delay-2">
              <svg className="w-6 h-6 text-[#00ffaa]" fill="currentColor" viewBox="0 0 24 24">
                <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
              </svg>
            </div>
          </div>
        </div>
      </div>

      {/* Ambient Glow Effects */}
      <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-[#00ffaa]/10 rounded-full blur-3xl"></div>
      <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-[#4a90e2]/10 rounded-full blur-3xl"></div>

      {/* Features Section */}
      <div className="relative z-10 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-24">
        <div className="text-center space-y-6 mb-16">
          <h2 className="text-4xl md:text-5xl lg:text-6xl font-bold scroll-slide-up">
            <span className="text-white">Secure </span>
            <span className="glow-text" style={{ color: '#00ffaa' }}>Your Code</span>
            <br />
            <span className="text-white">With AI-Powered Templates</span>
          </h2>
          <p className="text-xl text-gray-400 max-w-3xl mx-auto scroll-slide-up delay-200">
            Generate, test, and deploy secure coding templates instantly. ZeroZero combines advanced AI with enterprise-grade security to protect your applications from vulnerabilities.
          </p>
        </div>

        <div className="mb-12">
          <h3 className="text-3xl font-bold text-white text-center mb-4 scroll-fade-in">AI Coding Templates</h3>
          <p className="text-center text-gray-400 mb-12 scroll-fade-in delay-100">Explore our security-focused template results</p>
        </div>

        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
          {/* Template Card 1 */}
          <div className="group relative bg-white/5 backdrop-blur-sm border border-white/10 rounded-2xl p-6 hover:border-[#00ffaa]/50 transition-all hover:shadow-lg hover:shadow-[#00ffaa]/20 scroll-scale-up">
            <div className="mb-6">
              <div className="w-full aspect-[4/3] rounded-xl bg-gradient-to-br from-blue-900/50 to-purple-900/50 flex items-center justify-center mb-4 relative overflow-hidden">
                <div className="absolute inset-0 bg-grid-pattern opacity-10"></div>
                <svg className="w-16 h-16 md:w-20 md:h-20 text-[#4a90e2] relative z-10" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
                </svg>
                <div className="absolute top-3 left-3 text-[10px] md:text-xs text-gray-400">SQL Injection Prevention</div>
              </div>

              <div className="flex items-start gap-3 mb-4">
                <div className="p-2 rounded-lg bg-[#4a90e2]/20">
                  <svg className="w-5 h-5 text-[#4a90e2]" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
                  </svg>
                </div>
                <div>
                  <h4 className="text-xl font-bold text-white mb-2">Secure Query Builder</h4>
                  <p className="text-sm text-gray-400">
                    Automatically generates parameterized queries to prevent SQL injection attacks. Includes validation and sanitization layers.
                  </p>
                </div>
              </div>
            </div>

            <div className="flex items-center justify-between pt-4 border-t border-white/10">
              <div className="flex gap-2">
                <span className="px-3 py-1 text-xs rounded-full bg-blue-500/20 text-blue-300 border border-blue-500/30">Python</span>
                <span className="px-3 py-1 text-xs rounded-full bg-purple-500/20 text-purple-300 border border-purple-500/30">SQL</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-[#00ffaa]">98% Safe</span>
                <div className="w-2 h-2 rounded-full bg-[#00ffaa] animate-pulse"></div>
              </div>
            </div>
          </div>

          {/* Template Card 2 */}
          <div className="group relative bg-white/5 backdrop-blur-sm border border-white/10 rounded-2xl p-6 hover:border-[#00ffaa]/50 transition-all hover:shadow-lg hover:shadow-[#00ffaa]/20 scroll-scale-up delay-100">
            <div className="mb-6">
              <div className="w-full aspect-[4/3] rounded-xl bg-gradient-to-br from-purple-900/50 to-blue-900/50 flex items-center justify-center mb-4 relative overflow-hidden">
                <div className="absolute inset-0 bg-grid-pattern opacity-10"></div>
                <svg className="w-16 h-16 md:w-20 md:h-20 text-purple-400 relative z-10" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                </svg>
                <div className="absolute top-3 left-3 text-[10px] md:text-xs text-gray-400">Authentication System</div>
              </div>

              <div className="flex items-start gap-3 mb-4">
                <div className="p-2 rounded-lg bg-purple-500/20">
                  <svg className="w-5 h-5 text-purple-400" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
                  </svg>
                </div>
                <div>
                  <h4 className="text-xl font-bold text-white mb-2">JWT Auth Template</h4>
                  <p className="text-sm text-gray-400">
                    Production-ready authentication with JWT tokens, refresh mechanisms, and secure password hashing using bcrypt.
                  </p>
                </div>
              </div>
            </div>

            <div className="flex items-center justify-between pt-4 border-t border-white/10">
              <div className="flex gap-2">
                <span className="px-3 py-1 text-xs rounded-full bg-purple-500/20 text-purple-300 border border-purple-500/30">Node.js</span>
                <span className="px-3 py-1 text-xs rounded-full bg-blue-500/20 text-blue-300 border border-blue-500/30">JWT</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-[#00ffaa]">99% Safe</span>
                <div className="w-2 h-2 rounded-full bg-[#00ffaa] animate-pulse"></div>
              </div>
            </div>
          </div>

          {/* Template Card 3 */}
          <div className="group relative bg-white/5 backdrop-blur-sm border border-white/10 rounded-2xl p-6 hover:border-[#00ffaa]/50 transition-all hover:shadow-lg hover:shadow-[#00ffaa]/20 scroll-scale-up delay-200">
            <div className="mb-6">
              <div className="w-full aspect-[4/3] rounded-xl bg-gradient-to-br from-emerald-900/50 to-teal-900/50 flex items-center justify-center mb-4 relative overflow-hidden">
                <div className="absolute inset-0 bg-grid-pattern opacity-10"></div>
                <svg className="w-16 h-16 md:w-20 md:h-20 text-emerald-400 relative z-10" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9m-9 9a9 9 0 019-9" />
                </svg>
                <div className="absolute top-3 left-3 text-[10px] md:text-xs text-gray-400">API Security Layer</div>
              </div>

              <div className="flex items-start gap-3 mb-4">
                <div className="p-2 rounded-lg bg-emerald-500/20">
                  <svg className="w-5 h-5 text-emerald-400" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
                  </svg>
                </div>
                <div>
                  <h4 className="text-xl font-bold text-white mb-2">API Rate Limiter</h4>
                  <p className="text-sm text-gray-400">
                    Intelligent rate limiting with Redis caching, DDoS protection, and automatic IP blocking for suspicious activity.
                  </p>
                </div>
              </div>
            </div>

            <div className="flex items-center justify-between pt-4 border-t border-white/10">
              <div className="flex gap-2">
                <span className="px-3 py-1 text-xs rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">Express</span>
                <span className="px-3 py-1 text-xs rounded-full bg-teal-500/20 text-teal-300 border border-teal-500/30">Redis</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-[#00ffaa]">97% Safe</span>
                <div className="w-2 h-2 rounded-full bg-[#00ffaa] animate-pulse"></div>
              </div>
            </div>
          </div>

          {/* Template Card 4 */}
          <div className="group relative bg-white/5 backdrop-blur-sm border border-white/10 rounded-2xl p-6 hover:border-[#00ffaa]/50 transition-all hover:shadow-lg hover:shadow-[#00ffaa]/20 scroll-scale-up delay-300">
            <div className="mb-6">
              <div className="w-full aspect-[4/3] rounded-xl bg-gradient-to-br from-red-900/50 to-orange-900/50 flex items-center justify-center mb-4 relative overflow-hidden">
                <div className="absolute inset-0 bg-grid-pattern opacity-10"></div>
                <svg className="w-16 h-16 md:w-20 md:h-20 text-red-400 relative z-10" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                </svg>
                <div className="absolute top-3 left-3 text-[10px] md:text-xs text-gray-400">CSRF Protection</div>
              </div>

              <div className="flex items-start gap-3 mb-4">
                <div className="p-2 rounded-lg bg-red-500/20">
                  <svg className="w-5 h-5 text-red-400" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
                  </svg>
                </div>
                <div>
                  <h4 className="text-xl font-bold text-white mb-2">CSRF Protection Middleware</h4>
                  <p className="text-sm text-gray-400">
                    Double-submit cookie pattern with SameSite flags and token validation to prevent cross-site request forgery attacks.
                  </p>
                </div>
              </div>
            </div>

            <div className="flex items-center justify-between pt-4 border-t border-white/10">
              <div className="flex gap-2">
                <span className="px-3 py-1 text-xs rounded-full bg-red-500/20 text-red-300 border border-red-500/30">Express</span>
                <span className="px-3 py-1 text-xs rounded-full bg-orange-500/20 text-orange-300 border border-orange-500/30">Security</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-[#00ffaa]">96% Safe</span>
                <div className="w-2 h-2 rounded-full bg-[#00ffaa] animate-pulse"></div>
              </div>
            </div>
          </div>

          {/* Template Card 5 */}
          <div className="group relative bg-white/5 backdrop-blur-sm border border-white/10 rounded-2xl p-6 hover:border-[#00ffaa]/50 transition-all hover:shadow-lg hover:shadow-[#00ffaa]/20 scroll-scale-up delay-400">
            <div className="mb-6">
              <div className="w-full aspect-[4/3] rounded-xl bg-gradient-to-br from-yellow-900/50 to-amber-900/50 flex items-center justify-center mb-4 relative overflow-hidden">
                <div className="absolute inset-0 bg-grid-pattern opacity-10"></div>
                <svg className="w-16 h-16 md:w-20 md:h-20 text-yellow-400 relative z-10" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
                </svg>
                <div className="absolute top-3 left-3 text-[10px] md:text-xs text-gray-400">XSS Prevention</div>
              </div>

              <div className="flex items-start gap-3 mb-4">
                <div className="p-2 rounded-lg bg-yellow-500/20">
                  <svg className="w-5 h-5 text-yellow-400" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
                  </svg>
                </div>
                <div>
                  <h4 className="text-xl font-bold text-white mb-2">XSS Prevention Layer</h4>
                  <p className="text-sm text-gray-400">
                    Content Security Policy headers, HTML sanitization with DOMPurify, and automatic output encoding for all user inputs.
                  </p>
                </div>
              </div>
            </div>

            <div className="flex items-center justify-between pt-4 border-t border-white/10">
              <div className="flex gap-2">
                <span className="px-3 py-1 text-xs rounded-full bg-yellow-500/20 text-yellow-300 border border-yellow-500/30">React</span>
                <span className="px-3 py-1 text-xs rounded-full bg-amber-500/20 text-amber-300 border border-amber-500/30">DOMPurify</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-[#00ffaa]">95% Safe</span>
                <div className="w-2 h-2 rounded-full bg-[#00ffaa] animate-pulse"></div>
              </div>
            </div>
          </div>

          {/* Template Card 6 */}
          <div className="group relative bg-white/5 backdrop-blur-sm border border-white/10 rounded-2xl p-6 hover:border-[#00ffaa]/50 transition-all hover:shadow-lg hover:shadow-[#00ffaa]/20 scroll-scale-up delay-500">
            <div className="mb-6">
              <div className="w-full aspect-[4/3] rounded-xl bg-gradient-to-br from-indigo-900/50 to-violet-900/50 flex items-center justify-center mb-4 relative overflow-hidden">
                <div className="absolute inset-0 bg-grid-pattern opacity-10"></div>
                <svg className="w-16 h-16 md:w-20 md:h-20 text-indigo-400 relative z-10" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" />
                </svg>
                <div className="absolute top-3 left-3 text-[10px] md:text-xs text-gray-400">OAuth2 Integration</div>
              </div>

              <div className="flex items-start gap-3 mb-4">
                <div className="p-2 rounded-lg bg-indigo-500/20">
                  <svg className="w-5 h-5 text-indigo-400" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
                  </svg>
                </div>
                <div>
                  <h4 className="text-xl font-bold text-white mb-2">OAuth2 Integration</h4>
                  <p className="text-sm text-gray-400">
                    Complete OAuth2 flow with PKCE, state validation, and multi-provider support (Google, GitHub, Microsoft).
                  </p>
                </div>
              </div>
            </div>

            <div className="flex items-center justify-between pt-4 border-t border-white/10">
              <div className="flex gap-2">
                <span className="px-3 py-1 text-xs rounded-full bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">OAuth2</span>
                <span className="px-3 py-1 text-xs rounded-full bg-violet-500/20 text-violet-300 border border-violet-500/30">PKCE</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-[#00ffaa]">99% Safe</span>
                <div className="w-2 h-2 rounded-full bg-[#00ffaa] animate-pulse"></div>
              </div>
            </div>
          </div>

          {/* Template Card 7 */}
          <div className="group relative bg-white/5 backdrop-blur-sm border border-white/10 rounded-2xl p-6 hover:border-[#00ffaa]/50 transition-all hover:shadow-lg hover:shadow-[#00ffaa]/20 scroll-scale-up delay-600">
            <div className="mb-6">
              <div className="w-full aspect-[4/3] rounded-xl bg-gradient-to-br from-cyan-900/50 to-blue-900/50 flex items-center justify-center mb-4 relative overflow-hidden">
                <div className="absolute inset-0 bg-grid-pattern opacity-10"></div>
                <svg className="w-16 h-16 md:w-20 md:h-20 text-cyan-400 relative z-10" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                </svg>
                <div className="absolute top-3 left-3 text-[10px] md:text-xs text-gray-400">Data Encryption</div>
              </div>

              <div className="flex items-start gap-3 mb-4">
                <div className="p-2 rounded-lg bg-cyan-500/20">
                  <svg className="w-5 h-5 text-cyan-400" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
                  </svg>
                </div>
                <div>
                  <h4 className="text-xl font-bold text-white mb-2">Encryption Service</h4>
                  <p className="text-sm text-gray-400">
                    AES-256-GCM encryption for data at rest, TLS 1.3 for transit, and secure key rotation with AWS KMS integration.
                  </p>
                </div>
              </div>
            </div>

            <div className="flex items-center justify-between pt-4 border-t border-white/10">
              <div className="flex gap-2">
                <span className="px-3 py-1 text-xs rounded-full bg-cyan-500/20 text-cyan-300 border border-cyan-500/30">AES-256</span>
                <span className="px-3 py-1 text-xs rounded-full bg-blue-500/20 text-blue-300 border border-blue-500/30">KMS</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-[#00ffaa]">98% Safe</span>
                <div className="w-2 h-2 rounded-full bg-[#00ffaa] animate-pulse"></div>
              </div>
            </div>
          </div>

          {/* Template Card 8 */}
          <div className="group relative bg-white/5 backdrop-blur-sm border border-white/10 rounded-2xl p-6 hover:border-[#00ffaa]/50 transition-all hover:shadow-lg hover:shadow-[#00ffaa]/20 scroll-scale-up delay-100">
            <div className="mb-6">
              <div className="w-full aspect-[4/3] rounded-xl bg-gradient-to-br from-pink-900/50 to-rose-900/50 flex items-center justify-center mb-4 relative overflow-hidden">
                <div className="absolute inset-0 bg-grid-pattern opacity-10"></div>
                <svg className="w-16 h-16 md:w-20 md:h-20 text-pink-400 relative z-10" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                <div className="absolute top-3 left-3 text-[10px] md:text-xs text-gray-400">Input Validation</div>
              </div>

              <div className="flex items-start gap-3 mb-4">
                <div className="p-2 rounded-lg bg-pink-500/20">
                  <svg className="w-5 h-5 text-pink-400" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
                  </svg>
                </div>
                <div>
                  <h4 className="text-xl font-bold text-white mb-2">Input Validation Framework</h4>
                  <p className="text-sm text-gray-400">
                    Comprehensive validation with Zod schemas, type-safe parsing, and automatic error handling for all API inputs.
                  </p>
                </div>
              </div>
            </div>

            <div className="flex items-center justify-between pt-4 border-t border-white/10">
              <div className="flex gap-2">
                <span className="px-3 py-1 text-xs rounded-full bg-pink-500/20 text-pink-300 border border-pink-500/30">Zod</span>
                <span className="px-3 py-1 text-xs rounded-full bg-rose-500/20 text-rose-300 border border-rose-500/30">TypeScript</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-[#00ffaa]">97% Safe</span>
                <div className="w-2 h-2 rounded-full bg-[#00ffaa] animate-pulse"></div>
              </div>
            </div>
          </div>

          {/* Template Card 9 */}
          <div className="group relative bg-white/5 backdrop-blur-sm border border-white/10 rounded-2xl p-6 hover:border-[#00ffaa]/50 transition-all hover:shadow-lg hover:shadow-[#00ffaa]/20 scroll-scale-up delay-200">
            <div className="mb-6">
              <div className="w-full aspect-[4/3] rounded-xl bg-gradient-to-br from-green-900/50 to-emerald-900/50 flex items-center justify-center mb-4 relative overflow-hidden">
                <div className="absolute inset-0 bg-grid-pattern opacity-10"></div>
                <svg className="w-16 h-16 md:w-20 md:h-20 text-green-400 relative z-10" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                </svg>
                <div className="absolute top-3 left-3 text-[10px] md:text-xs text-gray-400">Security Headers</div>
              </div>

              <div className="flex items-start gap-3 mb-4">
                <div className="p-2 rounded-lg bg-green-500/20">
                  <svg className="w-5 h-5 text-green-400" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
                  </svg>
                </div>
                <div>
                  <h4 className="text-xl font-bold text-white mb-2">Security Headers Middleware</h4>
                  <p className="text-sm text-gray-400">
                    Automated security headers including CSP, HSTS, X-Frame-Options, and Permissions-Policy for comprehensive protection.
                  </p>
                </div>
              </div>
            </div>

            <div className="flex items-center justify-between pt-4 border-t border-white/10">
              <div className="flex gap-2">
                <span className="px-3 py-1 text-xs rounded-full bg-green-500/20 text-green-300 border border-green-500/30">Next.js</span>
                <span className="px-3 py-1 text-xs rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">Helmet</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-[#00ffaa]">96% Safe</span>
                <div className="w-2 h-2 rounded-full bg-[#00ffaa] animate-pulse"></div>
              </div>
            </div>
          </div>
        </div>

        {/* CTA Buttons */}
        <div className="flex flex-col sm:flex-row items-center justify-center gap-4 mt-16 md:mt-20 scroll-scale-up">
          <button className="px-8 py-3 rounded-lg font-semibold text-black transition-all hover:scale-105 hover:shadow-lg hover:shadow-[#00ffaa]/50 flex items-center gap-2 bg-[#00ffaa]">
            Try it free
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
            </svg>
          </button>
          <button className="px-8 py-3 rounded-lg font-semibold text-white border border-white/20 bg-white/5 backdrop-blur-sm transition-all hover:border-white/40 hover:bg-white/10 flex items-center gap-2">
            <svg className="w-5 h-5 text-[#00ffaa]" fill="currentColor" viewBox="0 0 24 24">
              <path d="M8 5v14l11-7z"/>
            </svg>
            See how it works
          </button>
        </div>
      </div>

      {/* No Friction Section */}
      <div className="relative z-10 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-32">
        <div className="text-center space-y-6">
          <h2 className="text-4xl md:text-5xl lg:text-6xl font-bold leading-tight scroll-slide-up">
            <span className="text-white">No containers. No set up.</span>
            <br />
            <span className="glow-text bg-gradient-to-r from-[#00ffaa] to-[#4a90e2] bg-clip-text text-transparent">
              No friction.
            </span>
          </h2>
          <p className="text-lg md:text-xl text-gray-400 max-w-3xl mx-auto scroll-slide-up delay-200">
            Reproducible environments that launch in seconds, powered entirely by open-source software and isolated for responsible testing.
          </p>
        </div>
      </div>

      {/* Pricing Section */}
      <div className="relative z-10 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-24">
        <div className="text-center mb-16">
          <h2 className="text-4xl md:text-5xl lg:text-6xl font-bold text-white mb-4 scroll-slide-up">
            Simple pricing plans.
          </h2>
          <p className="text-lg md:text-xl text-gray-400 scroll-slide-up delay-100">
            We've designed our pricing to maximize your ROI.
          </p>
        </div>

        <div className="grid md:grid-cols-3 gap-6 lg:gap-8 items-center">
          {/* Basic Plan */}
          <div className="relative bg-white/5 backdrop-blur-sm border border-white/10 rounded-2xl p-8 scroll-slide-right">
            <div className="mb-6">
              <h3 className="text-3xl font-bold text-white mb-4">Basic</h3>
              <p className="text-gray-400 text-sm mb-6">
                Perfect for small businesses getting started with secure templates
              </p>
              <div className="mb-2">
                <span className="text-5xl font-bold text-white">$0</span>
                <span className="text-gray-400 text-xl">/m</span>
              </div>
            </div>

            <ul className="space-y-3 mb-8 min-h-[200px]">
              <li className="text-gray-300 text-sm">• 5 environments</li>
              <li className="text-gray-300 text-sm">• 2GB RAM per environment</li>
              <li className="text-gray-300 text-sm">• Community support</li>
              <li className="text-gray-300 text-sm">• Basic templates</li>
            </ul>

            <button className="w-full px-6 py-3 rounded-full font-semibold text-white bg-transparent border-2 border-white/20 hover:bg-white/5 transition-all">
              Get Started
            </button>
          </div>

          {/* Pro Plan */}
          <div className="relative bg-white/5 backdrop-blur-sm border-[3px] border-white rounded-2xl p-8 md:scale-105 shadow-2xl scroll-scale-up delay-200">
            <div className="absolute -top-4 right-8">
              <span className="px-4 py-1 text-xs font-semibold text-white bg-black rounded-full border border-white/20">
                Most Popular
              </span>
            </div>

            <div className="mb-6">
              <h3 className="text-3xl font-bold text-white mb-4">Pro</h3>
              <p className="text-gray-400 text-sm mb-6">
                For growing teams who need advanced security analysis
              </p>
              <div className="mb-2">
                <span className="text-6xl md:text-7xl font-bold bg-gradient-to-r from-[#00ffaa] to-[#4a90e2] bg-clip-text text-transparent">Custom</span>
              </div>
            </div>

            <ul className="space-y-3 mb-8 min-h-[200px]">
              <li className="text-gray-300 text-sm">• Up to 200 prompt simulations</li>
              <li className="text-gray-300 text-sm">• 20 blog post generations</li>
              <li className="text-gray-300 text-sm">• Email outreach to popular blogs</li>
              <li className="text-gray-300 text-sm">• + Perplexity, Claude and Gemini</li>
              <li className="text-gray-300 text-sm">• Upto 10 team members</li>
            </ul>

            <button className="w-full px-6 py-3 rounded-full font-semibold text-white bg-black border-2 border-white/20 hover:bg-white/5 transition-all">
              Book a Demo
            </button>
          </div>

          {/* Enterprise Plan */}
          <div className="relative bg-white/5 backdrop-blur-sm border border-white/10 rounded-2xl p-8 scroll-slide-left delay-400">
            <div className="mb-6">
              <h3 className="text-3xl font-bold text-white mb-4">Enterprise</h3>
              <p className="text-gray-400 text-sm mb-6">
                For organizations that need custom security solutions at scale
              </p>
              <div className="mb-2">
                <span className="text-5xl font-bold text-white">Custom</span>
              </div>
            </div>

            <ul className="space-y-3 mb-8 min-h-[200px]">
              <li className="text-gray-300 text-sm">• Everything in Pro</li>
              <li className="text-gray-300 text-sm">• Dedicated security specialist</li>
              <li className="text-gray-300 text-sm">• Professionally edited blogs</li>
              <li className="text-gray-300 text-sm">• Priority Slack Support</li>
              <li className="text-gray-300 text-sm">• Custom Integrations</li>
            </ul>

            <button className="w-full px-6 py-3 rounded-full font-semibold text-white bg-transparent border-2 border-white/20 hover:bg-white/5 transition-all">
              Book a Demo
            </button>
          </div>
        </div>
      </div>

      {/* FAQ Section */}
      <div className="relative z-10 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-24">
        <div className="grid lg:grid-cols-2 gap-12">
          {/* Left Column - FAQ */}
          <div>
            <h2 className="text-4xl md:text-5xl font-bold text-white mb-4 scroll-slide-right">FAQ</h2>
            <p className="text-gray-400 mb-8 scroll-slide-right delay-100">Below are frequently asked questions and answers.</p>

            <div className="space-y-4">
              {/* FAQ Item 1 */}
              <details className="group bg-white/5 backdrop-blur-sm border border-white/10 rounded-xl p-6 hover:border-white/20 transition-all scroll-slide-up">
                <summary className="flex items-center justify-between cursor-pointer list-none">
                  <span className="text-white font-semibold">What is your product and how does it work?</span>
                  <svg className="w-6 h-6 text-[#00ffaa] group-open:rotate-45 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                  </svg>
                </summary>
                <p className="mt-4 text-gray-400 text-sm">
                  Our platform provides AI-powered secure coding templates that help developers build production-ready applications with built-in security features. Simply select a template, customize it to your needs, and deploy.
                </p>
              </details>

              {/* FAQ Item 2 */}
              <details className="group bg-white/5 backdrop-blur-sm border border-white/10 rounded-xl p-6 hover:border-white/20 transition-all">
                <summary className="flex items-center justify-between cursor-pointer list-none">
                  <span className="text-white font-semibold">How much does it cost?</span>
                  <svg className="w-6 h-6 text-[#00ffaa] group-open:rotate-45 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                  </svg>
                </summary>
                <p className="mt-4 text-gray-400 text-sm">
                  We offer flexible pricing starting with a free Basic plan. Our Pro and Enterprise plans offer custom pricing based on your team size and requirements. Contact us for a personalized quote.
                </p>
              </details>

              {/* FAQ Item 3 */}
              <details className="group bg-white/5 backdrop-blur-sm border border-white/10 rounded-xl p-6 hover:border-white/20 transition-all">
                <summary className="flex items-center justify-between cursor-pointer list-none">
                  <span className="text-white font-semibold">Is there a free trial available?</span>
                  <svg className="w-6 h-6 text-[#00ffaa] group-open:rotate-45 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                  </svg>
                </summary>
                <p className="mt-4 text-gray-400 text-sm">
                  Yes! Our Basic plan is completely free forever. You can also request a demo of our Pro or Enterprise plans to see advanced features in action before committing.
                </p>
              </details>

              {/* FAQ Item 4 */}
              <details className="group bg-white/5 backdrop-blur-sm border border-white/10 rounded-xl p-6 hover:border-white/20 transition-all">
                <summary className="flex items-center justify-between cursor-pointer list-none">
                  <span className="text-white font-semibold">How do I get started?</span>
                  <svg className="w-6 h-6 text-[#00ffaa] group-open:rotate-45 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                  </svg>
                </summary>
                <p className="mt-4 text-gray-400 text-sm">
                  Getting started is easy! Sign up for a free account, browse our template library, select the templates that fit your needs, and start building. Our documentation will guide you through the setup process.
                </p>
              </details>

              {/* FAQ Item 5 */}
              <details className="group bg-white/5 backdrop-blur-sm border border-white/10 rounded-xl p-6 hover:border-white/20 transition-all">
                <summary className="flex items-center justify-between cursor-pointer list-none">
                  <span className="text-white font-semibold">Can I cancel my subscription anytime?</span>
                  <svg className="w-6 h-6 text-[#00ffaa] group-open:rotate-45 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                  </svg>
                </summary>
                <p className="mt-4 text-gray-400 text-sm">
                  Absolutely! You can cancel your subscription at any time from your account settings. There are no cancellation fees or long-term commitments required.
                </p>
              </details>

              {/* FAQ Item 6 */}
              <details className="group bg-white/5 backdrop-blur-sm border border-white/10 rounded-xl p-6 hover:border-white/20 transition-all">
                <summary className="flex items-center justify-between cursor-pointer list-none">
                  <span className="text-white font-semibold">Is my data secure?</span>
                  <svg className="w-6 h-6 text-[#00ffaa] group-open:rotate-45 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                  </svg>
                </summary>
                <p className="mt-4 text-gray-400 text-sm">
                  Security is our top priority. We use industry-standard encryption (AES-256), secure authentication, and follow best practices for data protection. Your code and data are never shared with third parties.
                </p>
              </details>
            </div>
          </div>

          {/* Right Column - Newsletter Signup */}
          <div className="lg:pl-12">
            <div className="sticky top-24 bg-white/5 backdrop-blur-sm border border-white/10 rounded-2xl p-8 scroll-slide-left delay-200">
              <div className="flex justify-center mb-6">
                <div className="w-16 h-16 rounded-full bg-[#00ffaa] flex items-center justify-center">
                  <svg className="w-8 h-8 text-black" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M20 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 4l-8 5-8-5V6l8 5 8-5v2z"/>
                  </svg>
                </div>
              </div>

              <h3 className="text-2xl font-bold text-white text-center mb-4">Stay Updated</h3>
              <p className="text-gray-400 text-sm text-center mb-6">
                Subscribe for monthly newsletter about product updates, how-tos, community spotlights, and more. Unsubscribe anytime.
              </p>

              <div className="space-y-4">
                <input
                  type="email"
                  placeholder="Enter your email here"
                  className="w-full px-4 py-3 rounded-lg bg-white/5 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:border-[#00ffaa]/50 focus:ring-2 focus:ring-[#00ffaa]/20 transition-all"
                />
                <button className="w-full px-6 py-3 rounded-lg font-semibold text-black bg-[#00ffaa] hover:scale-105 hover:shadow-lg hover:shadow-[#00ffaa]/50 transition-all flex items-center justify-center gap-2">
                  Subscribe
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
                  </svg>
                </button>
              </div>

              <div className="flex items-center justify-center gap-4 mt-6 text-xs text-gray-500">
                <div className="flex items-center gap-1">
                  <svg className="w-4 h-4 text-[#00ffaa]" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
                  </svg>
                  <span>No spam</span>
                </div>
                <div className="flex items-center gap-1">
                  <svg className="w-4 h-4 text-red-400" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
                  </svg>
                  <span>Unsubscribe anytime</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Footer */}
      <footer className="relative z-10 border-t border-white/10 mt-24 scroll-fade-in">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-8 mb-12">
            {/* Brand Column */}
            <div className="col-span-2 md:col-span-1">
              <div className="flex items-center gap-2 mb-4">
                <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-[#00ffaa] to-[#4a90e2] flex items-center justify-center">
                  <span className="text-sm font-bold text-black">ZZ</span>
                </div>
                <span className="text-xl font-bold text-white">Product</span>
              </div>
              <p className="text-gray-400 text-sm">
                Building the future of productivity and collaboration.
              </p>
            </div>

            {/* Product Column */}
            <div>
              <h4 className="text-white font-semibold mb-4">Product</h4>
              <ul className="space-y-3">
                <li>
                  <a href="#" className="text-gray-400 hover:text-white text-sm transition-colors">
                    Features
                  </a>
                </li>
                <li>
                  <a href="#" className="text-gray-400 hover:text-white text-sm transition-colors">
                    Pricing
                  </a>
                </li>
                <li>
                  <a href="#" className="text-gray-400 hover:text-white text-sm transition-colors">
                    Security
                  </a>
                </li>
              </ul>
            </div>

            {/* Support Column */}
            <div>
              <h4 className="text-white font-semibold mb-4">Support</h4>
              <ul className="space-y-3">
                <li>
                  <a href="#" className="text-gray-400 hover:text-white text-sm transition-colors">
                    Documentation
                  </a>
                </li>
                <li>
                  <a href="#" className="text-gray-400 hover:text-white text-sm transition-colors">
                    Help Center
                  </a>
                </li>
                <li>
                  <a href="#" className="text-gray-400 hover:text-white text-sm transition-colors">
                    Contact
                  </a>
                </li>
              </ul>
            </div>

            {/* Company Column */}
            <div>
              <h4 className="text-white font-semibold mb-4">Company</h4>
              <ul className="space-y-3">
                <li>
                  <a href="#" className="text-gray-400 hover:text-white text-sm transition-colors">
                    About
                  </a>
                </li>
                <li>
                  <a href="#" className="text-gray-400 hover:text-white text-sm transition-colors">
                    Blog
                  </a>
                </li>
                <li>
                  <a href="#" className="text-gray-400 hover:text-white text-sm transition-colors">
                    Careers
                  </a>
                </li>
              </ul>
            </div>
          </div>

          {/* Copyright */}
          <div className="pt-8 border-t border-white/10">
            <p className="text-center text-gray-500 text-sm">
              © 2024 Product. All rights reserved.
            </p>
          </div>
        </div>
      </footer>
    </div>
  );
}
