"""Provenance Guard Flask app: /submit, /appeal, /log."""
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

import scoring
import storage
from signals import llm_signal, stylometric_signal

load_dotenv()
storage.init_db()

app = Flask(__name__)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)


def _now():
    return datetime.now(timezone.utc).isoformat()


@app.route("/submit", methods=["POST"])
@limiter.limit("10 per minute;100 per day")
def submit():
    body = request.get_json(silent=True) or {}
    text = body.get("text")
    creator_id = body.get("creator_id")

    if not text or not isinstance(text, str):
        return jsonify({"error": "'text' is required and must be a string"}), 400
    if not creator_id or not isinstance(creator_id, str):
        return jsonify({"error": "'creator_id' is required and must be a string"}), 400

    llm_result = llm_signal.analyze(text)
    style_result = stylometric_signal.analyze(text)

    confidence = scoring.combine(llm_result["score"], style_result["score"])
    attribution, label = scoring.to_label(confidence)

    content_id = str(uuid.uuid4())
    record = {
        "content_id": content_id,
        "creator_id": creator_id,
        "text": text,
        "llm_score": llm_result["score"],
        "llm_reasoning": llm_result["reasoning"],
        "stylometric_score": style_result["score"],
        "confidence": confidence,
        "attribution": attribution,
        "label": label,
        "status": "classified",
        "created_at": _now(),
    }
    storage.save_submission(record)

    return jsonify(
        {
            "content_id": content_id,
            "attribution": attribution,
            "confidence": confidence,
            "label": label,
            "signals": {
                "llm": llm_result,
                "stylometric": style_result,
            },
        }
    )


@app.route("/appeal", methods=["POST"])
def appeal():
    body = request.get_json(silent=True) or {}
    content_id = body.get("content_id")
    creator_reasoning = body.get("creator_reasoning")

    if not content_id or not isinstance(content_id, str):
        return jsonify({"error": "'content_id' is required and must be a string"}), 400
    if not creator_reasoning or not isinstance(creator_reasoning, str):
        return jsonify({"error": "'creator_reasoning' is required and must be a string"}), 400

    submission = storage.get_submission(content_id)
    if submission is None:
        return jsonify({"error": f"No submission found with content_id={content_id}"}), 404

    storage.mark_under_review(content_id)
    storage.save_appeal(content_id, creator_reasoning, _now())

    return jsonify(
        {
            "content_id": content_id,
            "status": "under_review",
            "message": "Your appeal has been received and is pending human review.",
        }
    )


@app.route("/log", methods=["GET"])
def log():
    return jsonify({"entries": storage.get_log_entries()})


if __name__ == "__main__":
    app.run(debug=True)
