# SPEC SHEET — Malaysia AI Takeoff + AI Document Inspector

- **Product:** Construction AI for Malaysian general contractors (GCs).
- **Features in scope:** (A) AI Quantity Takeoff Agent, (B) AI Document Inspector Agent (contracts / specs / codes).
- **Out of scope:** borehole digitiser, AI-generated estimates/pricing, site monitoring, scheduling.
- **Benchmarked against:** Civils.ai (civils.ai, Singapore, 2022, ~$1.3M raised, 200+ firms, 8 countries). This spec is written for an engineering AI model to implement from.
- **Current date:** 2026-08. Prices in MYR (RM); Civils.ai reference prices is SGD.

---

## 1. FEATURE A — AI Quantity Takeoff Agent

### 1.1 What it does

- Reads PDF construction drawings (scanned, handwritten, born-digital, multi-sheet).
- User types a plain-English scope prompt, e.g. `"measure all asphalt road surfacing and paving areas"` or `"all 4-inch waterline runs"`.
- Agent measures areas (m²), lengths (m), volumes (m³), counts (no.) per scope item, per drawing sheet.
- Returns: annotated PDF (markup on the original drawing) + Excel export, QA-reviewed by a human before delivery.

### 1.2 Inputs / Constraints

| Item | Spec |
|---|---|
| Accepted file types | PDF only (scanned, handwritten, old, multi-sheet). No preparation, no page splitting, no naming. |
| Not supported | CAD files (`.dwg`), Revit/BIM (user exports to PDF first). No structural calculations. |
| Prompt language | Plain English + Bahasa Melayu (bilingual).
| Unit system | Metric (m, m², m³, pcs). |
| Prompt mode | One-off prompt, or saved reusable workflow template shared across team.

### 1.3 Process (molecular level)

Pipeline = custom CV/geometry engine + OCR + vision-language model (VLM) + LLM + rules + human QA. NOT a general-purpose LLM calling ChatGPT on a PDF. Evidence in §5: general LLMs scored 18–20% of line items within ±5% on a controlled benchmark; Civils.ai scored 100%.

1. **Ingest / rasterise + vectorise**
   - PDF → cloud object storage (per-account isolation).
   - Page render to raster (~200 DPI) for visual/semantic reading (needed for scans).
   - Vector extraction from the PDF linework where born-digital: polylines, arcs, text blocks, closed regions, hatch/fill patterns. (Civils.ai description: "vectorised the plan and section sheets".)
2. **Auto-classify drawing sheets** — classify each sheet against a work-division taxonomy. Civils.ai uses CESMM4/CSI Divisions 31–33 (earthwork / exterior / utilities). Malaysia: map to JKR SOR divisions (civils, drainage, road works, utilities) — see §1.5.
3. **Semantic extraction** — OCR (print + handwritten), text labels, legends, schedules/tables, symbols. VLM assigns meaning: `legend item → measured class` (e.g. `asphalt`, `planting area`, `4" water pipe`, `manhole`).
4. **Geometry measurement engine** (the core algorithms):
   - **Areas:** closed polygon / region extraction (planar area). Apply scope rules from detail drawings: net vs gross planting area, single- vs both-side kerb (kerb run measured one side or two — resolved from detail sheets, not assumed).
   - **Lengths:** polyline network extraction (pipe/duct/cable runs); reconcile against schedules (pipe run in plan ↔ pipe schedule ↔ manhole schedule; the same item gets one reconciled quantity, not double-counted).
   - **Counts:** symbol/object detection (manholes, light fixtures, outlets, chambers) from plan + schedule.
   - **Volumes / earthworks:** reconstruct cut/fill surface from **contours and spot levels** (interpolate/TIN compute) then volume between surface and design level. This is the explicit root fix for the single biggest LLM error mode (bulk earthworks mis-estimation). Never assume uniform depth.
5. **Scale calibration** — detect/verify drawing scale from scale bars, title blocks, known dimensions. Civils.ai meter: standard takeoff ≤ 1:250; 1:250–1:500 counts as 2 takeoffs. User override: 2-point calibration (pick two points, enter real-world distance).
6. **Aggregation** — pixel → world units via scale; per-category totals; unit set per item type; consistent rounding; item naming per division; one row set per trade-sheet pair.
7. **Human QA gate (mandatory)** — engineer reviews every result (markup + numbers), fixes edge cases (messy annotations, legend ambiguity, scale anomalies), accepts or re-runs pipeline. Original AI output preserved in version history.
8. **Outputs** — annotated PDF + Excel; share as password-protected link with expiry; post-export user editing (move nodes, add/delete nodes, rename categories, multi-select edit, tags, undo, change scale).

