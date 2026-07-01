# Provenance Guard — Planning

## 1. Detection Signals

Provenance Guard uses two independent signals, chosen because they capture genuinely different properties of the text (one semantic, one structural).

### Signal 1: LLM Judgment (Groq, `llama-3.3-70b-versatile`)

- **What it measures:** Holistic semantic and stylistic coherence — the model is prompted to read the full passage and judge whether it reads as AI-generated or human-written, considering things like generic phrasing, hedging patterns, unnatural evenness of tone, and clichéd transitions ("Furthermore," "It is important to note").
- **Output shape:** JSON `{"ai_likelihood": <float 0.0-1.0>, "reasoning": "<short string>"}`. `ai_likelihood` is used directly as `llm_score`.
- **Why chosen:** LLMs are good at picking up on the "generic AI voice" — over-hedged, over-balanced, cliché-heavy prose — that is hard to reduce to a simple statistic.
- **Blind spot:** Can be fooled by lightly-edited AI text (a human paraphrasing an AI draft), and can be confidently *wrong* on unusual-but-genuine human styles: non-native English speakers who write more formally/carefully, or writers whose personal style happens to be very polished. It has no ground truth — it's pattern-matching on the same training data that produced modern AI writing style, so its errors are correlated with, not independent of, "text that reads AI-flavored regardless of source."

### Signal 2: Stylometric Heuristics (pure Python)

- **What it measures:** Structural/statistical uniformity of the writing — three sub-metrics combined:
  1. **Sentence-length variance** — human writing tends to mix short and long sentences; AI text is often more evenly paced.
  2. **Type-token ratio (TTR)** — vocabulary diversity (unique words / total words). Lower TTR can indicate repetitive, "safe" word choice typical of AI generation; but short texts naturally have high TTR regardless of authorship, which is corrected for below.
  3. **Punctuation density** — AI text tends toward conventional, evenly-distributed punctuation; human text is often burstier (em-dashes, ellipses, exclamation runs, or minimal punctuation in casual writing).
- **Output shape:** `{"score": <float 0.0-1.0>, "sentence_len_variance": <float>, "type_token_ratio": <float>, "punctuation_density": <float>}`. `score` is a 0–1 "AI-likelihood" derived from normalizing and combining the three sub-metrics (low variance + low diversity + conventional punctuation → high score).
- **Why chosen:** Purely computable, no external dependency, and captures *structure* rather than *meaning* — genuinely independent of what the LLM signal is doing.
- **Blind spot:** Unstable on short texts (a 2-sentence submission has meaningless "variance"). Doesn't understand content at all — a human writing in a deliberately uniform, formal register (technical documentation, legal writing) will score as AI-like even though it's genuinely human. Also blind to plagiarism/lightly-edited AI text, since editing can renormalize sentence rhythm without changing the substance.

### Combining into one confidence score

```
combined_confidence = 0.6 * llm_score + 0.4 * stylometric_score
```

The LLM signal is weighted higher (0.6) because it evaluates meaning and holistic voice, which is generally more diagnostic than surface statistics alone — but the stylometric signal (0.4) still meaningfully pulls the score back when the LLM is likely overconfident on structurally-human text (e.g. bursty punctuation, high sentence variance). Both signals are stored individually in the audit log regardless of the combined score, so a human reviewer can always see *why* a score landed where it did.

## 2. Uncertainty Representation

`combined_confidence` is a float in `[0, 1]` representing "how much this looks AI-generated," not a probability of ground truth. A score of exactly 0.5 means the two signals actively disagree or both landed near the middle — genuine ambiguity, not "50% chance." A 0.51 and a 0.95 must produce different user-facing labels because they represent very different evidentiary strength, even though both are technically "above the midpoint."

**Thresholds** (deliberately asymmetric — see false-positive reasoning below):

| combined_confidence | attribution | label shown |
|---|---|---|
| `>= 0.70` | `likely_ai` | High-confidence AI label |
| `0.31 – 0.69` | `uncertain` | Uncertain label |
| `<= 0.30` | `likely_human` | High-confidence human label |

**Why asymmetric-feeling but numerically symmetric bands:** A false positive (calling a human's work AI) is worse than a false negative on a creative-writing platform — it can damage a real creator's reputation and livelihood. Rather than shifting the numeric thresholds asymmetrically (which would just be security theater — the model's calibration doesn't actually justify picking 0.65 over 0.70), the asymmetry is enforced in **label language and appeal visibility**: the "likely AI" label is phrased more cautiously ("Our system's signals suggest...") than the "likely human" label, and every AI-flagged submission is told explicitly how to appeal. Uncertainty is treated as the default — a wide 0.31–0.69 middle band means most borderline content lands in "uncertain" rather than getting force-flipped to a binary AI/human call.

**Calibration testing approach:** tested against 4 deliberately chosen inputs spanning the range (clearly AI, clearly human, formal-but-human, lightly-edited-AI) — see README §Confidence Scoring for actual scores produced. The test checks two things: (1) does score *ordering* match intuition (clear-AI > borderline > clear-human), and (2) does the *spread* between clear cases and borderline cases stay wide enough that borderline cases land in the "uncertain" band rather than being force-classified.

## 3. Transparency Label Design

Exact text returned by the API and meant for display to a non-technical reader:

| Variant | Label text |
|---|---|
| High-confidence AI | `"Our detection signals strongly suggest this content was AI-generated. If you believe this is a mistake, you can appeal this classification."` |
| High-confidence human | `"Our detection signals suggest this content was written by a human."` |
| Uncertain | `"We're not confident whether this content is AI-generated or human-written — treat this classification as inconclusive."` |

Design notes: the AI-flagged label explicitly names the appeal path in the same sentence, since that's the highest-stakes case for the creator. The human-flagged label is stated plainly with no hedge (it's the "safe" outcome, no reason to hedge further). The uncertain label explicitly says "we're not confident" rather than picking a side — it should read as an honest shrug, not a disguised binary verdict.

