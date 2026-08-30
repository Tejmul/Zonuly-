# JobHunter — Tools, Services & Relationship Sourcing

> Companion to `JOBHUNTER-ARCHITECTURE.md`. This is the *what do I actually sign up for* doc.
> Local only. Prices are indicative — **verify current pricing before buying anything.**

---

## 0. The short answer

If I only pick what I'll actually use in month one:

| Need | Pick | Cost |
|---|---|---|
| Job discovery | **Greenhouse + Lever + Ashby public APIs** | Free |
| Company list | **YC directory + HN Who's Hiring (Algolia API)** | Free |
| Finding humans | **GitHub API** (commits, org members, contributors) | Free |
| Page reading | **Jina Reader** (`r.jina.ai`) → Playwright fallback | Free / free |
| Email finding | **Hunter.io** free tier → **Findymail** when it matters | Free → ~$50/mo |
| Email verification | **MillionVerifier** (pay-as-you-go credits) | ~$30 one-off |
| Cheap bulk LLM | **Ollama** + Qwen2.5-14B or Llama-3.1-8B | Free (local) |
| Embeddings | **Ollama** + `nomic-embed-text`, stored in `sqlite-vec` | Free (local) |
| Draft writing | **Claude Haiku** (bulk) / **Sonnet** (final drafts) | ~$5–15/mo |
| Sending + replies | **Gmail API** (OAuth, own account) | Free |
| App | Next.js + Drizzle + SQLite + Zod | Free |
| Tests | Vitest + MSW | Free |

**Realistic month one: ₹3,000–6,000 (~$35–70).** Almost all of it is email finding and
verification. Everything else is free or local.

---

## 1. Job discovery

### Tier 1 — ATS public APIs (the whole game)

Startups don't build careers pages; they embed an ATS. Those ATSs serve public JSON to the
company's own site, so reading them is just reading a public endpoint.

| ATS | Endpoint shape | Auth | Notes |
|---|---|---|---|
| **Greenhouse** | `boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true` | none | Biggest coverage. Start here |
| **Lever** | `api.lever.co/v0/postings/{slug}?mode=json` | none | Second-biggest |
| **Ashby** | public job-board API by org slug | none | Very common in newer/AI startups |
| **Workable** | public board endpoint | none | Long tail |
| **Recruitee** | `{slug}.recruitee.com/api/offers/` | none | Long tail |
| **SmartRecruiters** | public postings API | none | More enterprise |

**Bootstrapping:** these are keyed by company slug, so you need a company list first, then
probe each company against each ATS. Cache the hit in `companies.ats_provider` — you only pay
discovery once, and the registry compounds every week.

### Tier 2 — aggregators & threads

| Source | How | Notes |
|---|---|---|
| **HN "Who is Hiring"** | HN Algolia API — `hn.algolia.com/api/v1/search?tags=comment,story_{id}` | Free-text; needs LLM parsing. Very high signal, monthly |
| **YC company directory** | Public list → map to ATS boards | Best route to funded-but-unknown |
| **RemoteOK / WeWorkRemotely** | RSS / JSON feeds | Remote-eligible only |
| **Hiring.cafe / a16z & Sequoia portfolio job boards** | Portfolio-wide boards | Good company-list seeds |

### Tier 3 — India-specific ⚠️

**Wellfound, Instahyre, Cutshort, Naukri.** Real coverage for the ₹24–60 LPA band, but **none
has a clean public API**. Check ToS before automating anything; several explicitly forbid it.

**Recommendation: use these manually.** Browse them yourself, paste interesting company names
into the registry, let the pipeline pick up their ATS board. You get the coverage without the
ToS problem — and it costs you five minutes a week.

---

## 2. Company intelligence (for scoring + targeting)

| Need | Tool | Cost |
|---|---|---|
| Funding stage / size | **YC directory**, Crunchbase free tier, company About page | Free |
| Tech stack | job description itself + their GitHub org | Free |
| Is this a real company | domain age, careers page, GitHub activity | Free |
| Engineering culture | their engineering blog, OSS activity | Free |

Skip paid company-data platforms for now. The job description plus a GitHub org tells you
almost everything that matters for *this* decision.

---

## 3. 🔑 Finding the relationships — the highest-leverage part

This is what you asked to go deeper on, and it's where the whole strategy lives or dies.
A cold email to a random engineer converts poorly. A cold email to someone with a **real
connection** to you converts far better. So the goal isn't "find an email" — it's
**find the warmest available path, and rank by warmth.**

### 3.1 The warmth ladder

Rank every contact. Spend the 25 daily sends top-down.

