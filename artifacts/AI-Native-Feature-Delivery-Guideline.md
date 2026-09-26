# AI-Native Feature Delivery Guideline
**Version:** 1.2 | **Owner:** Engineering Excellence | **Audience:** Engineering Teams, Tech Leads, Delivery Managers

---

## 1. Philosophy

This guideline operationalises **Context-first, AI-native delivery** — a model where AI acts as a co-engineer across the full feature lifecycle, not a typing accelerant.

The central premise: **AI output quality is bounded by context quality.** A well-constructed context package transforms a vague prompt into production-ready feature delivery. A thin context produces thin software. The team's primary investment is not in writing code faster — it is in assembling, maintaining, and governing context so that AI-assisted generation is deterministic, reviewable, and safe.

This model organises work around **Product Functions** (end-to-end feature slices), not decomposed micro-stories. It follows a strict phase gate sequence and applies both AI-assisted and deterministic quality checks before any artefact is promoted.

---

## 2. Foundational Concepts

### 2.1 Product Function (PF)

A Product Function is the atomic unit of delivery in this model. It represents a complete, independently deployable capability from the user's perspective — not a technical subtask.

**Examples:**
- ✅ "User can authenticate using SSO and receive a scoped JWT" — a Product Function
- ❌ "Create auth controller" — a technical slice, not a Product Function

Each Product Function must be: independently testable, independently deployable (or feature-flaggable), traceable to a business outcome, and completable within a single delivery iteration.

### 2.2 The Context Stack

Context is not a prompt — it is a structured, versioned package assembled before any AI generation begins. The stack has three layers:

| Layer | Source | Purpose |
|-------|--------|---------|
| **Requirement Context** | Jira, Confluence, research, stakeholder notes | Defines *what* and *why* |
| **Technical Context** | Architecture standards, NFR docs, ADRs, team learning docs, anti-pattern register | Defines *how* and *what not to do* |
| **Code Context** | Existing codebase patterns, interface contracts, shared modules, test examples | Grounds generation in the actual system |

All three layers must be present before Phase 1 begins. Missing any layer is a gate failure.

### 2.3 AI Role by Phase

| Phase | AI Mode | Recommended Model | Human Role |
|-------|---------|-------------------|-----------|
| Context Assembly | Summarise, gap-flag | Opus | Assemble, validate |
| Planning | Generate draft plan | Opus | Review, accept/reject |
| HLD | Generate options | Opus | Select, decide |
| LLD | Generate design detail | Opus | Review for correctness |
| Code + Tests | Generate implementation | Sonnet | Review, approve |
| Test Scenarios | Generate scenario matrix | Sonnet | Validate coverage |
| Quality Gates | Execute checks | Sonnet (Security: Opus) | Interpret, remediate |
| PR Review | Analyse diff | Sonnet | Approve, merge |

AI generates; humans decide. Every gate has a human accountable for the output before promotion.

### 2.4 Model Selection Principle

Not all AI tasks are equal in cognitive demand. Routing each task to the right model is a core efficiency and quality decision — not a cost optimisation afterthought.

**Use Claude Opus for reasoning-heavy tasks:**
Opus applies deeper multi-step reasoning, handles ambiguity, and produces more reliable judgement under incomplete information. Use it wherever the output requires architectural thinking, risk identification, constraint reasoning, or security analysis — phases where a wrong decision has downstream consequences that are expensive to fix.

| Task | Why Opus |
|------|----------|
| Context gap analysis (FCD review) | Must identify what is missing, not just what is present |
| Planning generation | Requires sequencing logic, dependency reasoning, risk anticipation |
| High-Level Design | Architectural trade-off reasoning; failure mode identification |
| Low-Level Design | Constraint satisfaction across NFR, security, data, and interface requirements |
| Claude Security Review | Must reason over implicit vulnerabilities, not just pattern-match |
| Anti-pattern disposition | Requires judgement on whether a finding is a genuine risk or acceptable trade-off |

**Use Claude Sonnet for generation-heavy tasks:**
Sonnet delivers high-quality, fast output for well-scoped, well-contextualised generation tasks. Once reasoning is complete and the design is locked, Sonnet executes the implementation efficiently. It is the right choice wherever the prompt is precise and the output is verifiable against a known spec.

| Task | Why Sonnet |
|------|-----------|
| Code generation (given approved LLD) | Scoped, deterministic generation against a known spec |
| Unit test generation | Pattern-based; style follows code context examples |
| Test scenario matrix generation | Systematic enumeration from acceptance criteria |
| Boilerplate, migration scripts, config | High-volume, low-ambiguity output |
| PR diff summary | Summarisation, not reasoning |
| CodeRabbit-style automated review | Pattern detection over structured input |

**The handoff point is the gate.** Opus drives every phase that produces a gate artefact (plan, HLD, LLD, security report). Sonnet executes every phase that consumes an approved gate artefact (code, tests, scenarios). This boundary is deliberate: expensive reasoning happens once, cheap generation executes many times against the reasoned output.

**Cost implication:** An average Product Function uses Opus for approximately 20% of token volume (reasoning phases) and Sonnet for 80% (generation phases). This is the right inversion — most tokens should be cheap because the expensive thinking happened upfront in a structured, reusable context document.

---

## 3. Context Assembly (Pre-Condition to All Work)

No generation phase begins without a complete context package. Context is assembled into a single **Feature Context Document (FCD)** per Product Function.

### 3.1 Requirement Context

**Sources:** Jira epic/story, Confluence functional specs, product research, design artefacts, stakeholder decision logs.

**FCD must contain:**
- Problem statement (one paragraph, user-centred)
- Acceptance criteria (explicit, measurable, numbered)
- Out-of-scope statements (explicit non-goals)
- Edge cases and failure scenarios known at requirements stage
- Links to source Jira/Confluence items (for traceability)
- User journey or API contract (whichever applies)
- Data sensitivity classification (PII, financial, public)

**Quality check:** Each acceptance criterion must be independently verifiable. Criteria that use "should", "may", or subjective language must be rewritten before proceeding.

