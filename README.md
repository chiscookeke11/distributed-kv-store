# Distributed Key-Value Store

A small Flask-based distributed key-value store that demonstrates the CAP theorem trade-off between **consistency and partition tolerance (CP)** and **availability and partition tolerance (AP)**. The project runs three cooperating nodes with Docker Compose, replicates writes between peers, and resolves conflicts with a last-write-wins timestamp strategy.

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Consistency Modes](#consistency-modes)
- [Project Structure](#project-structure)
- [Requirements](#requirements)
- [Quick Start](#quick-start)
- [API Reference](#api-reference)
- [Usage Examples](#usage-examples)
- [Testing CAP Behavior](#testing-cap-behavior)
- [Configuration](#configuration)
- [Data Model](#data-model)
- [Conflict Resolution](#conflict-resolution)
- [Operational Notes](#operational-notes)
- [Troubleshooting](#troubleshooting)
- [Limitations and Future Improvements](#limitations-and-future-improvements)

## Overview

This repository contains a minimal distributed in-memory key-value service. Each node exposes the same HTTP API and knows about its peers through environment variables. A write submitted to any node is replicated to the other nodes, while reads can be performed against any node.

The application is intended for learning and experimentation. It is useful for observing how distributed systems behave when peers are reachable, unavailable, or recovering after a partition.

Key capabilities:

- Store arbitrary JSON-compatible values under string keys.
- Replicate writes across multiple Flask nodes.
- Switch each node between CP and AP behavior at runtime.
- Synchronize a recovered node with peers.
- Run a three-node local cluster using Docker Compose.

## Architecture

The default Docker Compose setup starts three containers on a shared bridge network:

| Node | Container | Host URL | Internal peer address | Default mode |
| --- | --- | --- | --- | --- |
| Node 1 | `node1` | `http://localhost:5001` | `node1:5000` | `CP` |
| Node 2 | `node2` | `http://localhost:5002` | `node2:5000` | `CP` |
| Node 3 | `node3` | `http://localhost:5003` | `node3:5000` | `CP` |

Each node runs the same Flask application from `app.py`. The node identity, peer list, and startup mode are supplied through environment variables in `docker-compose.yml`.

```text
          Host machine

  localhost:5001      localhost:5002      localhost:5003
       |                   |                   |
       v                   v                   v
  +---------+         +---------+         +---------+
  | node1   | <-----> | node2   | <-----> | node3   |
  | Flask   |         | Flask   |         | Flask   |
  | store{} | <-----> | store{} | <-----> | store{} |
  +---------+         +---------+         +---------+
        \_____________________________________/
                  Docker bridge network
```

Replication is performed over HTTP by calling each peer's `/replicate` endpoint.

## Consistency Modes

The service supports two runtime modes: `CP` and `AP`.

### CP Mode

In CP mode, the node prioritizes consistency. A write is accepted only if the receiving node can replicate the update to **all configured peers** first.

Behavior:

1. Client sends `PUT /data/<key>` to a node.
2. The node sends the update to every peer using `POST /replicate`.
3. If every peer confirms the write, the node writes the value locally and returns success.
4. If any peer is unreachable or returns an error, the write is rejected with HTTP `503`.

This means CP mode can refuse writes during a peer failure or network partition so that the cluster avoids divergent state.

### AP Mode

In AP mode, the node prioritizes availability. A write is accepted locally even if some peers are unavailable.

Behavior:

1. Client sends `PUT /data/<key>` to a node.
2. The node writes the value locally immediately.
3. The node attempts best-effort replication to each peer.
4. The response includes per-peer replication results.

This means AP mode keeps accepting writes during peer failures, but nodes may temporarily hold different values until synchronization occurs.

## Project Structure

```text
.
├── app.py              # Flask application and distributed key-value logic
├── docker-compose.yml  # Three-node local cluster definition
├── Dockerfile          # Python container image definition
├── requirements.txt    # Python dependencies
└── README.md           # Project documentation
```

## Requirements

For the recommended Docker workflow:

- Docker
- Docker Compose v2 (`docker compose`)
- `curl` or another HTTP client

For running a single node directly on your machine:

- Python 3.12 or compatible Python 3 version
- `pip`

## Quick Start

### 1. Start the cluster

```bash
docker compose up --build
```

The first startup builds the Python image and starts all three nodes.

### 2. Verify the nodes are running

Open a second terminal and query each node:

```bash
curl http://localhost:5001/data
curl http://localhost:5002/data
curl http://localhost:5003/data
```

Each response should include the node name, mode, and current in-memory store.

### 3. Write a key

```bash
curl -X PUT http://localhost:5001/data/message \
  -H 'Content-Type: application/json' \
  -d '{"value":"hello distributed world"}'
```

### 4. Read the key from all nodes

```bash
curl http://localhost:5001/data/message
curl http://localhost:5002/data/message
curl http://localhost:5003/data/message
```

If replication succeeds, each node returns the same value.

### 5. Stop the cluster

```bash
docker compose down
```

## API Reference

### Get all data

```http
GET /data
```

Returns the full local store for the node receiving the request.

Example response:

```json
{
  "node": "node1",
  "mode": "CP",
  "store": {
    "message": {
      "value": "hello distributed world",
      "timestamp": 1788012345.123
    }
  }
}
```

### Get one key

```http
GET /data/<key>
```

Returns one key from the node's local store.

Successful response:

```json
{
  "node": "node1",
  "key": "message",
  "value": "hello distributed world",
  "timestamp": 1788012345.123
}
```

Missing key response:

```json
{
  "error": "Key not found"
}
```

### Write one key

```http
PUT /data/<key>
Content-Type: application/json

{
  "value": "any JSON-compatible value"
}
```

Writes a value to the receiving node and attempts replication according to the node's current mode.

CP success response:

```json
{
  "status": "ok",
  "node": "node1",
  "key": "message",
  "value": "hello distributed world",
  "timestamp": 1788012345.123,
  "mode": "CP",
  "message": "All nodes consistent"
}
```

CP failure response when a peer is unavailable:

```json
{
  "error": "Could not reach node2:5000",
  "reason": "Write rejected to maintain consistency (CP mode)"
}
```

AP success response:

```json
{
  "status": "ok",
  "node": "node1",
  "key": "message",
  "value": "hello distributed world",
  "timestamp": 1788012345.123,
  "mode": "AP",
  "replication": [
    {
      "peer": "node2:5000",
      "status": "replicated"
    },
    {
      "peer": "node3:5000",
      "status": "unreachable"
    }
  ]
}
```

### Replicate a key

```http
POST /replicate
Content-Type: application/json

{
  "key": "message",
  "value": "hello distributed world",
  "timestamp": 1788012345.123
}
```

This endpoint is used internally by peer nodes. It accepts a replicated update if the incoming timestamp is newer than or equal to the local timestamp for the same key.

### Synchronize from peers

```http
POST /sync
```

Fetches all peer stores and merges newer values into the local node using last-write-wins conflict resolution.

Example:

```bash
curl -X POST http://localhost:5002/sync
```

Example response:

```json
{
  "status": "ok",
  "node": "node2",
  "merged_keys": 1,
  "store": {
    "message": {
      "value": "hello distributed world",
      "timestamp": 1788012345.123
    }
  }
}
```

### Get current mode

```http
GET /mode
```

Returns the current mode for the node receiving the request.

Example:

```json
{
  "node": "node1",
  "mode": "CP"
}
```

### Set current mode

```http
POST /mode
Content-Type: application/json

{
  "mode": "AP"
}
```

Valid mode values are `CP` and `AP`. The value is normalized to uppercase.

Example:

```bash
curl -X POST http://localhost:5001/mode \
  -H 'Content-Type: application/json' \
  -d '{"mode":"AP"}'
```

## Usage Examples

### Store a string

```bash
curl -X PUT http://localhost:5001/data/greeting \
  -H 'Content-Type: application/json' \
  -d '{"value":"hello"}'
```

### Store an object

```bash
curl -X PUT http://localhost:5001/data/user:42 \
  -H 'Content-Type: application/json' \
  -d '{"value":{"name":"Ada","role":"admin"}}'
```

### Read the whole store from node 3

```bash
curl http://localhost:5003/data
```

### Switch all nodes to AP mode

```bash
for port in 5001 5002 5003; do
  curl -X POST "http://localhost:${port}/mode" \
    -H 'Content-Type: application/json' \
    -d '{"mode":"AP"}'
done
```

### Switch all nodes back to CP mode

```bash
for port in 5001 5002 5003; do
  curl -X POST "http://localhost:${port}/mode" \
    -H 'Content-Type: application/json' \
    -d '{"mode":"CP"}'
done
```

## Testing CAP Behavior

The following scenarios can be used to observe the difference between CP and AP behavior.

### Scenario 1: CP mode rejects writes when a peer is unavailable

Start the cluster:

```bash
docker compose up --build
```

Stop one peer:

```bash
docker stop node2
```

Attempt a write through node 1:

```bash
curl -i -X PUT http://localhost:5001/data/cp-test \
  -H 'Content-Type: application/json' \
  -d '{"value":"should be rejected"}'
```

Expected result: node 1 returns HTTP `503` because it cannot replicate to every configured peer.

Restart node 2:

```bash
docker start node2
```

### Scenario 2: AP mode accepts writes when a peer is unavailable

Switch node 1 to AP mode:

```bash
curl -X POST http://localhost:5001/mode \
  -H 'Content-Type: application/json' \
  -d '{"mode":"AP"}'
```

Stop one peer:

```bash
docker stop node2
```

Write through node 1:

```bash
curl -X PUT http://localhost:5001/data/ap-test \
  -H 'Content-Type: application/json' \
  -d '{"value":"accepted locally"}'
```

Expected result: node 1 returns success and reports node 2 as unreachable in the replication results.

Restart node 2:

```bash
docker start node2
```

Synchronize node 2 after it comes back:

```bash
curl -X POST http://localhost:5002/sync
```

Read the key from node 2:

```bash
curl http://localhost:5002/data/ap-test
```

## Configuration

The application reads these environment variables at startup:

| Variable | Default | Description |
| --- | --- | --- |
| `NODE_NAME` | `node1` | Human-readable node name returned in API responses. |
| `PEERS` | empty | Comma-separated list of peer hostnames and ports, such as `node2:5000,node3:5000`. |
| `MODE` | `CP` | Initial consistency mode. Supported values are `CP` and `AP`. |
| `PORT` | `5000` | Flask port inside the container or local process. |

When using Docker Compose, these values are already configured for the three-node cluster.

## Running Without Docker

You can run a single local node directly for API exploration:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
PORT=5000 NODE_NAME=node1 MODE=AP python app.py
```

For a multi-node non-Docker setup, start multiple processes on different ports and configure `PEERS` to point at the other local processes.

Example node 1:

```bash
PORT=5001 NODE_NAME=node1 PEERS=localhost:5002,localhost:5003 MODE=CP python app.py
```

Example node 2:

```bash
PORT=5002 NODE_NAME=node2 PEERS=localhost:5001,localhost:5003 MODE=CP python app.py
```

Example node 3:

```bash
PORT=5003 NODE_NAME=node3 PEERS=localhost:5001,localhost:5002 MODE=CP python app.py
```

## Data Model

The in-memory store is a Python dictionary. Every key maps to an object with two fields:

```json
{
  "value": "stored value",
  "timestamp": 1788012345.123
}
```

- `value` contains the client-provided JSON value from the write request.
- `timestamp` is generated by the receiving node with `time.time()` and is used for conflict resolution.

All data is stored in memory only. Restarting a container clears that node's local store.

## Conflict Resolution

The project uses last-write-wins conflict resolution:

- Incoming replicated values are accepted when their timestamp is newer than or equal to the local value's timestamp.
- Synchronization merges peer stores and keeps the newest timestamp for each key.
- Clock differences between nodes can affect which value wins because timestamps come from each node's local system clock.

## Operational Notes

- The Flask development server is used for simplicity and demonstration. It is not intended as a production WSGI server.
- CP writes use a two-second timeout per peer.
- AP replication uses a one-second timeout per peer.
- Runtime mode changes are process-local. Changing node 1 to AP does not automatically change node 2 or node 3.
- The `/sync` endpoint pulls state into the node receiving the request; it does not push that node's state to peers.

## Troubleshooting

### `docker compose up` fails because ports are already in use

Another process may already be bound to `5001`, `5002`, or `5003`. Stop the conflicting process or edit `docker-compose.yml` to use different host ports.

### A CP write returns `503`

This is expected if any configured peer is unavailable or returns a non-`200` response. Check container health and logs:

```bash
docker ps
docker logs node1
docker logs node2
docker logs node3
```

### A restarted node is missing data

Data is in memory and is lost when a node process restarts. If peers still have the data, call `/sync` on the restarted node:

```bash
curl -X POST http://localhost:5002/sync
```

### Nodes show different values

This can happen in AP mode or after a node outage. Use `/sync` on the stale node, then read the key again.

## Limitations and Future Improvements

This project intentionally keeps the implementation small. Potential improvements include:

- Persistent storage so data survives restarts.
- Health checks and automatic peer discovery.
- Background anti-entropy synchronization.
- Vector clocks or version vectors instead of wall-clock timestamps.
- Authentication and authorization for HTTP endpoints.
- Request validation for malformed or missing JSON payloads.
- Unit and integration tests.
- Production-ready serving with a WSGI server such as Gunicorn.

## License

No license file is currently included. Add a license before using this project in a public or production context.