| Tier | Signal | Why it converts | How to find |
|---|---|---|---|
| **1 · Alumni** | Same college | Strongest single signal for a student. People genuinely help juniors from their own college | LinkedIn alumni filter (**manually** — see §3.4), college alumni portal, Discord/WhatsApp batch groups |
| **2 · Shared OSS** | They maintain / contributed to something you've used or contributed to | Real shared context. You can say something true and specific | GitHub: your starred repos → contributors |
| **3 · Same city** | Bengaluru / Hyderabad / Pune etc. | Enables "happy to buy you a coffee" — much easier yes | GitHub profile location, team page |
| **4 · Same stack / domain** | They work on what you build | Gives you an honest hook | Their repos, their blog |
| **5 · Content** | They wrote a post / gave a talk you actually read | Specific, verifiable, flattering without lying | Their blog, YouTube, conference sites |
| **6 · Cold, right team** | Right company, right team, no link | Baseline. Still worth it — but last | GitHub org members |
| **7 · Recruiter / HR** | — | Lowest. They're already drowning | Team page |

Store this: `contacts.warmth_tier` + `contacts.warmth_evidence` (the actual fact — you'll use
it in the draft). **Sort the review queue by warmth, not by job score.**

> The single biggest upgrade over your original spec: it didn't have a warmth model. Adding one
> costs a column and a scoring function, and it's probably worth more than any other single
> feature.

### 3.2 GitHub — your best free relationship graph

GitHub is the only large, public, machine-readable professional graph that's free and allows
automation. Use it hard.

| API | What it gives | Endpoint |
|---|---|---|
| Org members | Public members of a company org | `/orgs/{org}/members` |
| Repo contributors | Who actually writes the code | `/repos/{o}/{r}/contributors` |
| **Commits** | **`commit.author.email`** — real addresses | `/repos/{o}/{r}/commits` |
| User profile | name, bio, location, blog, sometimes email | `/users/{login}` |
| Repo stargazers | People interested in the same things | `/repos/{o}/{r}/stargazers` |
| Search users | `location:Bengaluru language:Go` | `/search/users` |

**Auth:** a personal access token gives 5,000 req/hr. Plenty. Free.

**Finding a company's GitHub org:** try the domain name, check the website footer, or search
GitHub for the company name. Store as `companies.github_org`.

⚠️ **The `noreply` problem.** GitHub defaults to `{id}+{user}@users.noreply.github.com`, and
squash-merges hide the original author. Expect a meaningful fraction of commits to be useless.
**Measure this in week 1** — it drives everything downstream.

**Trick that materially improves the hit rate:** older commits (pre-2020) and commits to a
person's *own* repos (rather than the company org) leak real addresses far more often, because
the privacy default came later and personal projects are configured more casually.

### 3.3 Reading team / about pages

Many startups list their team publicly with names and roles.

| Tool | Use | Cost |
|---|---|---|
| **Jina Reader** — `https://r.jina.ai/{url}` | URL → clean markdown, one GET, no setup | Free tier |
| **Firecrawl** | Managed crawl + structured extract | Free tier, then paid |
| **Playwright** | JS-heavy pages, full control | Free (you already know it from the portal) |
| **Cheerio** | Static HTML parse | Free |

**Order:** Jina Reader → Playwright if it fails. Don't reach for the heavy tool first.

### 3.4 LinkedIn — manual only, and this is deliberate

**Do not automate LinkedIn. Not scraping, not connecting, not messaging.**

Your own spec already says this, and after reading the MVRX portal I'd underline it: they use
Apify actors explicitly labelled `no-cookies` so that **no LinkedIn account is ever logged in**
— nothing can be banned. That's the safe pattern, and it only works for public post data.

For your case the calculation is even more one-sided. A banned LinkedIn destroys the exact
asset you're building: the ability to *be referred*. The strategy dies with the account.

**So use LinkedIn the way it's meant to be used — by hand, 10 min/week:**
- Alumni filter: your college → "where they work" → target companies. **This is your tier-1
  goldmine.** Nothing else gives you this.
- Copy names into a CSV, drop it in `data/manual-contacts.csv`, let the pipeline resolve emails
  and draft from there.

Manual name entry + automated email resolution + automated drafting = the value with none of
the account risk. The human step is 10 minutes and it's the highest-yield 10 minutes in the
system.

### 3.5 Other relationship sources worth wiring

| Source | Signal | Automatable |
|---|---|---|
| **Alumni portal / batch WhatsApp groups** | Tier 1 | Manual |
| **Conference speaker lists** (PyCon India, Rootconf, FOSSAsia) | Tier 5, often with contact info | Semi |
| **Discord / Slack communities** you're in | Genuine warm intros | Manual |
| **Twitter/X** | Devs post openly; some list emails | API is paid now — skip |
| **Personal blogs** | Often have a contact page | Yes |
| **`git log` on repos you've cloned** | You already have this data locally | Yes — free win |

