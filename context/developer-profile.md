# Maxime Roy — Developer Profile & Entrepreneur Roadmap

**Generated:** 2026-03-07
**Sources:** LinkedIn, Obsidian vault, zshrc config, career MOC, AI tooling notes, GitHub repos, conversation history
**Goal:** Full-time on own ventures within 2–3 years
**Main company:** new.blacc

---

## Who I Am

Maxime Roy. Software Developer & Context Engineer. Montreal. Two careers stacked on top of each other.

**First career (~1998–2008): 3D Artist.** Roughly a decade in 3D animation, modeling, and visual production. NAD/UQAC 3D Animation program (1998–1999) was the starting point. This wasn't a hobby — it was a professional chapter. The spatial reasoning, visual composition, GPU intuition, and UI/UX instincts that come from years of 3D work are embedded in how you approach everything technical today. Most C++ systems developers don't have this. It's an unfair advantage in anything visual, interactive, or GPU-related.

**Second career (2012–present): Software Developer.** UQAM BSc Computer Science (2012–2016). 10+ roles since, always at the intersection where hardware meets software — imaging sensors (Teledyne DALSA), computational imaging (AIRY3D), research (CRIM), and now medical devices (Zimmer Biomet). Currently contracting at Zimmer Biomet (C++/Qt/QML, hybrid on-site, since June 2024).

**Third knowledge domain (~2021–present): Finance, Crypto & Web3.** Roughly 7,000 hours over 5 years of self-directed study — crypto, DeFi (staking, lending, borrowing), TradingView technical analysis, TFSA/ETF investing (S&P 500, Nasdaq), and macroeconomics. That's ~4 hrs/day sustained. This isn't surface-level interest — it's the kind of deep immersion that produced the Solidity and Rust skills specifically aimed at working as a Web3 developer. The goal wasn't just to understand crypto — it was to build in it. Solidity for smart contracts, Rust for high-performance blockchain infrastructure (Solana ecosystem, substrate frameworks). Most developers who touch crypto know how to write a basic smart contract. Few also understand the macro environment, DeFi mechanics, traditional investment vehicles, AND have the systems engineering background to build production blockchain tooling.

**The bridge:** The 3D background isn't separate from the engineering — it informed it. GPU/CUDA coursework, Blender skills, visualization instincts, UI/UX sensitivity in Qt/QML — these trace back to the artist decade. The finance depth isn't separate either — it informs what you build (CapCompare, Bear Crypto Club) and who you can serve (crypto-native users, DeFi participants, retail investors). You're not a developer who dabbles in visuals and reads crypto Twitter. You're a visual thinker and systems engineer with deep financial domain knowledge.

---

## Technical Identity

**Primary languages (daily use):** C++ (11/14/17/20), Python (3.10–3.14), Bash/Zsh
**Secondary languages (active knowledge):** Rust (Web3/blockchain focus), JavaScript/TypeScript, Go, Solidity (smart contracts, Web3 career goal), C#
**Frameworks & tools:** Qt/QML, Catch2, Google Test, pytest, FastAPI, Next.js, Docker, Docker Compose, Terraform, Ansible
**Visual/3D:** Blender, SolidWorks, OBS Studio, 3D animation pipeline experience
**Infrastructure:** Proxmox cluster (co-operated with a friend via Cypher Farms — 2×RTX 3080, P40+3060Ti GPU nodes), WireGuard VPN, Ollama (self-hosted LLMs), N8N automation, ClawdBot (Telegram bot on VM)
**Dev environment:** M2 Max MacBook, Starship prompt, Oh My Zsh, pyenv, NVM, Bun, tmux
**Dev tools built:** RepoSec (SAST security scanner, 40 rules), Phraser (offline voice-to-terminal via Whisper), Pencil-Sync (bidirectional design↔code sync tool)

---

## Psychology & Patterns

**Builder personality.** Happiest standing up infrastructure or designing systems. The instinct is always to build the platform first, then the product on top. This is both a strength (deep infrastructure ownership) and a risk (spending too long on foundations before shipping to users).