### 3.2 Technical Context

**Sources:** Architecture Decision Records (ADRs), NFR catalogue, team learning documents, technology standards register, security and compliance guidelines, anti-pattern register.

**FCD must contain:**
- Applicable architecture patterns (e.g., event-driven, CQRS, REST-first)
- NFR targets: latency (p95, p99), throughput, availability SLA, error budget
- Security requirements: auth model, data encryption at rest/transit, secrets handling
- Scalability assumptions: expected load, growth trajectory
- Observability requirements: required metrics, log structure, tracing expectations
- **Anti-pattern register entries applicable to this function** (explicit "do not do" statements)
- Team conventions: naming, folder structure, error handling patterns, dependency rules

**Anti-pattern register format (inline in FCD):**
```
[AP-001] Do not use synchronous HTTP calls between internal services — use async messaging.
[AP-007] Do not store secrets in environment variables — use the secrets manager.
[AP-012] Do not write business logic in controllers — enforce service layer separation.
```

### 3.3 Code Context

**Sources:** Existing service interfaces, shared libraries, database schema, example unit and integration tests, pipeline templates.

**FCD must contain:**
- Relevant interface contracts (API signatures, message schemas)
- Database entity models for affected domains
- Shared utility patterns already in use (e.g., error handling wrapper, logging initialiser)
- 1–2 representative unit test files showing team test style
- CI/CD pipeline template reference

**Code context loading instruction for AI:**
> "The following code excerpts represent existing patterns in this codebase. All generated code must follow these patterns exactly for naming, error handling, logging, and structure. Do not introduce new patterns not present in the examples below."

### 3.4 Data and IP Governance

Sending code and context to external AI APIs creates data exposure risk. This is non-optional governance — not a guideline, not a preference.

**What must never be sent to external AI APIs:**
- Real credentials, API keys, tokens, or secrets (even in comments or test fixtures)
- PII in any form: real names, emails, user IDs, financial data, health data
- Client-confidential code under NDA without explicit data handling confirmation from the AI provider
- Internal infrastructure details: real server names, IP ranges, internal domain names, VPN configurations

**Sanitisation protocol before context assembly:**
1. Strip all credentials from code examples — replace with `<REDACTED>` placeholders
2. Replace real user data in test fixtures with synthetic data
3. Mask internal hostnames and IPs
4. Remove client-identifying comments or file paths

**Enterprise and regulated-industry rule:** For clients in banking, healthcare, or defence, or where the contract prohibits third-party data transfer, the team must use a private or on-prem model deployment. Public API usage requires explicit contractual clearance. The tech lead is accountable for this check before Phase 0 begins.

**Prompt-level data classification check (injected into every AI prompt):**
> "The context provided has been sanitised. If you encounter what appears to be a credential, PII, or sensitive internal reference, flag it immediately and do not use it in generated output."

### 3.5 Context Reuse and Knowledge Transfer

The FCD is a product artefact, not a throwaway prompt. Learnings from completed PFs must feed future work — otherwise each team starting a new PF assembles context from scratch indefinitely.

**Shared Context Baseline:** Maintain a team-level shared context document (`team-context-baseline.md`) containing:
- Stable architecture patterns used by the team (updated after every ADR)
- Active anti-pattern register entries (the master register, not per-PF extracts)
- Canonical code examples for the top 5 recurring patterns (updated quarterly)
- NFR targets that apply globally (overridden per-PF only when justified)

Every new FCD inherits from this baseline. Engineers copy the applicable sections and extend — they do not rebuild from zero.

**Post-PF knowledge capture (mandatory before closing a PF):**
- Did any new anti-pattern emerge? Add to register.
- Did any code pattern prove superior? Promote to shared baseline.
- Did any prompt produce unexpectedly poor output? Document in Appendix D (Prompt Governance Log).
- Did the FCD miss a context element that caused rework? Update the FCD template.

---

## 4. Tech Spec Standard

The Tech Spec is the bridge between requirements and implementation. It is AI-assisted but human-approved before any code generation begins.

### 4.1 Required Sections

**4.1.1 Functional Scope**
- Restatement of the Product Function in engineering terms
- Component boundary map: which services/modules are touched
- Data flow diagram (text-representable or linked Confluence diagram)

**4.1.2 Architecture Decision**
- Selected pattern and rationale (not just what, but why over alternatives)
- Rejected alternatives with reasons (one sentence each)
- ADR reference or new ADR number if a new decision is being made

**4.1.3 NFR Targets (Binding)**

| NFR | Target | Measurement Method |
|-----|--------|--------------------|
| Latency (p95) | < 200 ms | APM trace, load test |
| Latency (p99) | < 500 ms | APM trace |
| Availability | 99.9% | SLA dashboard |
| Error rate | < 0.1% | Error rate alert |
| Throughput | N rps at peak | Load test scenario |

NFR targets are binding. Any generated code that cannot plausibly meet these targets (e.g., an O(n²) query against an unbounded table) is a spec-level failure, not a code review comment.

**4.1.4 Interface Contract**
- API specification (OpenAPI fragment or message schema)
- Input validation rules
- Response structure including error responses
- Idempotency and retry behaviour

**4.1.5 Data Design**
- Schema changes (new tables, columns, indexes)
- Migration strategy
- Data retention and archival rules for new data

**4.1.6 Security & Compliance**
- Auth requirements (who can call this, with what scope)
- Data classification of inputs and outputs
- Encryption requirements
- Audit logging requirements

**4.1.7 Observability Design**
- Metrics to emit (counter, gauge, histogram — named explicitly)
- Log events required (with structured fields)
- Distributed trace span requirements
- Alerting thresholds

**4.1.8 What Not to Do (Function-Specific)**
Translate relevant anti-pattern register entries into specific prohibitions for this function. This section is injected verbatim into every AI code generation prompt.

### 4.2 Tech Spec Approval Gate

The tech spec is reviewed by the tech lead and one peer before any generation begins. Review criteria:

