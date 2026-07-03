import uuid
from datetime import datetime, timezone

from flask import Flask, request, jsonify

from signals import classify_with_llm
from audit_log import append_entry, get_log

app = Flask(__name__)


@app.route("/")
def hello_world():
    return "<p>Hello, World!</p>"


@app.route("/submit", methods=["POST"])
def submit():
    data = request.get_json(silent=True) or {}
    text = data.get("text")
    creator_id = data.get("creator_id")

    if not text or not creator_id:
        return jsonify({"error": "text and creator_id are required"}), 400

    content_id = str(uuid.uuid4())
    llm_result = classify_with_llm(text)
    attribution = llm_result["label"]

    log_entry = {
        "content_id": content_id,
        "creator_id": creator_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "attribution": attribution,
        "confidence": None,
        "llm_score": llm_result["llm_ai_probability"],
        "status": "classified",
    }
    append_entry(log_entry)

    return jsonify({
        "content_id": content_id,
        "attribution": attribution,
        "confidence": None,
        "label": "placeholder-label"
    })


@app.route("/log", methods=["GET"])
def log():
    return jsonify({"entries": get_log()})


if __name__ == "__main__":
    app.run(debug=True)
