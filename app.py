import os
import time

from flask import Flask, request, jsonify
import requests as http_requests


app = Flask(__name__)


# In-memory key-value store with timestamps
# Format:
# {
#     "key": {
#         "value": "...",
#         "timestamp": 1234567890.123
#     }
# }
store = {}


# Configuration from environment
NODE_NAME = os.environ.get("NODE_NAME", "node1")
PEERS = [p for p in os.environ.get("PEERS", "").split(",") if p]
MODE = os.environ.get("MODE", "CP")


# ==========================================
# READ ENDPOINTS
# ==========================================

@app.route("/data", methods=["GET"])
def get_all_data():
    return jsonify({
        "node": NODE_NAME,
        "mode": MODE,
        "store": store
    })


@app.route("/data/<key>", methods=["GET"])
def get_data(key):
    if key in store:
        return jsonify({
            "node": NODE_NAME,
            "key": key,
            "value": store[key]["value"],
            "timestamp": store[key]["timestamp"]
        })

    return jsonify({
        "error": "Key not found"
    }), 404


# ==========================================
# WRITE ENDPOINT
# ==========================================

@app.route("/data/<key>", methods=["PUT"])
def put_data(key):
    global MODE

    value = request.json.get("value")
    timestamp = time.time()

    # ======================================
    # CP MODE
    # ======================================

    if MODE == "CP":

        # Replicate to ALL peers before confirming
        for peer in PEERS:
            try:
                resp = http_requests.post(
                    f"http://{peer}/replicate",
                    json={
                        "key": key,
                        "value": value,
                        "timestamp": timestamp
                    },
                    timeout=2
                )

                if resp.status_code != 200:
                    return jsonify({
                        "error": f"Replication to {peer} failed",
                        "reason": "Write rejected to maintain consistency (CP mode)"
                    }), 503

            except http_requests.exceptions.RequestException:
                return jsonify({
                    "error": f"Could not reach {peer}",
                    "reason": "Write rejected to maintain consistency (CP mode)"
                }), 503

        # Only write locally after all peers confirm
        store[key] = {
            "value": value,
            "timestamp": timestamp
        }

        return jsonify({
            "status": "ok",
            "node": NODE_NAME,
            "key": key,
            "value": value,
            "timestamp": timestamp,
            "mode": "CP",
            "message": "All nodes consistent"
        })


    # ======================================
    # AP MODE
    # ======================================

    else:

        # Write locally first
        store[key] = {
            "value": value,
            "timestamp": timestamp
        }

        replication_results = []

        # Try to replicate to peers
        for peer in PEERS:
            try:
                resp = http_requests.post(
                    f"http://{peer}/replicate",
                    json={
                        "key": key,
                        "value": value,
                        "timestamp": timestamp
                    },
                    timeout=1
                )

                if resp.status_code == 200:
                    replication_results.append({
                        "peer": peer,
                        "status": "replicated"
                    })
                else:
                    replication_results.append({
                        "peer": peer,
                        "status": "replication_failed"
                    })

            except http_requests.exceptions.RequestException:
                replication_results.append({
                    "peer": peer,
                    "status": "unreachable"
                })

        return jsonify({
            "status": "ok",
            "node": NODE_NAME,
            "key": key,
            "value": value,
            "timestamp": timestamp,
            "mode": "AP",
            "replication": replication_results
        })


# ==========================================
# REPLICATION ENDPOINT
# ==========================================

@app.route("/replicate", methods=["POST"])
def replicate():
    key = request.json.get("key")
    value = request.json.get("value")
    timestamp = request.json.get("timestamp", time.time())

    # Last-write-wins:
    # Only accept the incoming value if it is newer
    # than the version we already have.
    if key not in store or timestamp >= store[key]["timestamp"]:
        store[key] = {
            "value": value,
            "timestamp": timestamp
        }

    return jsonify({
        "status": "ok",
        "node": NODE_NAME
    })



# ====================
# sync endpoint
# ====================
@app.route("/sync", methods=["POST"])
def sync():
    """Fetch data from all peers and merge using last-write-wins."""
    merged_count = 0

    for peer in PEERS:
        try:
            resp = http_requests.get(f"http://{peer}/data", timeout=2)
            if resp.status_code == 200:
                peer_store = resp.json().get("store", {})
                for key, entry in peer_store.items():
                    peer_timestamp = entry["timestamp"]
                    if key not in store or peer_timestamp > store[key]["timestamp"]:
                        store[key] = entry
                        merged_count += 1
        except http_requests.exceptions.RequestException:
            continue

    return jsonify({
        "status": "ok",
        "node": NODE_NAME,
        "merged_keys": merged_count,
        "store": store,
    })


# ==========================================
# MODE ENDPOINTS
# ==========================================

@app.route("/mode", methods=["GET"])
def get_mode():
    return jsonify({
        "node": NODE_NAME,
        "mode": MODE
    })


@app.route("/mode", methods=["POST"])
def set_mode():
    global MODE

    new_mode = request.json.get("mode", "").upper()

    if new_mode in ("CP", "AP"):
        MODE = new_mode

        return jsonify({
            "status": "ok",
            "node": NODE_NAME,
            "mode": MODE
        })

    return jsonify({
        "error": "Mode must be CP or AP"
    }), 400


# ==========================================
# START SERVER
# ==========================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
