# NEXUS//AGENTIS API Examples

## 1. Launch a Research Run (`POST /runs`)
```bash
curl -s -X POST http://localhost:8000/runs \
  -H "Content-Type: application/json" \
  -d '{
    "question": "How do speculative decoding algorithms accelerate autoregressive LLM inference while preserving output distribution?",
    "token_budget": 32000,
    "max_loops": 3,
    "support_threshold": 0.75
  }' | jq .
```

## 2. Stream Live Events with Resumable `Last-Event-ID` (`GET /runs/{id}/events`)
```bash
curl -N http://localhost:8000/runs/run_10f85ec3fb51/events \
  -H "Last-Event-ID: 5"
```

## 3. Submit Human Gate Decision (`POST /runs/{id}/decision`)
```bash
# Approve and finalize
curl -s -X POST http://localhost:8000/runs/run_10f85ec3fb51/decision \
  -H "Content-Type: application/json" \
  -d '{"action": "approve"}' | jq .

# Request targeted revision loop
curl -s -X POST http://localhost:8000/runs/run_10f85ec3fb51/decision \
  -H "Content-Type: application/json" \
  -d '{
    "action": "revise",
    "feedback": "Add quantitative tail-latency benchmarks for 70B models."
  }' | jq .
```

## 4. Verify Tamper-Evident Ledger Chain (`GET /runs/{id}/ledger/verify`)
```bash
curl -s http://localhost:8000/runs/run_10f85ec3fb51/ledger/verify | jq .
```

## 5. Download Finalized Markdown Report (`GET /runs/{id}/report.md`)
```bash
curl -s http://localhost:8000/runs/run_10f85ec3fb51/report.md -o report.md
```
