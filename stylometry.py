import re
import statistics


def _split_sentences(text):
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s for s in sentences if s.strip()]


def _split_words(text):
    return re.findall(r"[A-Za-z']+", text.lower())


def sentence_length_variance_score(sentences):
    """Std-dev of sentence length (in words). Normalized so low variance (uniform) -> 1.0."""
    if len(sentences) < 2:
        return 0.5

    lengths = [len(_split_words(s)) for s in sentences]
    mean_len = statistics.mean(lengths) or 1
    stdev = statistics.pstdev(lengths)

    coefficient_of_variation = stdev / mean_len
    # CoV of 0 -> uniform -> 1.0; CoV >= 1.0 -> highly bursty -> 0.0
    normalized_variability = min(coefficient_of_variation, 1.0)
    return 1.0 - normalized_variability


def vocabulary_richness_score(words):
    """Type-token ratio. Low richness (repetitive vocab) -> uniform -> high score.

    Raw TTR is naturally high (0.8-1.0) for short passages regardless of origin,
    since repetition only shows up over longer stretches of text. Rescale against
    a realistic short-text range (0.55-1.0) instead of the full [0,1] so the
    metric actually discriminates rather than pinning near 0 for every input.
    """
    if not words:
        return 0.5

    ttr = len(set(words)) / len(words)
    floor, ceiling = 0.55, 1.0
    normalized_ttr = (min(max(ttr, floor), ceiling) - floor) / (ceiling - floor)
    # Low relative TTR (repetitive) -> AI-leaning -> high score, so invert.
    return 1.0 - normalized_ttr


def sentence_complexity_score(sentences, words):
    """Mean sentence length combined with clause density (commas/conjunctions per sentence).
    Long, uniformly complex sentences -> AI-leaning -> high score."""
    if not sentences or not words:
        return 0.5

    mean_sentence_length = len(words) / len(sentences)
    clause_markers = sum(
        len(re.findall(r",|\b(and|but|which|that|because|although|while)\b", s.lower()))
        for s in sentences
    )
    clause_density = clause_markers / len(sentences)

    # Normalize: cap mean length at 30 words/sentence and clause density at 3 markers/sentence.
    normalized_length = min(mean_sentence_length / 30.0, 1.0)
    normalized_clauses = min(clause_density / 3.0, 1.0)

    return (normalized_length + normalized_clauses) / 2.0


def compute_stylo_score(text):
    """Compute the combined stylometric score for a piece of text.

    Returns a dict: {stylo_score, metrics} where stylo_score is in [0,1]
    (1.0 = highly uniform/AI-leaning, 0.0 = highly variable/bursty/human-leaning).
    """
    sentences = _split_sentences(text)
    words = _split_words(text)

    metrics = {
        "sentence_length_variance": sentence_length_variance_score(sentences),
        "vocabulary_richness": vocabulary_richness_score(words),
        "sentence_complexity": sentence_complexity_score(sentences, words),
    }

    weights = {
        "sentence_length_variance": 0.45,
        "vocabulary_richness": 0.30,
        "sentence_complexity": 0.25,
    }

    stylo_score = sum(metrics[k] * weights[k] for k in weights)

    return {
        "stylo_score": round(stylo_score, 4),
        "metrics": {k: round(v, 4) for k, v in metrics.items()},
    }


if __name__ == "__main__":
    from signals import classify_with_llm

    test_inputs = [
        (
            "clearly_ai",
            "Artificial intelligence represents a transformative paradigm shift in modern society. "
            "It is important to note that while the benefits of AI are numerous, it is equally "
            "essential to consider the ethical implications. Furthermore, stakeholders across "
            "various sectors must collaborate to ensure responsible deployment.",
        ),
        (
            "clearly_human",
            "ok so i finally tried that new ramen place downtown and honestly? "
            "underwhelming. the broth was fine but they put WAY too much sodium in it and "
            "i was thirsty for like three hours after. my friend got the spicy version and "
            "said it was better. probably won't go back unless someone drags me there",
        ),
        (
            "borderline_formal_human",
            "The relationship between monetary policy and asset price inflation has been "
            "extensively studied in the literature. Central banks face a fundamental tension "
            "between their mandate for price stability and the unintended consequences of "
            "prolonged low interest rates on equity and real estate valuations.",
        ),
        (
            "borderline_edited_ai",
            "I've been thinking a lot about remote work lately. There are genuine tradeoffs — "
            "flexibility and no commute on one side, isolation and blurred work-life boundaries "
            "on the other. Studies show productivity varies widely by individual and role type.",
        ),
    ]

    for name, text in test_inputs:
        stylo_result = compute_stylo_score(text)
        llm_result = classify_with_llm(text)

        print(f"--- {name} ---")
        print(f"Text: {text[:80]}...")
        print(f"stylo_score: {stylo_result['stylo_score']}  (metrics: {stylo_result['metrics']})")
        print(f"llm_score:   {llm_result['llm_ai_probability']}  (status: {llm_result['status']}, label: {llm_result['label']})")

        stylo = stylo_result["stylo_score"]
        llm = llm_result["llm_ai_probability"]
        if llm is not None:
            spread = abs(stylo - llm)
            agreement = "AGREE" if spread <= 0.15 else ("DISAGREE" if spread > 0.30 else "partial")
            print(f"spread: {round(spread, 4)} -> {agreement}")
        print()