**Systems-first thinker.** Proxmox homelab, WireGuard tunnels, GPU clusters, N8N automation — the plumbing comes before the product. You architect before you code.

**Alias-heavy / automation-biased.** Every repeated action gets a shortcut. Two times → alias. Three times → script. The zshrc is a map of what matters: `dck*` for Docker, `fpush` for safe force-push, `goclaude` for Claude sessions, `devloop` for autonomous coding, `ytdoc` for VidDocs deployment. This instinct is directly monetizable.

**Unix philosophy.** Small composable tools over monolithic solutions. Bash pipes over custom frameworks. This maps perfectly to AI harness engineering — the same principle (strip down, let the model figure it out) is what Vercel and Manis proved works best.

**Deep-dive learner.** The vault shows months-long study arcs: C++ standards progression (11→17→20), NeetCode full algorithm track, GPU/CUDA coursework, design patterns series. The finance/crypto study — 7,000 hours across DeFi protocols, macro, technical analysis, and investment vehicles — is the same pattern applied to a different domain. Goes deep before moving on.

**Solo operator.** The entire setup — homelab, VPN, self-hosted LLMs, automation loops, cross-agent workflows — is designed for one person to run a disproportionate amount of infrastructure. This is the entrepreneur's superpower: you don't need a team for what most companies need five people to run.

**Compound thinker.** Obsidian MOC structure, `/upvault` habit, CLAUDE.md pattern — everything feeds back into future sessions. Knowledge isn't consumed, it's deposited.

**Collector instinct (risk).** Multiple projects at various stages. The risk is spreading 10–20 hrs/week across too many fronts and shipping nothing. The roadmap below addresses this directly.

---

## Career Thread

**~1998–2008: 3D Artist / Animator** — NAD/UQAC 3D Animation (1998–1999), then roughly a decade of professional 3D work. Modeling, animation, visual production. This built spatial thinking, GPU intuition, and visual composition instincts.

**2012–2016: UQAM BSc Computer Science** — Career pivot into software engineering. Not starting from zero — the 3D background provided deep understanding of rendering pipelines, GPU architecture, and visual systems.

**2016–present: Software Developer** — Teledyne DALSA (imaging/sensors), CRIM (research), AIRY3D (computational imaging), and more. 10+ roles total. The thread is always **systems-level work where hardware meets software** — embedded, GPU, medical devices, imaging pipelines.

**~2021–present: Finance & crypto deep study** — ~7,000 hours across crypto, DeFi (staking, lending, borrowing), TradingView, TFSA/ETF investing (S&P 500, Nasdaq), macroeconomics. This is the domain knowledge behind Bear Crypto Club, CapCompare, and the Solidity skills.

**2022–present: Side ventures** — Cypher Farms (Proxmox infrastructure R&D), developer tools (RepoSec, Phraser, Pencil-Sync), VidDocs (YouTube-to-documentation converter), Bear Crypto Club (content/community).

**2024–present: Zimmer Biomet** — C++/Qt/QML, medical device software, Montreal hybrid contract.

LinkedIn: 1,781 followers. Title: "Software Developer & Context Engineer — C++ · Python · Rust · C# · JS | Blockchain & Web3" — the Blockchain & Web3 tag isn't aspirational; it's backed by ~7,000 hours of study and active Solidity/Rust skill development aimed at a Web3 career path.

---

## The Venture Portfolio

### Tier 1: Most Infrastructure-Complete

