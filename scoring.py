"""Combines signal scores into a confidence value and maps confidence to
the exact transparency label text (see planning.md sections 1-3)."""

LLM_WEIGHT = 0.6
STYLE_WEIGHT = 0.4

THRESHOLD_HIGH_AI = 0.70
THRESHOLD_HIGH_HUMAN = 0.30

LABEL_LIKELY_AI = (
    "Our detection signals strongly suggest this content was AI-generated. "
    "If you believe this is a mistake, you can appeal this classification."
)
LABEL_LIKELY_HUMAN = (
    "Our detection signals suggest this content was written by a human."
)
LABEL_UNCERTAIN = (
    "We're not confident whether this content is AI-generated or "
    "human-written — treat this classification as inconclusive."
)


def combine(llm_score, stylometric_score):
    confidence = (LLM_WEIGHT * llm_score) + (STYLE_WEIGHT * stylometric_score)
    return round(confidence, 4)


def to_label(confidence):
    if confidence >= THRESHOLD_HIGH_AI:
        return "likely_ai", LABEL_LIKELY_AI
    if confidence <= THRESHOLD_HIGH_HUMAN:
        return "likely_human", LABEL_LIKELY_HUMAN
    return "uncertain", LABEL_UNCERTAIN
