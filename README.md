# Provenance Guard

Backend system for classifying whether submitted text content is likely AI-generated or human-written, scoring confidence, surfacing a transparency label, and handling creator appeals.

See [planning.md](planning.md) for the full design spec (detection signals, uncertainty representation, transparency label design, appeals workflow, edge cases, and architecture diagrams).

---

## Rate Limiting

`POST /submit` and `POST /appeal` are both rate-limited using two independent mechanisms:

| Limit | Value | Applies to |
|---|---|---|
| Per-IP, short window | **10 requests / minute** | `/submit`, `/appeal` (via Flask-Limiter) |
| Per-IP, daily cap | **100 requests / day** | `/submit`, `/appeal` (via Flask-Limiter) |
| Per-creator minimum interval | **20 seconds between submissions** | `/submit` (custom, keyed on `creator_id`) |

### Reasoning

**10 requests/minute per IP.** A real writer submitting their own work does not click "submit" more than once every several seconds — even rapid editing-and-resubmitting (fixing a typo, tweaking a paragraph, trying again) rarely produces more than a handful of submissions in a single minute. 10/minute comfortably covers that realistic editing burst while still being far too slow for a script attempting to flood the classification pipeline (each request triggers a real Groq API call, so uncontrolled request volume directly translates to real cost and latency for other users).

**100 requests/day per IP.** Bounds the worst-case daily cost and load from a single IP address even if it isn't tripping the per-minute limit — e.g., a script sending one request every 7 seconds all day would stay under 10/minute but still hit hundreds of requests without a daily cap. 100/day is generous for a genuinely prolific human writer (multiple pieces plus revisions across a full day) while still capping any single IP's worst-case impact on the Groq API budget.

**20-second minimum interval per `creator_id`.** The per-IP limits alone don't catch a single compromised or scripted `creator_id` operating from behind a shared or rotating IP (common on mobile networks, corporate NATs, or a botnet deliberately spreading requests across many IPs to stay under the per-IP limit). Since a `creator_id` represents one creative identity, and composing or meaningfully revising a piece of writing takes more than a few seconds, a 20-second floor between submissions from the same `creator_id` is well below any realistic writing pace but high enough to make a scripted flood of "submissions" from one identity uneconomical to sustain — it forces at most 3 submissions/minute from any single `creator_id`, regardless of what IP they're using.

These two mechanisms are intentionally independent: the IP limit stops a single source (e.g. one script) from overwhelming the system regardless of how many identities it claims to submit as, and the per-creator interval stops a single identity from overwhelming the system regardless of how many IPs it spreads requests across.

### Verifying rate limiting

With the Flask server running, fire 12 rapid requests with distinct `creator_id`s (to isolate the IP-based limit from the per-creator one):

```bash
for i in $(seq 1 12); do
  curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:5000/submit \
    -H "Content-Type: application/json" \
    -d "{\"text\": \"This is a test submission for rate limit testing purposes only.\", \"creator_id\": \"ratelimit-test-$i\"}"
done
```

Observed output (10 succeed, then 429s):

```
200
200
200
200
200
200
200
200
200
200
429
429
```

To see the per-creator interval guard trigger independently, submit twice in a row with the *same* `creator_id`:

```bash
curl -s -X POST http://localhost:5000/submit -H "Content-Type: application/json" -d "{\"text\": \"First submission from this creator.\", \"creator_id\": \"interval-test-user\"}" -w "\nStatus: %{http_code}\n"
curl -s -X POST http://localhost:5000/submit -H "Content-Type: application/json" -d "{\"text\": \"Second submission immediately after, should be blocked.\", \"creator_id\": \"interval-test-user\"}" -w "\nStatus: %{http_code}\n"
```

Observed output:

```json
// first request
{ "attribution": "uncertain", "confidence": 0.5283, "content_id": "...", "label": "...", "signal_scores": { "llm_score": 0.7, "stylo_score": 0.2708 } }
Status: 200

// second request, same creator_id, immediately after
{ "error": "Too many submissions for creator_id 'interval-test-user'. Please wait at least 20 seconds between submissions." }
Status: 429
```

---

## Audit Log

Every call to `POST /submit` writes a structured JSON entry to `audit_log.json` (via `GET /log`) capturing: `timestamp`, `content_id`, `creator_id`, `attribution`, `confidence` (the combined score), both individual signal scores (`llm_score`, `stylo_score`), which combination path produced the score (`confidence_basis`: `"combined"` or `"stylo_only_fallback"`), `status`, and an explicit `appeal_filed` boolean.

When an appeal is filed against a `content_id`, two things happen in the log: the original entry's `status` flips to `"under_review"` and its `appeal_filed` flips to `true`, and a new appeal entry is appended containing `appeal_reasoning` plus an `original_decision` snapshot (attribution, confidence, both signal scores, original timestamp) — so a reviewer sees the original decision and the appeal side by side without re-running the pipeline.

### Example entries (from `GET /log`)

```json
{
  "content_id": "2ed2be6d-b725-4940-8839-d6171e91c808",
  "creator_id": "user-1",
  "timestamp": "2026-07-03T20:28:21.424234+00:00",
  "attribution": "likely_ai",
  "confidence": 0.72,
  "llm_score": 0.92,
  "stylo_score": 0.4721,
  "confidence_basis": "combined",
  "status": "classified",
  "appeal_filed": false
}
```

```json
{
  "content_id": "e14dc48e-1bc0-4950-8a78-1d8adc7cd3ce",
  "creator_id": "user-2",
  "timestamp": "2026-07-03T20:28:22.006445+00:00",
  "attribution": "likely_human",
  "confidence": 0.167,
  "llm_score": 0.05,
  "stylo_score": 0.3424,
  "confidence_basis": "combined",
  "status": "classified",
  "appeal_filed": false
}
```

The next pair shows a submission that was later appealed — note `appeal_filed` and `status` on the original entry, and the linked appeal entry right after it:

```json
{
  "content_id": "ded10a83-0748-463c-9d88-e4a2a6a544a6",
  "creator_id": "user-3",
  "timestamp": "2026-07-03T20:28:22.778838+00:00",
  "attribution": "uncertain",
  "confidence": 0.7192,
  "llm_score": 0.8,
  "stylo_score": 0.598,
  "confidence_basis": "combined",
  "status": "under_review",
  "appeal_filed": true
}
```

```json
{
  "content_id": "ded10a83-0748-463c-9d88-e4a2a6a544a6",
  "creator_id": "user-3",
  "timestamp": "2026-07-03T20:28:23.175417+00:00",
  "appeal_reasoning": "I wrote this myself. I am a non-native English speaker and my writing tends to read as more formal.",
  "status": "under_review",
  "original_decision": {
    "attribution": "uncertain",
    "confidence": 0.7192,
    "llm_score": 0.8,
    "stylo_score": 0.598,
    "timestamp": "2026-07-03T20:28:22.778838+00:00"
  }
}
```

### Verifying the log

```bash
curl -s http://localhost:5000/log | python -m json.tool
```