## 4. Appeals Workflow

- **Who can appeal:** the original creator (`creator_id` on the submission), identified by `content_id`.
- **What they provide:** `content_id` and `creator_reasoning` (free text explaining why they believe the classification is wrong).
- **What the system does on receipt:**
  1. Look up the submission by `content_id`; 404 if not found.
  2. Update that submission's `status` to `"under_review"`.
  3. Insert an appeal record (`content_id`, `creator_reasoning`, `timestamp`) linked to the original decision.
  4. Return a confirmation JSON (`content_id`, new `status`, confirmation message).
- **No automated re-classification** — a human reviewer is expected to look at the appeal queue out-of-band.
- **What a human reviewer would see** (via `GET /log`, filtered to `status = "under_review"`): the original text, both signal scores, the combined confidence, the label that was shown, and the creator's appeal reasoning — everything needed to make a manual call without re-running detection.

## 5. Anticipated Edge Cases

1. **Formal/technical human writing mis-flagged as AI.** A human writing in a deliberately uniform register (academic abstract, legal memo, or a non-native English speaker who writes carefully and formally) will show low sentence-length variance and conventional punctuation — exactly what the stylometric signal treats as AI-like — and the LLM signal may agree because that register overlaps with "generic AI voice." This is the single biggest false-positive risk and is why the label language + appeal path are treated as first-class, not an afterthought.
2. **Very short submissions.** Stylometric metrics (variance, TTR) are statistically meaningless on 1–2 sentences — a haiku-length submission could swing wildly based on a single long or short sentence. The system does not currently reject short submissions, which is a known limitation (documented in README).
3. **Lightly-edited AI output.** A human who takes an AI draft and does a light edit pass (changing a few words, breaking up a couple of sentences) can shift stylometric signals just enough to look human-authored while the underlying content and structure remain AI-generated. Neither signal is designed to catch this — it's a genuine detection gap, not just a labeling problem.

## Architecture

### Flow diagram

```
SUBMISSION FLOW
POST /submit {text, creator_id}
      │
      ▼
[Signal 1: Groq LLM]──llm_score (0-1)──┐
      │                                 │
[Signal 2: Stylometrics]──style_score──►[Combine: 0.6*llm + 0.4*style]──combined_score
                                                   │
                                                   ▼
                                        [Label mapper: 3 thresholds]──label_text
                                                   │
                                                   ▼
                                        [Audit log: SQLite insert]
                                                   │
                                                   ▼
                              Response: {content_id, attribution, confidence,
                                          label, signals: {llm, stylometric}}

APPEAL FLOW
POST /appeal {content_id, creator_reasoning}
      │
      ▼
[Lookup content_id in submissions table] ──404 if missing
      │
      ▼
[Update status → "under_review"] ──► [Audit log: insert appeal row]
      │
      ▼
Response: {content_id, status: "under_review", message}
```

### Narrative

A submission's text is run through both detection signals independently — the Groq LLM call and the pure-Python stylometric analysis never see each other's output, which is what makes them genuinely independent signals rather than two versions of the same idea. Their scores are combined into a single confidence float, mapped to one of three label variants via fixed thresholds, and every field (both raw signal scores, the combined score, the label, and a generated `content_id`) is written to the SQLite audit log before the response is returned to the caller. The appeal flow is deliberately separate and lightweight: it never re-runs detection, it only looks up the existing decision by `content_id`, flips status to `under_review`, and appends the creator's reasoning to the same audit trail so a human reviewer has full context in one place.

## AI Tool Plan

### M3 — Submission endpoint + first signal
- **Spec sections provided:** "Detection Signals" (Signal 1 section) + the Architecture diagram.
- **What to generate:** Flask app skeleton with `POST /submit` route stub returning a hardcoded response; the `llm_signal.analyze(text)` function calling Groq with the JSON-mode prompt described above.
- **Verification:** Call `llm_signal.analyze()` directly from a Python shell on 2–3 sample texts before wiring into the route; confirm output matches the `{"score": ..., "reasoning": ...}` shape and that scores look directionally sane (obvious AI text scores high).

### M4 — Second signal + confidence scoring
- **Spec sections provided:** "Detection Signals" (Signal 2 section) + "Uncertainty Representation" + Architecture diagram.
- **What to generate:** `stylometric_signal.analyze(text)` computing the three sub-metrics and combining them; `scoring.combine()` implementing the exact 0.6/0.4 weighting.
- **Verification:** Re-check the generated scoring function's thresholds against the table in §2 line by line (AI tools sometimes invent their own thresholds); run the 4 calibration texts and confirm score ordering + spread matches intuition (see README).

### M5 — Production layer
- **Spec sections provided:** "Transparency Label Design" + "Appeals Workflow" + Architecture diagram.
- **What to generate:** `scoring.to_label(confidence)` returning the exact 3 label strings from §3; `POST /appeal` endpoint implementing the workflow in §4.
- **Verification:** Call `to_label()` with values from each of the 3 bands and diff the returned text against §3 verbatim; submit then appeal a real `content_id` via curl and confirm `GET /log` shows `status: "under_review"` with the `creator_reasoning` populated.
