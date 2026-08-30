# JobHunter — the idea

## The problem, stated plainly

Job hunting for a high-paying engineering role is not one problem. It is four, and
they fail at different points.

1. **You never see most of the good jobs.** The roles that pay ₹24–60+ LPA are
   disproportionately at funded startups nobody has heard of yet. Those companies
   don't buy job-board ads. They post to their own careers page and wait. By the
   time a role shows up on a big aggregator, hundreds of people have applied.

2. **You can't tell which ones are worth your time.** A listing that says
   "AI Engineer" might want eight years of production ML, or might be a founding
   engineer role that would take a strong final-year student. You can't know
   without reading the whole posting, and there are thousands of them.

3. **Cold applications go nowhere.** Submitting through a portal puts you in a
   stack of 800. A referral — even a weak one from an engineer who barely knows
   you — moves you to a different, much shorter stack.

4. **Referrals don't scale by hand.** Finding a real person at a company, working
   out their email, learning enough about their work to write something that isn't
   obviously a template, sending it, and remembering to follow up — that's twenty
   minutes per person. Twenty people is a full day. And you have coursework.

Every one of those four is mechanical. None of them is where your actual judgement
matters. Your judgement matters when you decide *"yes, send that email to that
person"* — and that decision takes ten seconds if someone has done the other
nineteen minutes for you.

## What this is

**JobHunter is a pipeline that does the nineteen minutes and hands you the ten
seconds.**

It runs entirely on your own laptop. Every day it goes out, finds jobs you'd never
have found, reads each one against your actual resume, tells you honestly how
likely you are to get a first-round screen, works out who at those companies you
could realistically ask for a referral, finds their real email addresses, writes a
personalised ask for each one — and then stops, and waits for you.

Nothing is sent without you reading it and pressing approve.

## How it thinks

The pipeline is a funnel that gets narrower and more expensive at each step,
deliberately.

**Cast wide, cheaply.** Start from thousands of postings a day, pulled straight
from the source: the job-board APIs that startups' own careers pages run on, the
monthly Hacker News hiring thread, remote-work feeds, and the YC directory. These
are the places where a well-funded 40-person company posts a role before anyone
aggregates it. This step costs nothing but bandwidth, so it's greedy.

**Cut hard, cheaply.** Most of what comes back isn't for you — wrong discipline,
wrong seniority, wrong continent. Cheap rules and a fast semantic comparison
against your resume throw out the obvious no's before anything expensive touches
them. Thousands become hundreds.

**Judge slowly, carefully.** Only the survivors get read properly by a language
model running locally on your machine, which scores each one against a rubric:
how much of the required stack you actually have, whether the years they're asking
for are a real barrier, whether the posting welcomes early-career engineers, how
close their domain is to what you've shipped. It produces a number — your estimated
odds of getting a first screen — plus the reasons, plus the gaps.

The number is calibrated to be **honest, not encouraging.** A Staff role at a big
company scores low even if you know every technology in the listing, because you
would not get that screen. A founding-engineer role at a Series A startup scores
high even if the stack overlap is imperfect, because they hire for trajectory.
The point of the score is to stop you wasting a week on the wrong ten applications.

**Find the humans.** For the companies that score well, the pipeline goes looking
for people you could ask. The best free source turns out to be public code: when
engineers push commits to their company's open-source repositories, their real
work email is attached to those commits, in public, permanently. That's not a
loophole — it's how git works, and it's how open-source maintainers expect to be
contacted. Failing that, it reads the company's own team and careers pages, and
where it has enough examples it learns the company's email pattern and applies it.

Every contact carries a **confidence label**, and this matters more than it
sounds. "Verified" means the address came from a real commit or a public profile.
"Guessed" means it was constructed from a pattern and looks plausible but nothing
confirmed it. You see which is which, so you spend your limited daily sends on the
addresses that will actually arrive.

**Write something true.** For each person, the drafter reads what they've actually
built — their repositories, their bio — alongside your real background, and writes
a short email that connects one to the other. The rule it works under is strict:
never invent a project, a number, or a shared connection. If there isn't enough
public material to say anything specific, it says something generic rather than
something false. A generic honest email is recoverable. A flattering fabricated
one is not, and the person will notice.

**Stop.** The draft goes into a review queue. You read it. You edit it. You approve
or reject it. This is the only place a human is required, and it's the only place a
human adds anything.

**Send carefully, then remember.** Approved mail goes out from your own Gmail, hard-
capped at 25 a day, spaced out, plain text, inside working hours. Not because those
are arbitrary limits, but because a personal Gmail account that sends 200 lookalike
messages in an hour gets flagged as spam — and if that happens, the account you
need for the actual interviews is compromised. The cap protects the thing you're
trying to use.

After that it watches. Replies get pulled in and sorted into *they said yes*,
*they said no*, *the role's gone*, and *unclear, read it yourself*. If a thread
goes quiet for five days, exactly one polite follow-up is drafted — and it lands
in the same review queue as everything else. One follow-up. Never two.

## The one constraint everything is built around

**25 emails a day.** That's the real ceiling, and it's why the whole thing is
shaped the way it is.

If you could send unlimited mail, none of this would need to be careful — you'd
spray and pray. Because you can only send 25, and each one is irreversible, every
upstream decision becomes about *spending those 25 well*. That's why the scoring is
pessimistic rather than flattering. That's why contacts are ranked by whether the
address is real. That's why nothing sends without you looking at it.

The interface reflects this: the remaining daily budget is visible on every screen,
depleting.

## What it explicitly does not do

- **It doesn't automate LinkedIn.** Logged-in LinkedIn automation gets accounts
  banned, and a banned LinkedIn destroys the exact thing this is trying to build:
  your ability to be referred by people. The whole strategy dies with the account.
- **It doesn't apply for you.** Applications are cheap and worthless in bulk; the
  referral is the leverage. It finds and prepares, you decide.
- **It doesn't send anything on its own.** Ever. Every outbound message passes
  through a human.
- **It doesn't lie on your behalf.** No invented experience, no fake enthusiasm,
  no manufactured common ground.
- **It doesn't send your data anywhere.** The model runs on your laptop. Your
  resume, your targets, and your drafts don't leave it.

## What you actually do with it

You open it once a day.

You look at what came in overnight — jobs you hadn't heard of, with an honest
number next to each and a sentence explaining the number. You pick the ones you
believe in. You read the drafts waiting for you, fix the lines that don't sound
like you, and approve the ones that do. That's ten minutes.

The rest of the day, you build things and study, which is what actually makes the
referrals work.

Over a few weeks the useful thing isn't any single email. It's that you have a
funnel with numbers in it: how many companies you reached, who answered, what kind
of role answers most, which framing gets replies. Job hunting stops being a series
of hopeful one-off gestures and becomes something you can look at and adjust.

## The one-line version

> Job hunting is mostly search, filtering, and follow-up, which are machine work,
> plus judgement and voice, which are not. JobHunter does the machine work
> exhaustively and stops dead at the point where you're needed.