---

## 4. Email finding — the waterfall

Never call the expensive one first. Cascade, stop at the first hit, cache everything.

```
[1] GitHub commit email          free   ~20-40% hit
      ↓ miss
[2] GitHub profile email         free   ~10%
      ↓ miss
[3] Team/about page              free   ~15%
      ↓ miss
[4] Pattern inference            free   high coverage, "guessed" only
      ↓ low confidence
[5] Paid finder API              paid   ~50-70% on the remainder
      ↓
[6] Verification                 paid   before anything labelled "guessed" is sent
```

### Paid finders

| Tool | Model | Notes |
|---|---|---|
| **Hunter.io** | ~25–50 free/mo, then ~$34+/mo | Great **domain pattern** endpoint — often all you need |
| **Findymail** | ~$49/mo | Strong accuracy, built for cold outreach |
| **Prospeo** | credit-based | Good value |
| **Anymailfinder** | pay per *verified* result | Nice model — you don't pay for misses |
| **Apollo.io** | free tier w/ credits | Huge DB but data quality varies; ToS on export is strict — read it |
| **Clay** | ~$149+/mo | *Orchestrates* many providers in a waterfall. Excellent — and exactly what you're building yourself. **Skip it; building it is the point** |
| **People Data Labs** | API, per-record | Enterprise-priced. Overkill |

**My pick:** Hunter free tier for domain patterns → **Anymailfinder or Findymail** for the
remainder once you've proven the pipeline works. Don't subscribe in week 1.

### Pattern inference (free, and better than it sounds)

With 3+ verified addresses on a domain, infer the pattern:

```
first.last@   first@   flast@   f.last@   firstl@
```

Hunter's domain-search endpoint often just *tells you the pattern* — one call, then apply it
locally to every contact at that company. High leverage per API call.

Always store as `confidence: 'guessed'`. Always verify before spending a send.

### Verification

| Tool | Model | Notes |
|---|---|---|
| **MillionVerifier** | ~$30 for 10k credits, no subscription | Best value; my pick |
| **ZeroBounce / NeverBounce** | per-credit | More expensive, well-known |
| **Bouncer** | per-credit | Good API |
| DIY MX + SMTP probe | free | ⚠️ Unreliable, and probing can get your IP blocked. **Don't** |

A bounce costs you one of 25 *and* dings sender reputation. At ~₹0.25 per verification this is
the cheapest insurance in the whole system.

---

## 5. LLM stack

### Local (Ollama) — bulk work

```bash
ollama pull qwen2.5:14b            # scoring — best quality/size on a laptop
ollama pull llama3.1:8b            # faster fallback
ollama pull nomic-embed-text       # embeddings
```

| Task | Model | Why |
|---|---|---|
| Cheap semantic filter | `nomic-embed-text` | Thousands/day, must be free |
| Deep scoring rubric | `qwen2.5:14b` | Structured output, hundreds/day |
| HN thread parsing | `llama3.1:8b` | Simple extraction |

Needs ~16GB RAM for the 14B. If you're on 8GB, use `llama3.1:8b` and accept slightly noisier
scores. **LM Studio** is a friendlier GUI alternative to Ollama if you prefer.

### Hosted (Claude) — where quality is the product

| Task | Model | Volume | Why hosted |
|---|---|---|---|
| **Draft writing** | **Sonnet** | ~60/day | This is the product. Local 8B prose is noticeably stiff |
| Reply classification | **Haiku** | ~10/day | Cheap, structured |
| Warmth-evidence summarising | **Haiku** | ~60/day | Cheap |

Rough order of magnitude: **$5–15/month** at this volume. Track it in `api_costs` from the
first call — that's the portal's missing-column lesson.

**Structured output:** define Zod schemas, validate every response, retry on mismatch. Never
regex an LLM response.

### Vector storage

| Option | Notes |
|---|---|
| **sqlite-vec** | Extension for SQLite. Same file as everything else. **My pick** |
| **libsql / Turso** | SQLite fork with native vectors, if you ever want sync |
| Chroma / Qdrant | Separate service. Unnecessary at this scale |

At a few thousand postings you could honestly do cosine similarity in plain JS. Don't
over-engineer this.

---

## 6. Sending & inbox