- [ ] NFRs are quantified and measurable
- [ ] Interface contract covers all error cases
- [ ] Data design handles migration safely
- [ ] Security section reviewed by security-aware engineer
- [ ] Anti-patterns section is specific, not generic
- [ ] No ambiguity in acceptance criteria

---

## 5. Definition of Done (DoD)

DoD is derived from the intersection of requirement acceptance criteria and tech spec targets. It is not a checklist appended after build — it is the pre-agreed contract that shapes all generation.

### 5.1 DoD Structure

**Functional completeness:**
- [ ] All acceptance criteria from Requirement Context pass in integration test
- [ ] All edge cases and failure scenarios from requirements have explicit test coverage
- [ ] No acceptance criterion is met by test workaround (e.g., mocked dependency hiding real failure)

**Technical correctness:**
- [ ] NFR targets met under representative load (evidence required: test report or APM screenshot)
- [ ] Interface contract matches spec exactly (no undocumented deviations)
- [ ] Data migration tested on production-representative dataset
- [ ] No anti-pattern register violations (CodeRabbit + manual confirmation)

**Security:**
- [ ] Claude Security Review: zero high or critical findings
- [ ] All secrets accessed via secrets manager (no env var secrets)
- [ ] Auth enforced at correct layer (not business logic)
- [ ] Input validation covers all external inputs

**Observability:**
- [ ] All required metrics emitted and visible in dashboard
- [ ] Log events present with correct structured fields
- [ ] Distributed trace spans created as specified

**Quality gates passed:**
- [ ] Linting: zero violations (hard block, not warning)
- [ ] Unit test coverage: ≥ 80% line coverage on new code
- [ ] Integration tests: all scenarios pass
- [ ] CodeRabbit review: no unresolved medium+ comments
- [ ] Claude Security Review: completed, findings addressed

**Documentation:**
- [ ] API contract updated in shared spec repository
- [ ] ADR created or referenced for any new architecture decision
- [ ] Confluence updated if functional behaviour changed

DoD is signed off by the tech lead and the delivery manager. Any unchecked item blocks PR merge.

---

## 6. Product Function Delivery Lifecycle

### Phase 0 — Context Assembly
**Owner:** Tech Lead + Engineer  
**Gate:** Complete FCD signed off by tech lead

1. Pull Jira epic and linked stories into FCD requirement section
2. Pull applicable Confluence specs and research into FCD
3. Extract relevant ADRs, NFR catalogue entries, anti-patterns into FCD technical section
4. Pull code context: interface files, schema, test examples into FCD code section
5. Validate FCD completeness checklist (all three layers present)
6. Tech lead signs off FCD before proceeding

**AI use in this phase:** Use **Opus** — gap identification requires reasoning over what is absent, not just present. Opus summarises source documents, flags missing acceptance criteria, identifies ambiguous NFR targets, and surfaces unstated assumptions. Human validates every item.

---

### Phase 1 — Planning Generation
**Owner:** Tech Lead  
**Gate:** Approved delivery plan with effort estimate

**Model: Opus** — dependency sequencing, risk anticipation, and effort reasoning require multi-step judgement.

**AI prompt pattern:**
> "Given the Feature Context Document below, generate a delivery plan for this Product Function. The plan must include: ordered implementation phases, dependencies between phases, effort estimates per phase (in hours), risks and assumptions. Use only the architecture patterns and constraints from the Technical Context. Do not suggest new tools or patterns not present in the context."

**Output:** A phased plan covering HLD → LLD → Implementation → Testing → Observability wiring → Deployment. Tech lead reviews for completeness, risks, and realistic estimates. Plan is logged in Jira as the implementation epic breakdown.

---

### Phase 2 — High-Level Design (HLD)
**Owner:** Tech Lead  
**Gate:** Approved HLD document, peer-reviewed

**Model: Opus** — architectural trade-off reasoning, failure mode identification, and NFR compliance analysis require deep multi-step reasoning.

**AI prompt pattern:**
> "Using the approved delivery plan and Feature Context Document, generate a High-Level Design for [Product Function]. Cover: component interactions, data flow, external dependencies, failure modes, and how NFR targets will be met. Reference anti-patterns from the context and explicitly state how this design avoids them."

**HLD must produce:**
- Component diagram (text-representable)
- Sequence diagram for the primary flow and at least two failure flows
- NFR compliance rationale (how latency, throughput, availability targets are met)
- Risk register (top 3 risks with mitigations)

**Review:** Tech lead + one peer. Any unresolved risk blocks progression to LLD.

---

### Phase 3 — Low-Level Design (LLD)
**Owner:** Engineer + Tech Lead  
**Gate:** Approved LLD with interface contracts and data model

**Model: Opus** — constraint satisfaction across NFR, security, data model, and interface requirements simultaneously; errors here propagate directly into generated code.

**AI prompt pattern:**
> "Using the approved HLD and Feature Context Document, generate a Low-Level Design for [component/module]. Include: class/function signatures, data models, error handling strategy, unit test strategy, and database query patterns. All signatures must follow the code style and patterns shown in the Code Context section. Apply anti-patterns from context."

**LLD must produce:**
- Function/method signatures with parameter types and return types
- Database schema changes with migration scripts
- Error taxonomy: named error types, HTTP status codes, log levels
- Unit test strategy: what is tested at unit level vs integration level
- Configuration schema for any new config introduced

**Review:** Tech lead review for correctness against spec. Any deviation from tech spec requires spec amendment (not silent code deviation).

---

### Phase 4 — Code and Unit Test Generation
**Owner:** Engineer  
**Gate:** All unit tests pass; linting passes; code matches LLD

**Model: Sonnet** — generation is scoped and deterministic once the LLD is approved; Sonnet produces high-quality output faster and at lower cost for well-specified tasks.

**AI prompt pattern:**
> "Generate production-quality implementation code for [module] based on the approved LLD below. Code must: follow all patterns in the Code Context exactly, implement all error handling from the LLD error taxonomy, include structured logging for all log events in the Observability Design, enforce input validation for all external inputs, and contain no secrets or hardcoded configuration. Generate complete unit tests alongside the implementation covering happy path, all error paths, and boundary conditions."