### 1.4 Specs (targets)

| Metric | Target | Source |
|---|---|---|
| Accuracy (modern digital PDFs) | ≥97%; no line item outside ±3%; ≥45/45 items within ±5% in controlled test | Civils.ai |
| Accuracy (old/hand-drawn, pre-1975) | Degraded; not guaranteed. | Civils.ai |
| Latency | ≤24 h end-to-end (target); email notification on completion | Civils.ai |
| Metering | 1 takeoff = 1 trade × 1 drawing sheet (≤1:250). Multi-trade capped at 5 takeoffs/sheet. | Civils.ai |
| API / estimated cost per full takeoff | ~$3–4 for general-LLM attempts (barely useful); own engine + QA priced per takeoff | Civils.ai blog |
| Pricing tiers (Civils.ai SGD) | Starter ~SGD 90 / mo = 10 takeoffs, 1 seat, 2 GB, unlimited standard AI searches; Pro ~SGD 270 / mo = 30 takeoffs, 50 GB, learns your standards, priority support; Enterprise custom (unlimited seats, API/MCP, SSO/SAML, DPA). MYR localize approx. RM 300 / RM 900 (PPP estimate). | Civils.ai |
| Share | Password + expiry links; recipient needs no account | Civils.ai |
| Team repo | Save workflows to team account; run permissions; shared outputs | Civils.ai |

### 1.5 Malaysia deltas — market mechanics (watch this; it routes the product)

**Rule one: someone always has to count. The question is WHO.** In Malaysia the answer is decided by contract form:

| Form | Structure | Who measures | Measurement risk holder | Takeoff need |
|---|---|---|---|---|
| PWD 203 | Lump sum, drawings+specs are the contract | **Contractor** | Contractor. Clause 8(a): documents complementary — drawing/spec discrepancies can defeat variation claims. Under-measure = pure loss, un-bidable. | HIGH (critical path) |
| PWD 203A | BoQ is part of the contract | Client's consulting QS | Client (measured/valued form). Clause 8(b): BoQ contradicts drawings + S.O. instructs change = **variation entitlement**. S.O. values monthly; final account on measured executed work. | LOW at bid; HIGH post-award |
| PWD DB (design & build) | Contractor designs + builds | Contractor (+ its designers) | Contractor | HIGH |
| PAM 2006/2018 (private buildings) | Lump sum, one contract sum | Client QS supplies BoQ, but quantities are the contractor's agreed risk | Contractor | HIGH |
| FIDIC-based (MRT/ECRL/highways/GLCs) | D&B or BoQ hybrid | Per contract | Usually contractor | HIGH |

**The three places where the contractor counts its own money (the actual demand):**
1. **Count-it-yourself tenders** (203 / PAM / DB / FIDIC): the drawing arrives with no list. The machine's measured quantities ARE the bid. 1% under-measure on a RM 100M lump sum = RM 1M of the contractor's ~5% margin.
2. **Sub-procurement — the quiet 60–70% of every ringgit:** the GC hires 10–15 specialist teams (electricians, plumbers, painters, diggers). Whose quotes you get depends on how fast you hand each one its own measured quantities: packages out in days with the machine → 3–5 quotes each (competition drops prices); packages take weeks by hand → 2 quotes, stale pricing. The subs always contest the numbers ("your quantities wrong") — a measured answer ends the argument. Savings from merely competitive sub pricing: RM 450–650k on a RM 50M project (1.5–2% × 60–70% of value).
3. **Post-award remeasure — the monthly and final account:** the client pays a little every month (interim valuations); every change order is a recount; the final account is a full recount. Money owed is never auto-paid — it must be measured, cited and proved (JTC reference: 2,842 prompts, 5–15 min saved each, 528+ h/yr across 38 users, cross-checking schedules of rates against variation orders). The machine is the "check the friends' math" argument against the client's counters, and against over-claiming subs.

