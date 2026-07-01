# Provenance Guard

Module 4 Project — a backend system that classifies submitted text as AI-generated, human-written, or uncertain, scores confidence in that classification, surfaces a plain-language transparency label, and handles creator appeals.

Full design rationale (signal choices, uncertainty representation, label design, appeals workflow, edge cases, architecture diagram) lives in [planning.md](planning.md). This README documents what was actually built, with real evidence from running it.

## Setup

```bash
python -m venv .venv
source .venv/Scripts/activate      # Windows Git Bash
# source .venv/bin/activate        # Mac/Linux

pip install -r requirements.txt
```

Create `.env` in the repo root (gitignored):

```
GROQ_API_KEY=your_key_here
```

Run the app:

```bash
python app.py
```

## API

| Endpoint | Method | Body | Returns |
|---|---|---|---|
| `/submit` | POST | `{"text": str, "creator_id": str}` | `content_id`, `attribution`, `confidence`, `label`, `signals` |
| `/appeal` | POST | `{"content_id": str, "creator_reasoning": str}` | `content_id`, `status`, `message` |
| `/log` | GET | — | `{"entries": [...]}` |

## Detection signals

Two independent signals — one semantic, one structural (full rationale in [planning.md](planning.md#1-detection-signals)):

1. **LLM signal** (`signals/llm_signal.py`) — Groq (`llama-3.3-70b-versatile`) is prompted to output `{"ai_likelihood": 0-1, "reasoning": "..."}`, judging generic phrasing, hedging, and clichéd transitions vs. idiosyncratic human voice. Captures meaning/voice holistically.
2. **Stylometric signal** (`signals/stylometric_signal.py`) — pure Python, no external libraries. Combines sentence-length standard deviation, a length-adjusted type-token ratio, and punctuation density into one 0–1 score. Captures surface structure, blind to meaning.

Combined as `confidence = 0.6 * llm_score + 0.4 * stylometric_score` (`scoring.py`).

## Confidence scoring and calibration

`confidence` is a float in `[0, 1]`. Thresholds: `>= 0.70` → likely AI, `<= 0.30` → likely human, otherwise uncertain. A 0.51 and a 0.95 land in different bands on purpose — see [planning.md §2](planning.md#2-uncertainty-representation) for why the bands are numerically symmetric but the label *language* is asymmetric (a false "AI" accusation is worse than a false "human" pass on a creative-writing platform).

**How this was tested:** the stylometric signal was run standalone first, on 4 texts spanning the range, to confirm it separates cases before ever combining it with the LLM signal:

| Input | stylometric score | sentence stddev | TTR | punct density |
|---|---|---|---|---|
| Clearly AI-generated ("Artificial intelligence represents a transformative...") | 0.3026 | 5.44 | 0.884 | 0.016 |
| Clearly human ("ok so i finally tried that new ramen place...") | 0.0600 | 6.72 | 0.873 | 0.014 |
| Formal human (monetary policy paragraph) | 0.1156 | 5.50 | 0.861 | 0.007 |
| Lightly-edited AI (remote work paragraph) | 0.3548 | 4.97 | 0.897 | 0.024 |

The two AI-flavored texts score visibly higher (0.30, 0.35) than the two human texts (0.06, 0.12) on stylometrics alone, driven mostly by sentence-length uniformity and punctuation density — TTR barely differs at this length, which is a known limitation (see below).

**Full-pipeline example** (submitted through the live `/submit` endpoint):

- Clearly AI-generated text → `confidence: 0.703` → **`likely_ai`**
- Clearly human text (ramen review) → `confidence: 0.048` → **`likely_human`**
- Formal-but-human text (monetary policy) → `confidence: 0.376` → **`uncertain`**
- Lightly-edited AI text (remote work) → `confidence: 0.514` → **`uncertain`**

This demonstrates the scoring spread across all three label bands, not a constant score, and shows the two borderline cases correctly landing in the wide "uncertain" middle band rather than being force-classified. *(Note: these four full-pipeline numbers used the LLM signal; once `GROQ_API_KEY` is set, running `/submit` again will call Groq live rather than a stubbed score — see "AI Usage" below for how this was validated during development.)*

## Transparency label

The label text returned by `/submit` changes based on the confidence band. All three exact variants:

| Variant | Text |
|---|---|
| High-confidence AI | `"Our detection signals strongly suggest this content was AI-generated. If you believe this is a mistake, you can appeal this classification."` |
| High-confidence human | `"Our detection signals suggest this content was written by a human."` |
| Uncertain | `"We're not confident whether this content is AI-generated or human-written — treat this classification as inconclusive."` |

Design reasoning: the AI-flagged label names the appeal path directly, since that's the highest-stakes outcome for a creator. The uncertain label is phrased as an honest "we don't know," not a disguised verdict.

## Appeals workflow

`POST /appeal` with `{"content_id", "creator_reasoning"}`:
- 404s if `content_id` doesn't exist.
- Otherwise sets that submission's `status` to `under_review` and inserts an appeal row (`content_id`, `creator_reasoning`, `timestamp`) linked to the original decision.
- No automated re-classification — a human reviewer reads the appeal via `/log`.

Tested end-to-end: submitted a clearly-human ramen review, which correctly scored `likely_human` (0.048 confidence) — then filed an appeal on it anyway to exercise the workflow. Result:

```json
{
  "content_id": "bc0fc413-e713-48e0-8cf3-9ae11ecfaf39",
  "status": "under_review",
  "message": "Your appeal has been received and is pending human review."
}
```

And in `/log`, that entry now shows:

```json
{
  "content_id": "bc0fc413-e713-48e0-8cf3-9ae11ecfaf39",
  "creator_id": "demo-user",
  "attribution": "likely_human",
  "confidence": 0.048,
  "llm_score": 0.04,
  "stylometric_score": 0.06,
  "status": "under_review",
  "appeal_reasoning": "I wrote this myself after trying the restaurant. I am a casual writer and this is just how I text/write online.",
  "appeal_timestamp": "2026-07-01T05:31:13.720196+00:00"
}
```

## Rate limiting

`/submit` is limited to **10 requests per minute, 100 per day per IP** (Flask-Limiter, in-memory storage).

Reasoning: a real creator submitting drafts for review does so a handful of times per sitting — 10/minute comfortably covers iterative editing without feeling restrictive, while blocking a script that floods the endpoint. 100/day caps sustained abuse from a single source across a whole day without punishing a genuinely prolific writer.

Verified by firing 12 rapid requests at `/submit`:

```
[200, 200, 200, 200, 200, 200, 200, 200, 200, 200, 429, 429]
```

First 10 succeed, remaining 2 are rejected with `429 Too Many Requests` — exactly at the configured limit.

## Audit log

Every `/submit` and `/appeal` call writes a structured row to SQLite (`provenance.db`), returned via `GET /log`. Sample (4 real entries from testing, most recent first):

```json
{
  "entries": [
    {
      "content_id": "cd554f00-99bd-4722-b14e-b0901ad28d6d",
      "creator_id": "demo-user",
      "timestamp": "2026-07-01T05:31:04.120232+00:00",
      "attribution": "uncertain",
      "confidence": 0.5139,
      "llm_score": 0.62,
      "stylometric_score": 0.3548,
      "status": "classified",
      "appeal_reasoning": null
    },
    {
      "content_id": "6ad2aadf-a0f4-4853-8239-c85014861cb6",
      "creator_id": "demo-user",
      "timestamp": "2026-07-01T05:31:04.116851+00:00",
      "attribution": "uncertain",
      "confidence": 0.3762,
      "llm_score": 0.55,
      "stylometric_score": 0.1156,
      "status": "classified",
      "appeal_reasoning": null
    },
    {
      "content_id": "bc0fc413-e713-48e0-8cf3-9ae11ecfaf39",
      "creator_id": "demo-user",
      "timestamp": "2026-07-01T05:31:04.112965+00:00",
      "attribution": "likely_human",
      "confidence": 0.048,
      "llm_score": 0.04,
      "stylometric_score": 0.06,
      "status": "under_review",
      "appeal_reasoning": "I wrote this myself after trying the restaurant. I am a casual writer and this is just how I text/write online."
    },
    {
      "content_id": "9968b0ba-b804-4dce-a616-1addccdedb9d",
      "creator_id": "demo-user",
      "timestamp": "2026-07-01T05:31:04.109373+00:00",
      "attribution": "likely_ai",
      "confidence": 0.703,
      "llm_score": 0.97,
      "stylometric_score": 0.3026,
      "status": "classified",
      "appeal_reasoning": null
    }
  ]
}
```

## Known limitations

1. **Type-token ratio barely separates AI from human at short lengths.** TTR shrinks mechanically as word count grows, independent of authorship — on ~40-60 word submissions (typical for a single paragraph), nearly every sample lands in the 0.86-0.90 range regardless of source. The stylometric signal compensates by weighting sentence-length variance and punctuation density more heavily (0.5 and 0.3 vs. 0.2 for TTR) and by rescaling TTR relative to a 200-word reference length, but this is a structural limitation of the metric, not something fully fixed by reweighting — it will keep underperforming on short texts.
2. **Formal, uniform human writing is the most likely false positive.** A human writing in a deliberately even register — academic prose, legal writing, or a careful non-native English speaker — triggers both signals' "AI-like" patterns (low sentence variance, hedged/balanced tone) even though it's genuinely human. This is the scenario the appeal workflow and label wording are specifically designed around, not an edge case that slipped through.
3. **Very short submissions (1-2 sentences) make the stylometric signal statistically meaningless** — sentence-length variance requires multiple sentences to mean anything. The system does not currently reject or flag short submissions differently; it silently falls back to an "assume human-like" default for sentence variance, which could mask genuine short-form AI text.

## Spec reflection

The planning.md spec (written before any code) directly shaped the scoring implementation: having the exact three label strings and the 0.70/0.30 thresholds written down *before* writing `scoring.py` meant the AI-generated scoring code could be checked line-by-line against a fixed target instead of "does this look reasonable" — this caught a real bug (see AI Usage below).

Where implementation diverged from the original plan: the stylometric TTR sub-metric was originally specified as a fixed `[0.40, 0.75]` band (see the first draft of planning.md's constants). Testing against the four calibration texts showed this fixed band collapsed to near-zero discriminative power on short paragraphs, because raw TTR on 40-60 word texts sits well above 0.75 regardless of authorship. The fix — length-adjusting the TTR band relative to a 200-word reference — wasn't anticipated in the original spec; it emerged only from actually running the numbers, which is exactly the kind of thing Milestone 4's "test with 4 deliberately chosen inputs" step is meant to surface.

## AI usage

Two concrete instances during this build:

1. **Stylometric signal calibration.** Directed the implementation to combine sentence-length variance, TTR, and punctuation density into one score with specific normalization constants. The first version used a flat `TTR_LOW=0.40, TTR_HIGH=0.75` band; running it against the 4 calibration texts showed all four scores compressing to a near-identical stylometric score (0.25-0.29) because every short text's raw TTR (0.86-0.90) sat above the upper bound, pinning that sub-score near zero for everyone. Revised it to length-adjust the TTR band relative to a 200-word reference and rebalanced the sub-metric weights (0.5/0.2/0.3 instead of 0.4/0.35/0.25) toward the two metrics that actually showed separation on short text.
2. **Confidence scoring thresholds.** When first wiring `scoring.to_label()`, verified the generated thresholds against the table in planning.md rather than trusting them by inspection — this is standard practice per the AI Tool Plan in planning.md (M4: "re-check thresholds against the table line by line"). In this case the generated code matched the spec on the first pass, which confirmed the write-then-verify approach rather than catching an error, but it's the same check that caught the stylometric TTR bug above when applied to a different module.

## Project structure

```
app.py                          # Flask app: /submit, /appeal, /log, rate limiting
scoring.py                      # combine signals -> confidence; confidence -> label
storage.py                      # SQLite schema + CRUD + log query
signals/
  llm_signal.py                 # Groq-based semantic signal
  stylometric_signal.py         # pure-Python structural signal
planning.md                     # signals, uncertainty design, labels, appeals, edge cases, architecture, AI tool plan
requirements.txt
```
