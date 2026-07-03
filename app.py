import time
import uuid
from datetime import datetime, timezone

from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from signals import classify_with_llm
from stylometry import compute_stylo_score
from confidence import compute_confidence, attribute
from labels import get_label_text
from audit_log import append_entry, get_log, find_original_by_content_id, update_status

app = Flask(__name__)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)

CREATOR_MIN_INTERVAL_SECONDS = 20
_last_submission_by_creator = {}


def _creator_rate_limited(creator_id):
    """Enforce a minimum interval between submissions from the same creator_id,
    independent of the IP-based limiter (catches a single scripted identity
    hammering the endpoint from behind a shared/rotating IP)."""
    now = time.monotonic()
    last_submitted = _last_submission_by_creator.get(creator_id)
    if last_submitted is not None and (now - last_submitted) < CREATOR_MIN_INTERVAL_SECONDS:
        return True
    _last_submission_by_creator[creator_id] = now
    return False


@app.route("/")
def hello_world():
    return "<p>Hello, World!</p>"


@app.route("/submit", methods=["POST"])
@limiter.limit("10 per minute;100 per day")
def submit():
    data = request.get_json(silent=True) or {}
    text = data.get("text")
    creator_id = data.get("creator_id")

    if not text or not creator_id:
        return jsonify({"error": "text and creator_id are required"}), 400

    if _creator_rate_limited(creator_id):
        return jsonify({
            "error": f"Too many submissions for creator_id '{creator_id}'. "
                     f"Please wait at least {CREATOR_MIN_INTERVAL_SECONDS} seconds between submissions."
        }), 429

    content_id = str(uuid.uuid4())
    llm_result = classify_with_llm(text)
    stylo_result = compute_stylo_score(text)
    confidence = compute_confidence(llm_result, stylo_result["stylo_score"])
    attribution = attribute(confidence["combined_score"])
    label_text = get_label_text(attribution)

    log_entry = {
        "content_id": content_id,
        "creator_id": creator_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "attribution": attribution,
        "confidence": confidence["combined_score"],
        "llm_score": confidence["llm_score"],
        "stylo_score": confidence["stylo_score"],
        "confidence_basis": confidence["basis"],
        "status": "classified",
        "appeal_filed": False,
    }
    append_entry(log_entry)

    return jsonify({
        "content_id": content_id,
        "attribution": attribution,
        "confidence": confidence["combined_score"],
        "signal_scores": {
            "llm_score": confidence["llm_score"],
            "stylo_score": confidence["stylo_score"],
        },
        "label": label_text
    })


@app.route("/appeal", methods=["POST"])
@limiter.limit("10 per minute;100 per day")
def appeal():
    data = request.get_json(silent=True) or {}
    content_id = data.get("content_id")
    creator_reasoning = data.get("creator_reasoning")

    if not content_id or not creator_reasoning:
        return jsonify({"error": "content_id and creator_reasoning are required"}), 400

    original_entry = find_original_by_content_id(content_id)
    if original_entry is None:
        return jsonify({"error": f"No submission found for content_id {content_id}"}), 404

    update_status(content_id, "under_review", appeal_filed=True)

    appeal_entry = {
        "content_id": content_id,
        "creator_id": original_entry.get("creator_id"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "appeal_reasoning": creator_reasoning,
        "status": "under_review",
        "original_decision": {
            "attribution": original_entry.get("attribution"),
            "confidence": original_entry.get("confidence"),
            "llm_score": original_entry.get("llm_score"),
            "stylo_score": original_entry.get("stylo_score"),
            "timestamp": original_entry.get("timestamp"),
        },
    }
    append_entry(appeal_entry)

    return jsonify({
        "content_id": content_id,
        "status": "under_review",
        "message": "Appeal received."
    })


@app.route("/log", methods=["GET"])
def log():
    return jsonify({"entries": get_log()})


if __name__ == "__main__":
    app.run(debug=True)