**VidDocs — YouTube Tutorial to Documentation Converter**
- **GitHub:** celstnblacc/youtube-tutorial-to-doc-converter
- **Stack:** FastAPI + Next.js + PostgreSQL + Redis + Celery + Ollama (Mistral 7B)
- **Infrastructure:** Fully deployed on Proxmox — dedicated LXC container (10.255.81.85) running 6 Docker services, external Ollama VM (10.255.150.10) with 2×RTX 3080 for VLLM + CPU-only Mistral, iptables firewall, automated deployment script, complete `.env` production config
- **Progress:** 10-step implementation plan. Steps 1.1–1.3 complete (Docker infra, config, database models + migrations, Pydantic schemas). Stalled at Step 1.4 (API routes). Frontend branch has both backend and frontend directories ready.
- **Features planned:** Smart slide detection for video conferences, iterative slide awareness, OCR on frames, multi-format export (Markdown/HTML/PDF)
- **What's missing:** API routes (Step 1.4), auth service (1.5), YouTube/transcript/snapshot/LLM services (Steps 2–5), frontend integration (Steps 6–7)
- **Status:** Deployed infrastructure waiting for application code to catch up. This is your most "production-ready" project in terms of DevOps — the gap is finishing the application logic.

### Tier 2: Developer Tools (Highest Monetization Potential)

**RepoSec — SAST Security Scanner**
- 40 security rules across 6 layers (SAST, secrets detection, supply chain, etc.)
- Global pre-commit hooks, integrated into /ship pipeline
- Published on GitHub (celstnblacc/reposec), installed via pipx
- Complete documentation: security pipeline summary, rule listing, troubleshooting guide
- **Status:** Working tool, used daily in your own workflow. Not yet packaged for external users (no PyPI, no marketing, no landing page).