**Code generation rules (injected into every prompt):**
- Anti-pattern section from FCD is appended verbatim
- Code context examples are appended verbatim
- "Do not introduce dependencies not present in the existing dependency manifest"
- "Do not write business logic in [controllers/handlers] — use the service layer"
- "All database access must go through the repository layer"

**Post-generation engineer checklist:**
- [ ] Generated code reads correctly (no hallucinated APIs or non-existent methods)
- [ ] All LLD signatures are implemented as specified
- [ ] No hardcoded values (configs, secrets, URLs)
- [ ] Unit tests cover all paths defined in LLD test strategy
- [ ] Linting passes locally before committing

**AI Hallucination Validation Protocol:**

Hallucinations in code generation manifest in specific, detectable ways. Engineers must run this protocol on every generation output before committing — not after.

| Signal | Check | Resolution |
|--------|-------|-----------|
| Import does not resolve | Run `npm install` / `mvn dependency:resolve` / `pip check` — zero unresolved imports | Remove import; find correct package or flag in context |
| Method does not exist on library | Cross-reference generated calls against the library's actual API (docs or IDE) | Replace with correct method; add correct example to Code Context |
| Class or interface not in codebase | Search codebase for the referenced class name | Add the actual class to Code Context and regenerate |
| DB column or table referenced does not exist | Compare against schema in FCD Code Context | Add schema to Code Context and regenerate the data layer |
| Config key not in config schema | Check generated config references against defined config schema | Add schema to FCD and regenerate config access code |

**Regeneration trigger:** If more than 25% of generated code requires correction for hallucination (not style or preference), the context is insufficient. Do not patch line by line — identify the missing context element, add it to the FCD Code Context, and regenerate the module. Patching hallucinated code without improving context guarantees the same failure on the next generation.

**Confidence signals that warrant extra scrutiny:**
- AI uses a library version that does not match the dependency manifest
- AI generates a design pattern not shown in Code Context examples
- AI references a service or API not mentioned in the FCD
- Generated test mocks a dependency in a way inconsistent with the test style example

---

### Phase 5 — Testing Scenarios and Quality Gate

**5.1 Test Scenario Generation**

After code is written, AI generates the full test scenario matrix from the FCD.

**Model: Sonnet** — systematic enumeration from well-defined acceptance criteria; the FCD provides the complete input; no open-ended reasoning required.

**AI prompt pattern:**
> "Using the acceptance criteria, edge cases, and failure scenarios in the Feature Context Document, generate a complete test scenario matrix. For each scenario: provide a scenario ID, description, input conditions, expected outcome, test type (unit/integration/e2e/load), and DoD criterion it validates. Flag any acceptance criterion with no corresponding scenario."

**Test types required per Product Function:**

| Test Type | Scope | Tooling | Gate |
|-----------|-------|---------|------|
| Unit | Function/class level | Jest / JUnit / pytest | All pass before PR |
| Integration | Service + dependency | Testcontainers / WireMock | All pass before PR |
| Contract | API interface | Pact / OpenAPI validator | All pass before PR |
| Security | SAST, secrets scan | Claude Security Review + Snyk | Zero high/critical before PR |
| Load | NFR targets | k6 / Gatling | NFR targets met before PR |
| E2E | User journey | Playwright / Cypress | Smoke set passes before deploy |

**5.2 Deterministic Quality Gates**

These run in CI on every commit. All are hard blocks — pipeline fails on any violation.

**Gate 1 — Linting:**
- ESLint / Checkstyle / Pylint at maximum project-defined rule set
- Zero warnings tolerated (warnings are treated as errors in CI config)
- Formatter check (Prettier / Black) — format violations block pipeline
- Import order and unused import checks

**Gate 2 — CodeRabbit Automated Review:**
- Triggered on every PR automatically
- Reviews for: code smells, complexity violations, missing error handling, performance anti-patterns, test coverage gaps
- Any comment at severity medium or above must be resolved or explicitly acknowledged with a written rationale before merge
- CodeRabbit summary is included in the PR description

**Gate 3 — Claude Security Review:**
- **Model: Opus** — security analysis requires reasoning over implicit vulnerability paths, not just pattern matching; use Opus for all security review prompts (see Appendix B.4)
- Run as a CI step using a structured security prompt against the full diff
- Prompt covers: injection risks, broken auth, sensitive data exposure, security misconfiguration, insecure dependencies, secrets in code, input validation gaps
- Zero high or critical findings to pass
- Medium findings: engineer must provide written disposition (fix / accept risk with rationale)
- Output appended to PR as a comment for audit trail

**Gate 4 — Unit Test Coverage:**
- Coverage report generated on every CI run
- New code: ≥ 80% line coverage (hard gate)
- Coverage delta tracked: no PR may reduce coverage below current baseline

**Gate 5 — Dependency Scan:**
- OWASP dependency check or Snyk on every PR
- Zero known critical CVEs in new or updated dependencies
- High CVEs: must have accepted risk documentation or fix

---

### Phase 6 — Pull Request and Approval

**6.1 PR Structure (Required)**

Every PR must contain:
- **Title:** `[PF-ID] Product Function name — phase (e.g., Implementation, LLD)`
- **Description sections:**
  - What this PR does (one paragraph)
  - How to test it (steps a reviewer can follow)
  - DoD checklist with completion status for every item
  - CodeRabbit summary (auto-appended by CI)
  - Claude Security Review output (auto-appended by CI)
  - Any anti-pattern dispositions (if a medium finding was accepted)
  - Links: Jira PF, FCD, Tech Spec, LLD

**6.2 Review Approval Requirements**

| Reviewer | Role | Mandatory |
|----------|------|-----------|
| Tech Lead | Architecture, pattern adherence, LLD compliance | Yes — always |
| Peer Engineer | Code correctness, test quality, readability | Yes — always |
| Security Engineer | Security findings disposition | Yes — if any medium+ security finding |

