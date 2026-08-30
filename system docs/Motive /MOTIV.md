# MOTIV — why ZoNuLy exists, what we are trying to do, and how we will do it

> **Read this before anything else.** It is the problem statement, the motivation, the plan and
> the rules, in one place, so it never has to be re-explained. When the project's understanding
> changes, change this file and run `python scripts/run.py kg build`; the knowledge graph's
> `problem:` nodes are seeded from it.
>
> Written 2026-08-30 from Tejmul's own description. First person plural = Tejmul and his teammate.

---

## 1. Who we are and where we stand

We are fourth-year B.Tech (CS + AI) students at Newton School of Technology, class of 2027.
We have real, shipped engineering: LoRA/QLoRA fine-tuning deployed on RunPod, a PostgreSQL to
serverless migration that cut infra cost 95%, a founding-team AWS build, a RAG chatbot, a
freelance marketplace with 1,000+ community members. We are good at building products and AI
systems.

What we are **not** is competitive programmers. Normal DSA we can handle. Codeforces-level DSA we
cannot, and we are honest about that. Most large-company interviews ask for a good amount of DSA,
not Codeforces level, but the ones that gate on it are not where our odds are best.

We have no opinion about, and no dependence on, college placement. We are going to find our own
way in.

## 2. The economic insight this whole project is built on

An engineer sitting in an office in the US, UK or Germany costs the employer **₹1.5–2 crore a
year** all-in. The same company can hire an equally capable engineer working from India, or
relocated on a visa, for **₹20–50 lakh** and it is a rounding error to them. They are paying in
dollars, euros and pounds; our costs are in rupees.

That gap is the opportunity. It is not exploited by the household names, which are hyped,
oversubscribed and DSA-gated. It is exploited by **recently funded startups** (seed to Series B)
that have money, need a good software engineer who fits the role, and cannot find one fast enough.
They do not post on the big job boards; they post on their own careers page (an ATS) and wait.

So the target is:

| Target | Threshold | Why |
|---|---|---|
| **US / UK / Germany** companies, remote from India or on-site with a visa | any role that pays well in local terms (which is automatically ₹30 LPA+) | The currency gap. Remote-from-India is the realistic first path; relocation is the second. |
| **India, on-site** | **₹30 LPA and above** for a fresher | We will happily work on-site in India. 30–40 LPA is a big number here and they will expect a lot; still worth the interview. |
| **Not** Google / Microsoft / Amazon and the like | — | Hyped, DSA-gated, thousands of applicants per role. Not where our odds are. |

Every company gets a **confidence grade**: how well our resume matches the JD, and therefore how
likely we are to be shortlisted. **A low grade does not mean we skip it** — we still send the
resume and take our chances in the interview. The grade decides *ordering and effort*, not
whether we try.

## 3. The four problems, and why they are mechanical

1. **We never see most of the good jobs.** They live on ATS pages of companies nobody has heard
   of yet. By the time an aggregator shows them, hundreds have applied.
2. **We cannot tell which are worth our time.** "AI Engineer" spans eight years of ML to
   founding-engineer-for-a-strong-student. Only reading the JD against the resume tells you which.
3. **Cold applications go nowhere.** A portal submission is one of 800. A referral from an
   engineer, even a weak one, puts you in a stack of ten.
4. **Referrals do not scale by hand.** Find a person, work out their role and email, learn their
   work, write something that is not a template, send, follow up, track the reply, schedule the
   call — twenty minutes each, and we have coursework.

All four are search, filtering, drafting and follow-up: machine work. Our judgement matters at
exactly one moment — *"yes, send that email to that person"* — and that takes ten seconds if the
other nineteen minutes are done.

## 4. The process we want automated, step by step