| Need | Tool | Notes |
|---|---|---|
| Send | **Gmail API** (OAuth2, your own account) | Needed for threading + reply reads. Not SMTP |
| Read replies | Gmail API `users.history.list` | Poll every 30 min |
| Threading | `In-Reply-To` + `References` headers | Follow-ups must thread, not start new |
| Auth | `googleapis` npm (you've seen it in the portal) | Free |

**Explicitly not using:** Resend / SendGrid / Mailgun. Transactional ESPs are for bulk mail
from a domain. You want mail that comes from **your actual personal Gmail**, because that's
what makes it a real person writing — which is the entire premise.

⚠️ Gmail API send scope needs OAuth verification for published apps, but **for your own account
in testing mode it just works.** Keep it in testing mode with yourself as the only user.

---

## 7. App stack

| Layer | Choice | Why |
|---|---|---|
| Framework | **Next.js (App Router)** | You now know it from the portal |
| DB | **SQLite** + `better-sqlite3` (or libsql) | Single user, single file, copyable |
| ORM | **Drizzle** | Same as portal — knowledge transfers directly |
| Validation | **Zod** | API boundaries + all LLM structured output |
| Scheduling | **node-cron** in the worker | Daily trigger |
| Queue | SQLite table + polling loop | ~150 lines, fully debuggable |
| **Tests** | **Vitest** + **MSW** | MSW mocks the external APIs so tests run offline |
| HTTP | native `fetch` | No Axios needed |
| Logging | **pino** | Structured. Makes an overnight failure diagnosable |
| Lint | ESLint + Prettier + `lint-architecture.sh` | Copy the portal's, it's good |

**MSW matters more than it looks.** Record real Greenhouse/GitHub responses once as fixtures,
then every test runs offline, instantly, deterministically. It's the single thing that makes
"tests from day one" actually sustainable — and it's what the portal is missing.

---

## 8. Cost budget

### Month 1 (proving it works)
| Item | Cost |
|---|---|
| Job APIs, GitHub, Jina, Gmail | ₹0 |
| Ollama (local) | ₹0 |
| Claude API | ~₹800 |
| MillionVerifier (10k credits, one-off) | ~₹2,500 |
| Hunter.io free tier | ₹0 |
| **Total** | **~₹3,300** |

### Month 2+ (running properly)
| Item | Cost |
|---|---|
| Claude API | ~₹1,000/mo |
| Email finder (Findymail / Anymailfinder) | ~₹4,000/mo |
| Verification credits | amortised |
| **Total** | **~₹5,000/mo** |

**Put a hard ceiling in config** and have the worker refuse to start LLM stages past it.
`api_costs` makes this enforceable rather than aspirational.

---

## 9. Build order — free first, paid only once proven

**Week 1 — all free**
Greenhouse + Lever + GitHub + Jina + Ollama.
👉 **First thing: the GitHub email hit-rate spike.** 20 target companies, measure it.
Everything downstream depends on that number.

**Week 2 — all free**
Embeddings filter + local scoring + fixture calibration set.

**Week 3 — first spend**
Claude for drafts (~₹800). Hunter free tier for domain patterns.
Add paid finders **only** once you've confirmed drafts are worth sending.

**Week 4 — verification**
MillionVerifier credits before the first real send. Never send an unverified `guessed`.

Rule: **don't buy anything until the free version has proven the stage works.** The portal's
crons got disabled because scraping costs ran ahead of value — same failure mode, avoid it.

---

## 10. Deliberately not using

| Tool | Why not |
|---|---|
| **Any LinkedIn automation** (Phantombuster, Dripify, Waalaxy, browser extensions) | Bans the account you need to receive referrals. Non-negotiable |
| **Clay** | Does the waterfall for you — but building it is the point, and ₹12k/mo |
| Apollo bulk export | ToS on export is strict. Read it before relying on it |
| Instantly / Lemlist / Smartlead | Cold-email platforms for domain-based bulk sending. You want personal Gmail |
| Trigger.dev | Cloud-hosted; can't reach local Ollama or local SQLite |
| Postgres | Unnecessary for one user on one machine |
| Twitter/X API | Paid, poor value here |
| Puppeteer | Playwright does the same, better |

---

## 11. Where this differs from the original spec

Three additions worth being explicit about:

1. **Warmth tiers on contacts.** The spec found people and wrote to them. Adding a warmth
   ranking — alumni first, cold last — is probably the highest-value change in this doc, and
   it costs one column plus a scoring function.
2. **Manual LinkedIn alumni sourcing as a first-class input.** Not automated, not skipped —
   a deliberate 10-min/week human step that feeds the automated pipeline. It's your best
   source and the only safe way to use it.
3. **Hosted model for drafts, local for everything else.** A conscious deviation from
   "nothing leaves the laptop." Scoring, resume and the job corpus stay local; only the draft
   stage (your background + their public bio) goes out. Worth naming as a choice.