Review is not a rubber stamp. Each reviewer must confirm:
- [ ] DoD checklist is complete and accurate (not aspirational)
- [ ] CodeRabbit findings are resolved or dispositioned
- [ ] Claude Security findings are resolved or dispositioned
- [ ] Code matches LLD (no silent design deviations)
- [ ] Test scenarios from the matrix are implemented

**6.3 Post-Approval Test Run**

After all approvals, CI executes the full test suite:
1. Unit tests — all pass (required)
2. Integration tests — all pass (required)
3. Contract tests — all pass (required)
4. Security scan — zero new high/critical (required)
5. Coverage gate — no regression (required)
6. Load test (smoke) — NFR targets met at baseline load (required before pre-prod promote)

No merge until all six pass. This is enforced via branch protection — not a social contract.

---

## 7. Definition of Readiness (DoR) — Environment Promotion

DoR governs promotion between environments. It is distinct from DoD (which governs PR merge). A feature can pass DoD but fail DoR if environment-specific conditions are not met.

### 7.1 DoR: Lower → QA

- [ ] All DoD items complete
- [ ] Feature flag created and defaulted to off in QA
- [ ] Integration test suite passes against lower environment
- [ ] Database migration tested on lower; rollback script verified
- [ ] No unresolved P1/P2 bugs from lower testing
- [ ] QA engineer has reviewed and accepted test scenarios matrix

### 7.2 DoR: QA → Pre-Production

- [ ] QA sign-off: all acceptance criteria verified in QA environment
- [ ] Load test executed: NFR targets met at production-representative load
- [ ] Security review: no open high/critical findings
- [ ] Observability verified: all metrics and log events visible in APM/dashboards
- [ ] Runbook written: deployment steps, rollback procedure, monitoring checklist
- [ ] Feature flag toggle tested (on/off behaviour confirmed in QA)

### 7.3 DoR: Pre-Production → Production

- [ ] Pre-prod sign-off from tech lead and delivery manager
- [ ] Runbook reviewed and approved
- [ ] On-call engineer briefed on rollback procedure
- [ ] Deployment window confirmed (no conflicting releases)
- [ ] Feature flag strategy confirmed: % rollout or full enable
- [ ] Monitoring alert thresholds confirmed active
- [ ] Rollback time objective defined (how long before rollback is triggered if error rate exceeds threshold)

---

## 8. Governance and Anti-Patterns

### 8.1 Context Governance

Context is a living asset. It degrades if not maintained.

- FCD must be updated when requirements change (not after, not retrospectively)
- Anti-pattern register is owned by the tech lead; entries are added after every post-incident review
- Code context examples must be refreshed when team coding standards change
- Tech specs are versioned; a change to a spec after LLD requires re-approval

### 8.2 Process Metrics — How to Know It Is Working

This model must be measurable. Without metrics, adoption becomes faith-based. The following indicators are tracked per PF and rolled up per sprint.

**Input quality metrics (context and spec):**

| Metric | Definition | Target | Warning signal |
|--------|-----------|--------|---------------|
| FCD assembly time | Hours from PF initiation to tech lead FCD sign-off | < 8 hours | > 16 hours = context is being forced, not assembled |
| FCD rejection rate | % of FCDs sent back by tech lead for rework | < 15% | > 30% = engineers not using the template correctly |
| Tech spec cycle time | Hours from FCD sign-off to tech spec approval | < 4 hours | > 8 hours = spec ambiguity or alignment gap |

**Generation quality metrics:**

| Metric | Definition | Target | Warning signal |
|--------|-----------|--------|---------------|
| AI rework rate | % of generated code requiring significant human rewrite (>20% of lines changed) | < 20% | > 40% = context is thin or wrong |
| Hallucination rate | % of generation outputs containing at least one hallucinated import/method | < 10% | > 25% = Code Context needs richer examples |
| Gate rejection rate | % of PRs rejected at first review (DoD incomplete, CodeRabbit unresolved) | < 10% | > 25% = DoD not being used during development |

**Delivery quality metrics:**

| Metric | Definition | Target | Warning signal |
|--------|-----------|--------|---------------|
| Defect escape rate | Bugs found post-merge that should have been caught by DoD gates | < 5% of PFs | Any recurring category = gate miscalibration |
| PR cycle time | Hours from first commit to merge | < 24 hours | > 48 hours = review bottleneck or quality gate failure loop |
| Context reuse rate | % of a new FCD's technical context inherited from shared baseline vs written from scratch | > 60% | < 30% = shared baseline not maintained |

**Connection to Five-Index Framework:**
These metrics are not standalone — they map directly to the Cybage Five-Index measurement model:
- FCD quality + AI rework rate → **Adoption Index** (are teams using the model correctly?)
- Defect escape rate + hallucination rate → **Quality Index** (is AI-generated output trustworthy?)
- PR cycle time + gate rejection rate → **Velocity Index** (is the model accelerating or adding friction?)
- Context reuse rate → **Utilisation Index** (is accumulated knowledge being leveraged?)

### 8.3 Continuous Improvement Cycle

**Sprint retrospective (every sprint):**
- Review any gate blocked more than once — identify root cause
- Review any AI rework rate > 40% on a PF — identify missing context element
- Review any new incident or production defect — add to anti-pattern register
- Prompt log review: any prompt that produced poor output this sprint (see Appendix D)

**Quarterly review (tech lead + engineering lead):**
- Review FCD template against the last quarter's PFs — update sections that were consistently skipped or consistently incomplete
- Review shared context baseline — are the canonical code examples still current?
- Review Appendix B prompt templates against current model versions — re-run on three historical PF scenarios and compare output quality
- Review anti-pattern register for consolidation — merge related entries, retire resolved entries

**Model version assessment (when AI provider releases a new version):**
- Re-run Appendix B prompts on three historical PF scenarios
- Compare output quality: equivalent / better / worse per prompt
- If materially better: update the model recommendation in Section 2.4
- If regression on any prompt: update the prompt to compensate before switching

### 8.4 Anti-Patterns in This Model

These are failure modes observed in teams adopting context-first delivery. Treat them as hard rules.

