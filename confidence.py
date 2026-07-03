DISAGREEMENT_THRESHOLD = 0.30
AGREEMENT_THRESHOLD = 0.15
LIKELY_AI_THRESHOLD = 0.72
LIKELY_HUMAN_THRESHOLD = 0.40
UNCERTAIN_BAND = (LIKELY_HUMAN_THRESHOLD, LIKELY_AI_THRESHOLD)
LLM_WEIGHT = 0.6
STYLO_WEIGHT = 0.4
FALLBACK_CAP = 0.69


def attribute(combined_score):
    """Map a combined_score to an attribution label using the calibrated thresholds."""
    if combined_score >= LIKELY_AI_THRESHOLD:
        return "likely_ai"
    if combined_score < LIKELY_HUMAN_THRESHOLD:
        return "likely_human"
    return "uncertain"


def _pull_toward_uncertain(score):
    """Pull a score toward the uncertain band without fully discarding it."""
    low, high = UNCERTAIN_BAND
    if score < low:
        return low
    if score > high:
        return high
    return score


def compute_confidence(llm_result, stylo_score):
    """Combine the LLM signal and stylometric signal into a single calibrated confidence score.

    llm_result: dict from signals.classify_with_llm — {llm_ai_probability, label, reason, status}
    stylo_score: float in [0,1] from stylometry.compute_stylo_score

    Returns a dict: {combined_score, basis, llm_score, stylo_score}
    basis is one of: "combined", "stylo_only_fallback" — records which path was taken.
    """
    llm_status = llm_result.get("status")
    llm_score = llm_result.get("llm_ai_probability")

    if llm_status != "success" or llm_score is None:
        combined_score = min(stylo_score, FALLBACK_CAP)
        return {
            "combined_score": round(combined_score, 4),
            "basis": "stylo_only_fallback",
            "llm_score": llm_score,
            "stylo_score": round(stylo_score, 4),
            "llm_status": llm_status,
        }

    spread = abs(llm_score - stylo_score)
    raw_combined = (LLM_WEIGHT * llm_score) + (STYLO_WEIGHT * stylo_score)

    same_side = (llm_score >= 0.5) == (stylo_score >= 0.5)

    if same_side and spread <= AGREEMENT_THRESHOLD:
        combined_score = raw_combined
    elif spread > DISAGREEMENT_THRESHOLD:
        combined_score = _pull_toward_uncertain(raw_combined)
    else:
        combined_score = raw_combined

    return {
        "combined_score": round(combined_score, 4),
        "basis": "combined",
        "llm_score": round(llm_score, 4),
        "stylo_score": round(stylo_score, 4),
        "llm_status": llm_status,
    }


if __name__ == "__main__":
    from signals import classify_with_llm
    from stylometry import compute_stylo_score

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
        llm_result = classify_with_llm(text)
        stylo_result = compute_stylo_score(text)
        confidence = compute_confidence(llm_result, stylo_result["stylo_score"])
        attribution = attribute(confidence["combined_score"])

        print(f"--- {name} ---")
        print(f"llm_score: {confidence['llm_score']} (status: {confidence['llm_status']})   stylo_score: {confidence['stylo_score']}")
        print(f"combined_score: {confidence['combined_score']}  basis: {confidence['basis']}  -> attribution: {attribution}")
        print()

    print("--- fallback test: simulated LLM failure ---")
    fake_failed_llm = {"llm_ai_probability": None, "label": "uncertain", "reason": "simulated failure", "status": "parse_failure"}
    high_stylo = 0.95
    confidence = compute_confidence(fake_failed_llm, high_stylo)
    print(f"stylo_score: {high_stylo} (very uniform) + failed LLM -> combined_score: {confidence['combined_score']} (capped at {FALLBACK_CAP}), basis: {confidence['basis']}")