**Phraser — Offline Voice-to-Terminal via Whisper**
- Fork of a fork of [Handy](https://github.com/cjpais/Handy) (MIT-licensed) — customized for terminal-native workflow
- Full voice terminal stack: Ghostty + Zellij + Yazi + lazygit + Phraser + Ollama + zoxide
- Published on GitHub (celstnblacc/Phraser)
- Privacy-first (fully offline), local Whisper model for speech-to-text
- **Monetization note:** Handy is MIT-licensed, so you CAN monetize a fork — sell it, rebrand it, charge for it. MIT only requires you keep the copyright notice. However, since other forks exist and the upstream is free, direct monetization would need a clear value-add (see below).
- **Status:** Working tool with documentation. No marketing or distribution beyond GitHub.

**Pencil-Sync — Bidirectional Design ↔ Code Sync**
- 22 files, ESM-only TypeScript CLI tool
- Syncs .pen design files (Pencil.dev) with frontend code using Claude CLI as sync engine
- Hash-based state tracking, lock-based loop prevention, 4 conflict strategies
- Auto-detects framework/styling (React, Tailwind, Vite, etc.)
- **Status:** Built (March 2026), next steps are live testing against real .pen files. Not yet published as npm package.

**Harness Engineering Templates** — CLAUDE.md / AGENTS.md workflows
- Multi-layered AI dev workflow: cross-agent routing (Claude Code + Codex CLI), security pipelines, vault integration
- Well beyond typical "use Copilot" setups — but hard to gauge how it compares to what others are building privately
- The Obsidian vault itself is a structured knowledge product
- **Status:** Internal knowledge. Not yet extracted into a sellable form (templates, course, blog series).

### Tier 3: Infrastructure R&D (Pre-Revenue)

**Cypher Farms** (April 2022 – present)
- R&D cloud computing hardware on Proxmox infrastructure
- **Does NOT currently generate revenue** — this is R&D and experimentation, not a running business yet
- The hardware and expertise exist (Proxmox cluster, GPU nodes, networking, automation)
- Natural evolution path: managed AI compute offering, GPU-as-a-service
- **Status:** Infrastructure asset. Not yet productized or monetized.

### Tier 4: Content & Community (Audience Building)

**Bear Crypto Club** — YouTube/crypto community
- YouTube studio setup documented, OBS recording workflow ready
- Content creation infrastructure exists but pipeline is not running
- **Backed by ~7,000 hours of domain study** — crypto, DeFi, staking/lending/borrowing, TradingView, TFSA/ETF (S&P 500, Nasdaq), macroeconomics. This isn't a "developer talks about crypto" project — the domain knowledge is deep enough to produce substantive educational content
- **Status:** Early stage. Infrastructure and domain knowledge exist, no content published.

### Tier 5: Early-Stage / Idea Phase

**CapCompare** (under new.blacc) — Rust full-stack web app
- Tech stack researched (Leptos/Dioxus + Axum + SurrealDB)
- Crypto market cap comparison tool
- Domain knowledge is strong (7,000 hours of crypto/DeFi/macro study) — the product idea comes from real understanding of what crypto users want, not a surface-level guess
- **Status:** Research phase. No code beyond framework evaluation.

> **Note:** **new.blacc** is the main company entity. All ventures above — VidDocs, RepoSec, Phraser, Pencil-Sync, Bear Crypto Club, CapCompare — operate under or will be consolidated under the new.blacc umbrella. Cypher Farms remains a separate partnership.

---

## Strategic Position — Honest Assessment

What you actually have, what it's actually worth, and where the gaps are.

### Real Strengths

**1. The C++ contract is a high-value safety net.**
C++ developers in Montreal command $45–100+ CAD/hr on contract. Medical device software (Zimmer Biomet) is a regulated, specialized niche — that pushes rates higher. This isn't just "a job to quit." It's a funding source. Most indie hackers start from zero income while building. You start from a strong contract. That's a real advantage — as long as you don't let it become the excuse to never ship.

**2. Infrastructure ownership eliminates cloud costs.**
The Proxmox cluster (co-operated with a friend) means you can run VidDocs — FastAPI, PostgreSQL, Redis, Celery, Ollama with GPU inference — without paying AWS/GCP bills. For a bootstrapped solo founder, that's significant. Most indie hackers building AI products are burning $200–2000/month on cloud compute before they have a single user. You can run your stack at near-zero marginal cost. The caveat: this infrastructure is a partnership, so you depend on someone else's continued involvement.

**3. You build tools that solve your own problems.**
RepoSec, Phraser, Pencil-Sync, VidDocs — each started because you hit a real friction point. That's the correct origin story for developer tools. The problem is that solving *your* problem isn't the same as solving *a market's* problem. More on that below.

**4. The 3D artist background is a genuine differentiator — in specific contexts.**
GPU intuition, spatial reasoning, visual composition, UI/UX instincts from a decade of professional 3D work. This matters for: anything GPU/CUDA-related, visual product design, video content quality, presentation polish. It does NOT automatically translate to "better products" or "more revenue." It's an edge, not a moat. The edge becomes a moat only if your products require visual/GPU skills that competitors lack.

**5. Deep finance/crypto domain knowledge — ~7,000 hours — plus Web3 development skills.**
This is the most underweighted asset in this profile. 7,000 hours of study across crypto, DeFi mechanics (staking, lending, borrowing), TradingView technical analysis, Canadian TFSA investing, ETFs (S&P 500, Nasdaq), and macroeconomics. You also invested time specifically learning Solidity and Rust with the goal of working as a Web3 developer. That's not "I read crypto Twitter." That's domain expertise combined with the technical skills to build in the space — smart contracts (Solidity), high-performance blockchain infrastructure (Rust), and the systems engineering foundation (C++) to handle the hard parts. Combined with the 3D/visual background, this positions you to build crypto/DeFi tools with better UX than most Web3 products currently offer. Bear Crypto Club and CapCompare aren't side-hobby projects — they're the intersection of 7,000 hours of domain study and a Web3 development skillset. The question remains: is this knowledge being turned into something, or is it still accumulating?

**6. AI harness engineering knowledge is real and potentially valuable as content.**
CLAUDE.md architecture, cross-agent routing, MCP stacks — this is deep practitioner knowledge. OpenAI and Anthropic both published guides on harness/context engineering in 2025. The topic is hot. But knowledge only has market value when it reaches an audience. Right now it's locked inside your Obsidian vault.

### Honest Gaps

**1. Zero products have shipped to users.**
This is the single most important fact in this document. VidDocs is stalled at Step 1.4. RepoSec has no PyPI package. Phraser has no distribution beyond GitHub. Pencil-Sync hasn't been tested against real .pen files. Bear Crypto Club has no published content. CapCompare is research-phase only. You have built a lot of infrastructure. You have shipped nothing to anyone who isn't you.

**2. Zero revenue from any venture.**
No paying users. No free users. No beta testers. No mailing list. No audience. The gap between "I built this" and "someone pays for this" is where most solo developers die. Building is the comfortable part. Shipping, marketing, and selling are the parts that actually generate freedom.

**3. The VidDocs market already has shipped competitors.**
Docsie (docsie.io) already offers video-to-documentation conversion as a SaaS — supports YouTube, Loom, Vimeo, direct uploads, with structured output including screenshots and step-by-step formatting. Y2Doc (y2doc.com) converts YouTube videos into structured documents with headings, timestamps, and visual context, supporting videos up to 4 hours. Multiple open-source GitHub repos (DoIT-AI/youtube-to-docs, filiksyos/Youtube-to-Doc, others) exist. VidDocs isn't entering an empty market — it's entering a market where the MVP bar is already set by working products. The differentiator would need to be clear: self-hosted/privacy-first? Better LLM-powered structuring via local Ollama? Slide detection for conference recordings? That positioning hasn't been defined yet.

**4. The SAST market is brutally crowded.**
RepoSec has 40 rules across 6 layers. Semgrep — the open-source leader — has thousands of rules, VC funding, and a growing commercial business. SonarQube supports 30+ languages. An industry analyst in 2025 explicitly warned: "If you're a founder considering building in the SAST space, I would not recommend it." RepoSec as a standalone product faces a near-impossible competitive landscape. Its value is more likely as a portfolio piece, a blog post series ("how I built a security scanner"), or a component inside a larger offering — not as a standalone commercial product.

**5. The voice-to-terminal niche is small and getting crowded.**
Phraser competes with Superwhisper, VoiceInk, Whispering, voice_typing, faster-whisper+ydotool setups, Vibe Transcribe, and others. The "offline, terminal-native" angle is a real differentiator but limits the market to a small subset of privacy-conscious CLI power users. MIT license allows monetization, but with free alternatives everywhere, charging requires a very clear value-add that doesn't exist yet.

**6. Content creation is at zero, not "ready."**
OBS is installed. A studio is documented. But zero videos published, zero blog posts, zero tweets about your work. "Infrastructure to create content" is not content. The indie hacker data is clear: building in public, content marketing, and audience-building are what separate the developers who ship from the developers who build forever in private. Right now you're fully in private.

**7. The 10–20 hrs/week constraint is severe.**
Indie hacker benchmarks: first $100 MRR typically arrives around month 9 of *focused, shipped* work. $2K MRR around month 18. Sustainable income ($10K+ MRR) at 2–3 years — and that's for people who are actively shipping and iterating. At 10–20 hrs/week split across multiple projects, the timeline stretches or never arrives. The math demands extreme focus.

### What This Means Strategically

The honest picture: you have strong technical skills, infrastructure, and a funded runway via the contract. What you lack is everything on the *market side* — users, audience, revenue, competitive positioning, distribution. The technical stack is not the bottleneck. The shipping and selling are.

This isn't unusual. It's the most common failure mode for technical founders: build forever, ship never. The profile above shows all the signs. The question is whether you break the pattern.

---

## The Roadmap — 2 to 3 Years to Full Independence

### The Freedom Number

**Freedom = recurring revenue ≥ living expenses.**

Estimate your monthly living expenses in Montreal. That's the number. C++ contract rates in Montreal for your profile are roughly $75–100+ CAD/hr — call it $12K–16K+ CAD/month gross at full-time. Your ventures need to replace that. At 10–20 hrs/week, you're not going to build a $16K/month business overnight. The realistic intermediate target is $5K CAD/month from ventures — enough to drop to part-time contracting and buy more hours for your own work.

Track this number monthly. Write it down. If it's not moving, something needs to change.

### Phase 0: Triage & Commit (Now — Month 1)

**Goal:** Stop scattering. Pick ONE product bet. Start content immediately.

The biggest risk to your 2–3 year timeline isn't lack of skill — it's spreading 10–20 hrs/week across 7 projects and shipping nothing. The data from successful indie hackers is consistent: focus on one thing, ship it, iterate based on real user feedback.

**Pick ONE product (not two, not three — one):**

The honest ranking by shipping proximity:

1. **VidDocs** — Most infrastructure built, but also the most complex to finish (Steps 1.4–7 are significant application code) and the market already has competitors (Docsie, Y2Doc). If you pick this, you need to define a clear differentiator: self-hosted? Privacy-first local LLM processing? Conference slide detection? "Another YouTube-to-docs tool" won't cut it.

2. **Bear Crypto Club as content-first play** — With 7,000 hours of crypto/DeFi/macro study, you have a genuine knowledge edge. A developer who can explain DeFi mechanics, macro trends, TradingView setups, and TFSA strategy — while also building crypto tools — is a rare content creator. YouTube, blog, or Twitter/X. The audience for crypto education is massive and monetizable (sponsorships, affiliate, courses, community). The risk: crypto content is noisy and full of scammers, so trust-building takes time. The advantage: your depth is real, not surface-level hype.

3. **Harness engineering as content product** — Shortest time-to-audience for a *developer* audience. Blog posts, YouTube videos, and Twitter/X threads about CLAUDE.md setup, cross-agent workflows, AI harness engineering for solo devs. Builds audience first, then sell (templates, course, consulting). The indie hackers who made it (Marc Louvion, Pieter Levels) all built audience before or alongside their products.

4. **RepoSec or Phraser as packaged dev tool** — Fastest to "technically ship" (publish to PyPI or npm, write a landing page). But the competitive landscapes are brutal. RepoSec enters a market dominated by Semgrep and SonarQube. Phraser enters a market with 8+ alternatives. Unless you have a clear angle, these are more valuable as portfolio pieces and content topics than as standalone revenue products.

**Freeze everything else:**
- CapCompare — the domain knowledge is there but no code exists yet, revisit after content traction proves the crypto audience
- Pencil-Sync — niche, dependent on Pencil.dev adoption, revisit later
- Cypher Farms as product — keep the infra running for VidDocs, don't try to sell it separately yet

**Rule:** If it doesn't have users or audience growth within 3 months, reassess.

### Phase 1: Ship & Publish (Months 1–6)

**Goal:** One working product OR one active content channel with measurable audience.

**If you pick VidDocs (10–15 hrs/week):**
- Define the differentiator first. "Self-hosted, privacy-first, local LLM" is a real angle that Docsie and Y2Doc don't offer
- Finish Steps 1.4–1.5 (API routes + auth) — this unblocks the core loop
- Implement Steps 2–3 (YouTube service + transcript) — minimum viable functionality
- MVP target: paste YouTube URL → get structured Markdown documentation. No slide detection, no fancy exports, no multi-format. Just the core loop working
- Ship it publicly. GitHub README that explains the value proposition. A landing page (even a single-page site). Let people try it
- Measure: downloads, GitHub stars, issues filed, anyone actually using it

**If you pick content-first (5–8 hrs/week on content, rest on a product):**
- One published piece per week minimum — blog post, YouTube video, or substantial Twitter/X thread
- Topics you can write about *today* without any new building: how CLAUDE.md works and why, setting up cross-agent workflows (Claude Code + Codex CLI), the Vercel experiment (stripped tools → better accuracy), VidDocs build log, Proxmox GPU cluster for self-hosted AI
- Platform: pick one primary (blog, YouTube, or Twitter/X) and cross-post snippets to the others
- Measure: views, followers, engagement, email signups
- Use the content to discover what people actually want to pay for — let the audience tell you

**Dev tool packaging (2–3 hrs/week alongside either path):**
- Pick one (RepoSec or Phraser). Publish to PyPI or npm. Write a README that sells, not just documents. Write one "why I built this" blog post. This is a portfolio piece and content topic, not the primary revenue bet.

**Contract (Zimmer Biomet):** Keep it. Don't reduce hours. It's funding everything and the ventures aren't generating anything yet.

### Phase 2: Find Signal (Months 6–12)

**Goal:** Evidence that someone other than you cares about what you've built.

This is the make-or-break phase. Most solo developers never get here because they never ship in Phase 1. If you've shipped:

- **Product signal:** Are people using it? Filing issues? Asking for features? If VidDocs has users who come back unprompted, that's signal. If nobody uses it after 3 months of being public, that's also signal — stop and pivot.
- **Content signal:** Is the audience growing? Are people sharing your posts? Asking follow-up questions? If you're publishing weekly and engagement is flat after 6 months, the format or platform isn't working — change it.
- **Revenue experiments:** Can you charge for anything? A hosted VidDocs instance ($10–20/month)? Premium harness engineering templates ($29–99 one-time)? A "build your AI dev workflow" mini-course ($49–149)? Even $500/month proves the model works.

**Key metric:** Any revenue outside the contract? Even $100/month is more than $0/month, and $0/month is what you have now.

**If nothing is working by month 9:** Don't panic, but be honest. Re-read this document. Are you actually shipping, or are you back to building infrastructure? Are you publishing content, or are you "planning to start"? Adjust or pick a different product bet entirely.

### Phase 3: Double Down (Months 12–24)

**Goal:** Venture revenue reaches $2K–5K CAD/month.

- Pour the 10–20 hrs/week into whatever showed signal in Phase 2
- Kill ventures that aren't producing. Not "pause" — actually stop spending time on them
- If content is working: create a paid product (course, templates, consulting)
- If a product is working: add paid tier, improve onboarding, iterate on the thing users ask for
- Start raising contract rates or reducing contract hours only when venture revenue is stable for 3+ consecutive months
- Consider "selective contracts only" — your terms, your rate, higher hourly — as an intermediate step

**Key decision at month 18:** Is the revenue trajectory clear? If venture income is growing month-over-month, plan the contract exit. If it's flat, adjust the timeline to 3–4 years and keep the contract full-time.

### Phase 4: Independence (Months 24–36)

**Goal:** Venture revenue ≥ $5K–8K CAD/month. Contract becomes optional.

- Transition off the contract or go selective (your terms, your rate, your schedule)
- The freed-up 40 hrs/week accelerates what's already working
- At this point you're not starting from zero — you have a product with users, content with an audience, and revenue with history
- Full $12K+ replacement is the stretch goal; $5K–8K plus selective contracting is the realistic "freedom" threshold

**The honest timeline:** Indie hacker data says 2–3 years for sustainable income ($10K+ MRR) with *consistent shipping effort.* At 10–20 hrs/week with a history of not-yet-shipping, 3 years is optimistic. Plan for 3. Celebrate if it's 2.

---

## Anti-Patterns — Ranked by How Likely You Are to Fall Into Them

**1. The infrastructure trap (HIGHEST RISK).**
Your entire history shows this pattern: Proxmox cluster perfected, Docker Compose with 6 services deployed, Ollama VM with GPU passthrough configured, deployment scripts automated, iptables firewall rules written — and the actual application is stalled at Step 1.4 (API routes). The DevOps is gold-plated. The product doesn't work. This is your default mode. Every time you feel the pull to "optimize the cluster" or "refactor the deployment" or "set up a new Ollama model" instead of writing the API routes that make VidDocs functional — that's this trap. Recognize it.

**2. The scatter trap (HIGH RISK).**
7 projects at 2 hrs/week each = 0 products shipped. You already have VidDocs, RepoSec, Phraser, Pencil-Sync, Bear Crypto Club, CapCompare, Cypher Farms, harness engineering templates — and you're working 10–20 hrs/week. The math doesn't work. Each new project idea that excites you is a direct threat to the ones that need to ship. Write the idea in the vault and keep working on the one thing.

**3. The artist's perfectionism (HIGH RISK).**
The 3D artist decade trained you to care about polish, composition, and visual quality. That instinct will tell you VidDocs needs a beautiful UI before you show it to anyone, or that the blog post needs custom illustrations, or that the YouTube video needs professional editing. Ugly but live beats beautiful but unreleased. Every time. The first version should embarrass you slightly — that means you shipped early enough.

**4. The "building in private" trap (HIGH RISK).**
The Obsidian vault is full. The CLAUDE.md is detailed. The harness engineering knowledge is deep. And nobody knows about any of it. Zero published content. Zero public presence beyond a LinkedIn profile. Building in public — sharing progress, writing about what you're learning, showing work-in-progress — is not optional for a solo founder without a marketing budget. It IS the marketing budget.

**5. The contract comfort trap (MEDIUM RISK).**
Zimmer Biomet is stable. Medical device software isn't going away. The paycheck arrives. The danger: if the contract is comfortable enough, the urgency to ship ventures evaporates. You end up in a comfortable loop of "I'll ship next month" for years. Keep the freedom number visible. Track it monthly. If it hasn't moved in 6 months, something is seriously wrong with the plan.

**6. The "one more feature" trap (MEDIUM RISK).**
VidDocs doesn't need slide detection for v1. RepoSec doesn't need 80 rules. Phraser doesn't need a custom UI. The MVP is the smallest thing that proves someone wants what you're building. Everything else is a post-launch feature — if and only if users ask for it.

**7. The solo operator ceiling (LONGER-TERM RISK).**
You're wired to build everything yourself. That works up to a certain revenue level. Past $5K–10K/month, solo operators hit a wall: customer support, feature requests, infrastructure maintenance, and marketing all compete for the same 10–20 hours. At that point, the decision becomes: stay solo and cap revenue, hire/outsource and grow, or keep it lifestyle-scale. This is a good problem to have — and you're nowhere near it yet. But know it's coming.

---

## What You Actually Have (Your Real Moat — and Its Limits)

**The intersection is real, but unproven.**
3D artist background + C++/systems engineering + GPU infrastructure ownership + AI harness engineering + developer tool-building instinct + ~7,000 hours of crypto/finance/macro domain knowledge. This is an unusual combination. But "unusual combination" is not a business. It becomes a business when it's packaged into something someone pays for. The crypto/finance knowledge particularly shifts the picture: Bear Crypto Club and CapCompare aren't random side projects — they're backed by real domain depth. The question is whether that depth gets extracted into content and products, or stays as personal knowledge.

**The infrastructure is real, but it's a cost center until it serves paying users.**
The Proxmox cluster, the GPU nodes, the WireGuard VPN, the self-hosted Ollama — impressive engineering. But infrastructure that only serves your own experiments is an expense and a hobby, not a business asset. It becomes a business asset the moment a paying user's request hits an API endpoint on that cluster.

**The contract skill is real and is your current moat.**
C++ medical device software in Montreal is specialized, in-demand, and hard to automate away. This is what funds the transition. Don't undervalue it. Don't resent it. Use it strategically: it's buying you the 2–3 year runway to build something else. Many indie hackers start with zero runway and fail because they run out of money, not ideas.

**The content knowledge is real but trapped.**
Harness engineering, AI workflow design, multi-agent systems, Proxmox GPU setup — you have content that developers would want to consume. It's all sitting in an Obsidian vault that no one else can see. The shortest path to an audience (and eventually revenue) might not be a product at all — it might be content first, product second. The most successful solo developers in 2025–2026 (Marc Louvion, Pieter Levels, and others) built audience alongside or before their products.

**The bottom line:** You have the technical ingredients. What's missing is the single hardest thing for builders to do — stop building and start shipping. The transition from "talented developer with a vault full of projects" to "entrepreneur with paying customers" requires exactly one thing: getting something — anything — in front of people who aren't you. That's it. Everything else is a distraction from that.

---

*Review this document monthly. Track the freedom number. Count shipped things vs built things. If the shipped count hasn't increased, re-read the anti-patterns section. Adjust based on what's actually working, not what feels most interesting to build.*