**[AP-M-001] Thin context, fast generation**
Skipping FCD assembly to start coding faster. Produces technically complete but functionally wrong code. The rework cost exceeds the time saved.

**[AP-M-002] Context as a one-time document**
Writing the FCD at the start and never updating it. AI generation on stale context produces confidently wrong output. FCD must be live throughout the delivery cycle.

**[AP-M-003] AI review replacing human review**
Using CodeRabbit and Claude Security Review as the only review mechanism, skipping the tech lead review. Deterministic tools catch structural issues; they do not catch design intent misalignment, team knowledge gaps, or strategic errors.

**[AP-M-004] Merging without full test gate**
Merging a PR when all human approvals are in but waiting for CI to "catch up." This breaks the sequence guarantee. Tests must be green before merge — no exceptions.

**[AP-M-005] Product Function too large**
A PF that spans multiple services, multiple data domains, and multiple teams is not a PF — it is a programme. PFs that cannot be completed in one iteration must be decomposed before the context assembly phase begins.

**[AP-M-006] Skipping observability wiring**
Treating metrics and logging as post-delivery cleanup. Observability is part of DoD. Features that cannot be measured in production are not complete.

**[AP-M-007] Anti-pattern register not maintained**
The register only works if it is updated continuously. A register last updated six months ago is not a guardrail — it is documentation theatre. Tech leads own this and update it as part of every retrospective.

**[AP-M-008] Sensitive data in AI prompts**
Code context assembled from real test fixtures, integration configs, or legacy code often contains credentials, real user data, or client-identifying information. Sending this to an external AI API is a data breach risk regardless of the provider's stated policies. Sanitisation is mandatory before context assembly, not optional. The tech lead is accountable for confirming this before Phase 0 sign-off.

**[AP-M-009] Prompt drift without governance**
Teams customise Appendix B prompts informally — adding instructions, removing hard rules, adjusting tone — without versioning or approval. Over time, different engineers use materially different prompts for the same task, producing inconsistent AI output. Prompt changes must go through the same review process as code changes. See Appendix D for prompt governance protocol.

**[AP-M-010] Patching hallucinations instead of improving context**
When AI generates incorrect code, the instinct is to fix the individual lines. This treats the symptom. Hallucinations are a context signal: the AI lacked information it needed. The correct response is to identify what was missing, add it to the FCD, and regenerate. Teams that patch without improving context will see the same hallucinations in the next PF that touches the same domain.

**[AP-M-011] Isolated FCD assembly with no shared baseline**
Every PF builds its technical context from scratch because no team-level baseline exists. This means anti-patterns are discovered repeatedly, code examples are inconsistently chosen, and NFR targets vary without justification. Maintaining the shared context baseline (`team-context-baseline.md`) is not overhead — it is the compounding return on prior delivery investment.

---

## 9. Escalation and Exception Paths

The gate model works when gates resolve cleanly. It must also specify what happens when they do not.

### 9.1 Blocked FCD — Requirements Not Available

**Trigger:** Phase 0 cannot complete because Jira/Confluence content is missing, ambiguous, or contradictory.

**Resolution path:**
1. Engineer flags to tech lead within 4 hours of starting FCD assembly
2. Tech lead contacts the product owner with a specific list of missing items (not a general "unclear requirements" note)
3. Product owner has 1 business day to provide resolution or schedule a clarification session
4. If unresolved at 1 business day: delivery manager escalates to programme lead
5. PF does not proceed to Phase 1 until FCD is signed off — no exception

### 9.2 Gate Rejection Loop (> 2 Rejections at the Same Gate)

**Trigger:** A PF is rejected at the same gate more than twice.

**This is a process signal, not an engineer performance signal.** Two rejections mean either the gate criteria are ambiguous or the engineer has not been adequately coached on the model.

**Resolution path:**
1. On the third rejection, tech lead pairs with the engineer to complete the gate artefact together — not as a review but as a working session
2. Tech lead documents what was missing or misunderstood
3. If the gap was a template ambiguity: update the FCD template or DoD checklist
4. If the gap was an engineer capability gap: schedule targeted coaching before the next PF

### 9.3 Security Finding with Ambiguous Severity

**Trigger:** Claude Security Review produces a finding where the correct severity is genuinely debatable (e.g., a potential injection vector with compensating controls already in place).

**Resolution path:**
1. Engineer proposes a disposition with written rationale (fix / accept risk / false positive) within 24 hours of the finding
2. Security engineer reviews and confirms or corrects the disposition within 48 hours
3. If the security engineer and tech lead disagree: engineering lead makes the final call and documents it
4. The finding and its disposition are recorded in the PR comment permanently — never silently closed

### 9.4 Critical Hotfix — Abbreviated Process

**When applicable:** A production defect or security vulnerability requires a fix that cannot wait for the full lifecycle. This is declared by the engineering lead, not self-assigned by engineers.

**Abbreviated gate sequence (hotfix only):**
1. FCD: requirement context only (no full technical context required) — time target < 2 hours
2. Skip Phase 1 (planning) and Phase 2 (HLD)
3. Phase 3 (LLD): tech lead drafts the LLD directly, not AI-generated — time target < 1 hour
4. Phase 4 (Code): Sonnet generation against the LLD, with tech lead pairing
5. Phase 5 (Testing): unit tests for the specific fix only; existing regression suite must pass
6. Phase 6 (PR): tech lead is both author-reviewer and approver — a second engineer must also approve
7. Quality gates: linting and Claude Security Review are mandatory — no skipping
8. Deploy via feature flag to 5% traffic, monitor for 30 minutes before full rollout

**Post-hotfix obligation:** Within 3 business days of the hotfix, a full retrospective is held and any anti-pattern identified is added to the register. The abbreviated FCD is expanded to full FCD standard.

### 9.5 Greenfield Context — No Existing Codebase

**Trigger:** A new service or repository is being started with no existing code context to reference.