**Dual role (same robot, two jobs):** where the client already counted (203A), the takeoff engine's job is not counting — it's checking the client's list (BoQ omission audit → §Feature B). Where the contractor counts, it acts as the measuring engine. Product consequence: the engine must output at **per-trade AND per-phase granularity** (sub-package cross-sections from whole-project BoQs + drawings), not just whole-sheet totals.

**Other deltas:**
- Drawings: metric, 1:100/1:200/1:250/1:500, JKR-division legends, frequently bilingual BM/EN labels — OCR + legend mapping must handle code-switched text.
- Exports: Excel/CSV aligned to JKR SOR + CSI-style divisions; item names in BM/EN.
- Buyer math (ROI): loaded QS cost RM 100–150/h. One tender takeoff = 5–15 person-days = RM 15–30k; 50–90% cut = RM 8–27k/tender; 12–24 tenders/yr = RM 100–650k/yr. Extra bids (+2–4) ≈ +1 win ≈ RM 0.5–3.0M gross margin.
- Data residency: store in ap-southeast-1; PDPA 2010 compliance.

---

## 2. FEATURE B — AI Document Inspector Agent (contracts / specs / codes)

### 2.1 What it does

- Grounded Q&A + checklist execution across the project document corpus.
- Every answer returns a **citation** (page + clause/section) with one-tap click-through. Nothing fabricated, nothing uncited.
- Reusable workflows: build a question/risk checklist once, re-run on every new tender pack.
- Malaysia rule-packs (§2.4): deterministic checks over keyword + structure, not LLM "opinion".

### 2.2 Inputs / Constraints

| Item | Spec |
|---|---|
| Corpus | Contracts (PWD 203, PWD 203A, PWD DB, PAM 2006/2018, FIDIC), employer's requirements, specs (JKR), codes of practice, drawings, schedules. PDF/scanned/born-digital. |
| Language | Bilingual BM/EN detection; answers in the user's language |
| Scale | Full 600-page document sets OK; no page splitting |
| Access | Web app; also usable from phone on site |

### 2.3 Process (molecular level)

1. **Ingest + chunk** — per page / clause / schedule / table. Preserve structure: clause numbers, schedules, figures, amendments/errata (superseded text marked). Bilingual: BM/EN segments must not be split mid-clause.
2. **Hybrid index** —
   - Vector embeddings (semantic retrieval) + keyword/BM25 (exact terms: clause refs, `10% retention`, RM amounts, dates) + structured extraction for schedules/tables (rates, dates, numbers as typed fields).
   - Citation anchor = page + clause + line; every chunk keeps source coordinates.
3. **Query execution** — single NL question OR workflow template (list of questions run in batch). Retrieval → grounded answer generation (RAG), citation mandatory; if no evidence in corpus → answer `not found in corpus` (never invent).
4. **Agent behaviours:**
   - Risk review: extract clauses + exclusions + obligations → risk list with citations + plain-English summary (BM/EN).
   - Deliverables/timelines: extract submission dates, review periods, approvals → checklist with dates.
   - Compliance: run rule-pack checks (§2.4) → PASS / flag / void, each with line citation.
   - Subcontract v client spec: cross-check scope/inclusions/compliance → gap list + conflict flag + decision-matrix score per subcontractor.
   - BoQ omission audit (wires to Feature A): drawings vs client BoQ → items in drawings missing from the BoQ → `VO/clause 8(b)` claim-readiness list.
5. **Deterministic rules where possible** — Malaysia rule-packs below are encoded as code + regex + structure, LLM only for semantic extraction. LLM-based floating facts are prohibited from output without citation.
6. **Human review** — outputs are drafting support for qualified personnel; sign-off by the engineer/QS per procurement rules.

### 2.4 Malaysia rule-pack (initial)

| Rule | Check | Nail it to |
|---|---|---|
| CIPAA compliance | Retention > 10% → flag (void under CIPAA 2012); payment-term clauses that abridge adjudication rights → flag with citation | CIPAA 2012 |
| LAD / EOT | LAD rate, cap; EOT notice window in **calendar days** and to whom; missed-window = dead EOT -> show the exact clause | PWD 203A / PAM |
| Authority-approval delay | TNB / water supply / authority (IMB) approval delays: does contract treat as EOT cause? Which clause? | contract |
| Site-conditions / soil | "deemed to have inspected" / soil-conditions disclaimer clauses → surface with citation (critical for earthworks lump-sum) | contract |
| Compliance & registration | Bumiputera participation requirements, CIDB grade (G1–G7) + levy, insurance/bond requirements | tender doc |
| Payment mechanics | Payment timeline, retention, bond 2.5–5%, escrow/MOF requirements | contract |
| Escalation / SST | Price fluctuation clauses, SST treatment | contract |
| SOR-vs-VO rate audit | Subcontractor VO rates vs contract Schedule of Rates → over-/under-flagged | SOR + VO |

