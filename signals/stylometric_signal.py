"""Stylometric heuristic signal: measures structural uniformity of text.

Captures a genuinely different property from the LLM signal — surface
statistics rather than meaning. Combines three sub-metrics into one
0-1 "AI-likelihood" score (higher = more uniform/AI-like).
"""
import re

# Normalization constants, chosen from typical prose statistics rather
# than tuned on a specific dataset. Documented here instead of left as
# unexplained magic numbers.

# Sentence-length std-dev (in words) above which we consider variance
# "high" (human-like); below this it's considered "low" (AI-like, uniform pacing).
SENTENCE_VARIANCE_HIGH = 6.0
SENTENCE_VARIANCE_LOW = 1.5

# Type-token ratio (unique words / total words) — AI text tends to reuse
# a narrower vocabulary. Below this ratio reads as "repetitive" (AI-like);
# above reads as "diverse" (human-like). TTR shrinks mechanically as word
# count grows (more chances to repeat a word), so the band is expressed
# relative to a text of ~WORD_COUNT_REFERENCE words rather than as a fixed
# constant — otherwise short submissions always look "diverse" regardless
# of authorship.
WORD_COUNT_REFERENCE = 200.0
TTR_LOW = 0.40
TTR_HIGH = 0.92

# Punctuation density (punctuation marks / total characters) — AI text
# tends toward a narrow, conventional band; human text is often burstier
# (many exclamation marks/ellipses, or very sparse punctuation).
PUNCT_DENSITY_CONVENTIONAL_LOW = 0.015
PUNCT_DENSITY_CONVENTIONAL_HIGH = 0.035


def _split_sentences(text):
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s for s in sentences if s.strip()]


def _split_words(text):
    return re.findall(r"[A-Za-z']+", text.lower())


def _normalize(value, low, high, invert=False):
    """Map value into [0, 1] given a [low, high] band; clamp at edges.

    If invert=False: value <= low -> 1.0 (AI-like), value >= high -> 0.0 (human-like).
    """
    if high == low:
        return 0.5
    score = (high - value) / (high - low)
    score = max(0.0, min(1.0, score))
    return 1.0 - score if invert else score


def analyze(text):
    sentences = _split_sentences(text)
    words = _split_words(text)

    if len(sentences) >= 2:
        lengths = [len(_split_words(s)) for s in sentences]
        mean_len = sum(lengths) / len(lengths)
        variance = sum((l - mean_len) ** 2 for l in lengths) / len(lengths)
        sentence_len_stddev = variance ** 0.5
    else:
        sentence_len_stddev = SENTENCE_VARIANCE_HIGH  # insufficient data, assume human-like

    variance_score = _normalize(
        sentence_len_stddev, SENTENCE_VARIANCE_LOW, SENTENCE_VARIANCE_HIGH
    )

    if words:
        raw_ttr = len(set(words)) / len(words)
        # Rescale as if the text were WORD_COUNT_REFERENCE words long, since
        # TTR shrinks with length regardless of authorship. sqrt curve
        # approximates how TTR decays as vocabulary saturates.
        length_factor = (len(words) / WORD_COUNT_REFERENCE) ** 0.5
        ttr = min(1.0, raw_ttr / max(length_factor, 0.3))
    else:
        raw_ttr = ttr = TTR_HIGH
    ttr_score = _normalize(ttr, TTR_LOW, TTR_HIGH)

    punct_count = len(re.findall(r"[.,;:!?\-–—]", text))
    punct_density = punct_count / len(text) if text else 0.0
    if punct_density <= PUNCT_DENSITY_CONVENTIONAL_LOW or punct_density >= PUNCT_DENSITY_CONVENTIONAL_HIGH:
        punct_score = 0.2  # bursty/sparse -> human-like
    else:
        punct_score = 0.8  # conventional, narrow band -> AI-like

    combined = (variance_score * 0.5) + (ttr_score * 0.2) + (punct_score * 0.3)

    return {
        "score": round(combined, 4),
        "sentence_len_stddev": round(sentence_len_stddev, 4),
        "type_token_ratio": round(raw_ttr, 4),
        "punctuation_density": round(punct_density, 4),
    }