**Resolution path:**
1. Tech lead selects the closest analogous service in the organisation's portfolio as the code context source
2. If no analogous service exists: the team defines the patterns explicitly in the FCD Code Context (naming conventions, error handling approach, test style) before any generation
3. The first PF on a greenfield service must have the tech lead pair with the engineer for Phase 4 — the generated output sets the pattern baseline for all future PFs on that service
4. After the first PF is merged, the patterns are immediately added to the shared context baseline

---

## 10. Roles and Responsibilities

| Role | Responsibilities |
|------|-----------------|
| **Tech Lead** | FCD approval, tech spec approval, HLD review, PR approval, DoR sign-off, escalation resolution |
| **Engineer** | FCD assembly, LLD generation, code review of AI output, unit test ownership, PR authorship, hallucination protocol execution |
| **Delivery Manager** | DoD completeness verification, DoR sign-off for pre-prod → prod, PF scope governance, blocked FCD escalation |
| **QA Engineer** | Test scenario matrix review, QA environment sign-off, DoR: QA → pre-prod gate |
| **Security Engineer** | Claude Security Review disposition review, DoR: pre-prod → prod security gate, ambiguous finding resolution |
| **Engineering Lead** | Security finding final arbitration, hotfix declaration, process metric review (quarterly) |

---

## 11. Quick Reference — Gate Sequence

```
Context Assembly (FCD complete) ──► [GATE: Tech Lead FCD sign-off]
         │
         ▼
Planning Generation ──────────────► [GATE: Tech Lead plan approval]
         │
         ▼
High-Level Design ────────────────► [GATE: Tech Lead + peer HLD review]
         │
         ▼
Low-Level Design ─────────────────► [GATE: Tech Lead LLD review]
         │
         ▼
Code + Unit Tests ────────────────► [GATE: Linting pass, unit tests pass]
         │
         ▼
Test Scenario Matrix ─────────────► [GATE: QA review of scenarios]
         │
         ▼
Deterministic Quality Gates ──────► [GATE: CodeRabbit, Claude Security,
         │                                   Coverage, Dependency scan]
         ▼
PR: Human Reviews ────────────────► [GATE: Tech Lead + Peer approval]
         │
         ▼
Post-Approval CI ─────────────────► [GATE: All test types pass]
         │
         ▼
Merge to Main ────────────────────► [DoR: Lower → QA]
         │
         ▼
QA Sign-off ──────────────────────► [DoR: QA → Pre-prod]
         │
         ▼
Pre-prod Sign-off ────────────────► [DoR: Pre-prod → Prod]
         │
         ▼
Production Deploy (feature flagged)
```

---

## Appendix A — Feature Context Document (FCD) Template

```markdown
# FCD: [Product Function Name]
**PF-ID:** [Jira Epic ID] | **Version:** 1.0 | **Owner:** [Tech Lead name]
**Status:** Draft / Approved / Active / Superseded

---
## Requirement Context
### Problem Statement
[One paragraph. User-centred. What problem does this solve and for whom?]

### Acceptance Criteria
1. [AC-01] …
2. [AC-02] …
[Each must be independently verifiable]

### Non-Goals
- …

### Edge Cases and Failure Scenarios
- …

### Source References
- Jira: [link]
- Confluence: [link]
- Data classification: [PII / Financial / Internal / Public]

---
## Technical Context
### Applicable Architecture Patterns
- …

### NFR Targets
| NFR | Target | Measurement |
|-----|--------|-------------|
| Latency p95 | | |
| Availability | | |

### Anti-Pattern Register (applicable entries)
- [AP-XXX] …

### Team Conventions
- …

---
## Code Context
### Interface Contracts
[Paste or link relevant interfaces]

### Database Entities
[Paste or link relevant models]

### Test Style Example
[Paste representative test file excerpts]

### CI/CD Template Reference
[Link or name]
```

---

## Appendix B — Claude Prompt Templates

Model assignments are stated per template. Do not substitute models — the assignment reflects the reasoning demand of the task.

**B.1 HLD Generation**
**Model: Claude Opus** — architectural reasoning, failure mode analysis, NFR trade-off judgement.
```
You are a senior software architect. Generate a High-Level Design for the Product Function described in the Feature Context Document below.

Requirements:
- Follow only the architecture patterns listed in Technical Context
- NFR targets are binding — design must explicitly address how each target is met
- Failure modes must be identified for primary and secondary flows
- Anti-patterns listed in Technical Context must be explicitly avoided

Output format:
1. Component interaction description
2. Primary flow sequence (text-representable)
3. Failure flow sequences (minimum 2)
4. NFR compliance rationale
5. Top 3 risks with mitigations

[PASTE FCD HERE]
```

**B.2 Code Generation**
**Model: Claude Sonnet** — scoped generation against an approved LLD; high-volume, deterministic output.
```
You are a senior software engineer. Generate production-quality implementation code for [module name] based on the Low-Level Design below.

Hard rules — these are non-negotiable:
- Follow every pattern shown in the Code Context exactly (naming, error handling, logging, structure)
- Apply every anti-pattern prohibition listed below
- Do not introduce dependencies not in the existing dependency manifest
- All configuration must come from the config schema — no hardcoded values
- All external inputs must be validated before use
- Emit structured log events at points specified in the Observability Design

Generate alongside the implementation:
- Complete unit tests covering happy path, all error paths, and boundary conditions
- Test style must match the test style shown in Code Context

[PASTE FCD — Technical Context, Code Context, LLD, Anti-patterns]
```

**B.3 Test Scenario Matrix Generation**
**Model: Claude Sonnet** — systematic enumeration from well-defined acceptance criteria; no ambiguous reasoning required.
```
You are a QA engineer. Using the acceptance criteria, edge cases, and failure scenarios in the Feature Context Document below, generate a complete test scenario matrix.

For each scenario provide:
- Scenario ID
- Description
- Input conditions
- Expected outcome
- Test type (unit / integration / contract / load / e2e)
- DoD criterion it validates

Flag any acceptance criterion with no corresponding scenario as a coverage gap.

[PASTE FCD — Requirement Context section only]
```

---