### 2.5 Specs

| Metric | Target | Source |
|---|---|---|
| Citation | Mandatory on every answer; page + clause; one-tap open | Civils.ai |
| Search volume | "Unlimited" standard in-app searches under fair use (1 person = 1 account); multi-step agent workflows custom-priced | Civils.ai |
| Latency | Minutes per query (online); batch workflows asynchronously + notify | Civils.ai |
| Accuracy posture | Grounded answers only; ungrounded = explicit `not found` | Civils.ai |
| Pricing | Bundled in all plans (no separate tier); Enterprise: API + MCP, SSO/SAML, custom DPA | Civils.ai |
| Evidence trail | Every answer clickable to source; audit log for procurement/bid file | Civils.ai |

### 2.6 Malaysia deltas

- Corpus: JKR Form 203/203A/DB, PAM 2006/2018, FIDIC, JKR Standard Specs, Malaysian codes. Bilingual BM/EN.
- The headliner matches the buyer: post-award cash position — "verify the S.O.'s monthly valuation, catch the VO before the SOR is re-priced, build the claim file" (JTC reference case: 2,842 prompts, 5–15 min saved each, 528+ h/yr at 38 users).
- Sell order: takeoff opens the door; inspector keeps the account (prevents loss, ROI less measurable — never lead with it).

---

## 3. Shared platform specs

| Item | Spec |
|---|---|
| Data | TLS in transit, encryption at rest, per-account isolation, delete anytime (UI + via request), client owns all IP; never used to train models; no third-party sharing. |
| Deployment | Web app (no install), server ap-southeast-1 (MY latency + PDPA); enterprise: SSO/SAML, DPA, security review. |
| Integrations | API + MCP (Enterprise); Autodesk Construction Cloud ingest. |
| Ops | Email notification on completion; 24 h internal SLA; ship cadence every 2 weeks; human review staff scales per takeoff volume (the unit-economics constraint). |

## 4. KPIs to instrument

- Accuracy vs ground-truth QS quantities on own benchmark (per division) — target ≥97% ±3%.
- QA rework rate (results sent back or corrected) — must stay < ~10% or unit economics break.
- p95 latency per takeoff; per-borehole N/A.
- Prompt success rate (user prompt → accepted output, no re-run).
- Takeoff throughput per seat/month; sub-procurement time (tender → sub packages out) as the customer-facing metric.

## 5. Evidence & sources (vendor claims; directional)

- Civils.ai blind benchmark (vendor-authored, one UK civils scheme, 2025-26): Civils.ai 45/45 line items within ±5% (bid within 3% of chartered-QS ground truth); Claude Sonnet 4.5: 9/45 items ±5% (39% underestimate); GPT-4-class ChatGPT: 8/45 (43% underestimate). Largest single miss: bulk earthworks ~£230k. Error taxonomy root causes: geometry-derived quantities (m³/m²), cross-sheet aggregation (lm), scope-boundary resolution — all fixed by the geometry + reconciliation + rules engine above.
- Borehole/AGS and other details: out of scope (see "Out of scope").
- Sources: civils.ai (home, pricing, about, takeoffs page, specs & checks page, compare, blog: "Can LLMs perform good civil estimates?", "How to build no-code AI workflows", "AutoCAD Data Extraction API", "What's new — June 2026"), RightAIChoice (95/100), PitchBook/Tracxn (funding ~$1.3M).

## 6. Open questions for the implementer

1. Model names: Civils.ai does not publish its model stack. Own pipeline should be treated as: CV geometry engine (polygon/polyline/region ops) + OCR/vision-language model (semantics) + LLM (prompt parsing, reconciliation), with deterministic rules where possible.
2. Malaysian benchmark corpus: need real JKR drawing sets + ground-truth BoQs to validate ≥97% on Malaysian drawings (bilingual legends, local scales).
3. Human QA cost is the dominant unit cost; validate that reviewer throughput supports the takeoff metering economics.