```
 1  COMPANIES     scrape funded startups in US/UK/DE (+ India ≥30 LPA) from ATS boards, YC,
                  HN hiring, funding-round feeds  →  a registry that compounds every week
 2  JOBS + GRADE  pull every open role, score it against OUR resume  →  confidence 0–100,
                  reasons, gaps. High grade = high chance. Low grade = still send, lower priority.
 3  PEOPLE        for each company, 10–30 people who actually work there: name, role, email,
                  LinkedIn, GitHub, whatever is public
 4  ROLES         classify each person: SDE1/2/3, staff, engineering manager, DevOps, founder /
                  CTO, recruiter / HR. We target the ones who can refer: engineers, EMs, founders.
                  Recruiters last.
 5  RESEARCH      what has this person built, how senior are they, what do they care about —
                  enough to write one true sentence about them, never an invented one
 6  DRAFT         a cold email with the resume link, from a boilerplate personalised to their
                  name, role, work and our real overlap
 7  REVIEW        we read it, fix it, approve it  ← the only human step
 8  SEND          from our own Gmail, capped at 25/day, spaced, plain text
 9  REPLIES       poll, classify: yes / no / role gone / unclear. Expect ~5–10 replies per 100
                  sends, and a third of those to be "hiring is done"
10  FOLLOW UP     one polite follow-up after 5 silent days, never two
11  SCHEDULE      when someone says yes — sends a Meet link, schedules a screen, an assessment,
                  an interview — extract the time, put it on OUR calendar, notify us, and if two
                  companies land on the same slot, draft the reschedule email for us to approve
12  LEARN         the funnel with numbers: which roles, which framing, which company stage
                  actually answers — so the next month is better than this one
```

## 5. The funnel, with honest numbers

| | Per candidate, per month |
|---|---|
| Sends | 25/day × ~20 working days ≈ **500** |
| Replies (5–10%) | 25–50 |
| Of which "hiring done / not now" (~40%) | 10–20 |
| Positive: referral, call, assessment | **8–20** |
| Interviews reached | 3–8 |

Two of us run the same machine with two profiles, so the pipeline's ceiling is roughly double.
Volume is bounded by Gmail deliverability (25/day per account), not by how many people we can
find — which is why **who** we send to matters far more than how many we find.

## 6. The rules we do not break

- **Nothing sends without one of us reading it.** The review queue is the only path to send.
- **Nothing is invented.** No fake project, number, mutual connection or compliment. A generic
  honest email is recoverable; a flattering fabricated one is not.
- **No logged-in LinkedIn automation.** A banned LinkedIn kills the exact thing we are building —
  the ability to be referred. Public data only, through channels that never touch our session.
- **25 a day per Gmail account, irreversibly spent.** The cap protects the inbox interviews
  arrive in.
- **One follow-up. Never two.**
- **Both of us never write to the same person in the same month.** Two near-identical emails
  from two students at the same college a week apart reads as spam, and burns the company.
- **It has to be cheap.** We are students. Target: ₹0 recurring, with an optional ₹1,000–2,500
  a month if paid data (Apify people data) or a hosted writing model (OpenRouter) materially
  raises the quality of *who* we reach and *what* we send.
- **No local model, ever.** Ollama has wrecked this machine every time it was tried. Every model
  call goes through OpenRouter behind a cost ledger and a budget cap. Local SQLite, no daemons.
- **Nothing happens without permission — in the app and in building it.** Every action the
  system can take has a tier (read · free read · spend · write to the world · forbidden); spend
  and world-writes need a grant we gave, and anything without one asks and waits. The same
  applies to the person or model building it: a step is proposed, approved, built, verified,
  noted — one at a time. See `system docs/FINAL-PLAN-V3.md` §11 and §14.

## 7. What "done" looks like

We open the app once a day. Overnight it found jobs we had never heard of, with an honest grade
and a sentence explaining it; found real people at the good companies with their role labelled;
wrote the emails. We read the queue, fix the lines that do not sound like us, approve. That is
ten minutes. When someone replies "yes, here's a link, Thursday 4pm?", it is on our calendar with
a notification and, if needed, a reschedule draft waiting. After a month we can see, in numbers,
what works.

## 8. How to use this file

- **A new session (human or model):** read this, then `knowledge/BRIEF.md` for the live state,
  then `system docs/FINAL-PLAN-V3.md` for the build plan.
- **The problem changed:** edit this file, mirror the change in `knowledge/context.yaml`
  (`problem:` and the relevant `features:` / `gaps:`), run `kg build`.
- **Something was decided or built:** `python scripts/run.py kg note "..." --about <ids>`.