**B.4 Claude Security Review**
**Model: Claude Opus** — implicit vulnerability reasoning, not pattern matching; finding disposition requires judgement.
```
You are a security engineer reviewing a code diff. Analyse the following changes for security vulnerabilities.

Check for:
- Injection risks (SQL, command, template, header)
- Broken or missing authentication/authorisation
- Sensitive data exposure (logging PII, unencrypted storage)
- Security misconfiguration (CORS, headers, TLS settings)
- Insecure dependencies (flag any new dependency for manual CVE check)
- Hardcoded secrets or credentials
- Missing input validation on external inputs
- Insecure direct object references

For each finding, provide:
- Severity: Critical / High / Medium / Low / Informational
- Location: file and line
- Description: what the vulnerability is
- Remediation: specific fix

Output a summary line at the end: "Security gate: PASS / FAIL — [N] findings above Medium"

[PASTE DIFF HERE]
```

---

---

## Appendix C — Team Adoption Ramp-Up Path

This guideline does not activate by being published. Transformation requires a staged adoption sequence. Skipping stages produces a team that is nominally compliant but practically reverting to old habits within two sprints.

### Prerequisites: AI Literacy Baseline

Before a developer works their first PF under this model, they must be able to:
- Write a structured prompt with context injection and hard constraints (not just "write me a function that…")
- Read AI-generated code critically — identifying hallucinations, pattern violations, and missing error handling
- Understand the FCD template sufficiently to assemble one for a small, well-defined requirement
- Know the difference between Opus and Sonnet for their tasks (see Section 2.4)

If the team does not have this baseline, a half-day AI literacy workshop precedes Stage 1.

### Stage 1 — Pilot (Weeks 1–2)

**Who:** One senior engineer + tech lead, working together.  
**What:** One low-risk, well-understood PF — an enhancement to an existing feature, not a net-new domain.  
**Goal:** Complete the full lifecycle end-to-end, surface every friction point, validate the gate sequence.

- The tech lead assembles the FCD and the engineer reviews it (inverted for learning)
- Both attend every phase review together
- After completion: 30-minute debrief — what worked, what was awkward, what was missing from the templates
- Update FCD template and Appendix B prompts based on findings before Stage 2

### Stage 2 — Expansion (Weeks 3–4)

**Who:** Two engineers independently, tech lead reviewing both.  
**What:** Two concurrent PFs of moderate complexity.  
**Goal:** Validate that the model works without tech lead co-piloting; identify coaching gaps.

- Each engineer assembles their own FCD independently
- Tech lead reviews both FCDs in a shared session (30 minutes) — surface inconsistencies in how the template is being applied
- Any hallucination or gate rejection is reviewed as a team learning, not an individual failure

### Stage 3 — Full Team Adoption (Month 2)

**Who:** Entire team.  
**What:** All new PFs follow the model; existing work in flight continues under old process until complete.  
**Goal:** Establish the model as the default, not the exception.

- Introduce DoR gates for the first time — Stage 1 and 2 pilots may have used simplified DoR
- Begin tracking process metrics (Section 8.2) from this point
- Hold the first formal retrospective using the continuous improvement cycle (Section 8.3)
- Update the shared context baseline with patterns learned from Stage 1 and 2

### Stage 4 — Optimisation (Month 3+)

**Who:** Entire team with engineering lead visibility.  
**What:** Model is stable; focus shifts to efficiency and measurement.  
**Goal:** Measurable improvement in Quality and Velocity indexes.

- Process metrics reviewed in every sprint retrospective
- Anti-pattern register actively maintained
- Prompt library expanded from team-specific learnings
- Context reuse rate tracked and improving
- Engineering lead assesses transformation progress against Five-Index baseline

**Adoption is complete when:** the team reaches a context reuse rate > 60%, AI rework rate < 20%, and defect escape rate < 5% — sustained over three consecutive sprints.

---

## Appendix D — Prompt Governance

Prompts in Appendix B are the operational interface between this guideline and AI models. They are not static artefacts — they require governance equivalent to code.

### D.1 Prompt Versioning

Each prompt in Appendix B carries a version number, model target, and last-verified date. Format:

```
Prompt: B.1 — HLD Generation
Version: 1.0 | Model: Claude Opus | Last verified: [date] | Owner: Tech Lead
```

When a prompt is modified, the version is incremented and the change is logged in D.3.

### D.2 Prompt Change Protocol

1. Engineer or tech lead proposes a change to an Appendix B prompt with a written rationale
2. The proposed prompt is tested against three historical PF scenarios (or representative synthetic scenarios)
3. Tech lead compares output quality: equivalent / better / worse on each scenario
4. If better or equivalent: change approved, version incremented
5. If worse on any scenario: change rejected or revised before re-testing
6. Approved changes are applied to the shared prompt library and the guideline simultaneously

Hard rules in prompts (the `Non-negotiable:` sections) may only be removed by the engineering lead, not by individual tech leads.

### D.3 Prompt Performance Log

Maintain a running log of prompt outputs that were unexpectedly poor. This is the early-warning system for model drift and context decay.

| Date | Prompt | PF | Issue observed | Root cause | Resolved by |
|------|--------|-----|----------------|-----------|-------------|
| [date] | B.2 Code Gen | PF-042 | Hallucinated non-existent ORM method | Code context missing ORM example | Added ORM examples to shared baseline |

Review this log in every quarterly process review. Patterns in the log indicate either a prompt that needs updating or a context baseline that is degrading.

### D.4 Model Version Transition Protocol

When the AI provider releases a new model version:
1. Do not switch immediately in production prompts
2. Run each Appendix B prompt against three historical PF scenarios on the new model version
3. Document output quality delta in the Prompt Performance Log
4. If all prompts perform equivalently or better: update model references in Section 2.4 and Appendix B, communicate to team
5. If any prompt regresses: update that prompt to compensate before switching
6. Staged rollout: switch Sonnet prompts first (lower risk), then Opus prompts after two-sprint validation

---

*This guideline is a living document. Update after every retrospective that surfaces a process gap. Version history tracked in Confluence.*
