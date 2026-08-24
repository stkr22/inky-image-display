# Heap profiling

Both long-running services can trace their own allocations on demand. This
exists because RSS in the API and the sync worker climbs in **steps that line
up with sync batches**, never falling back — the signature of retention, not
of allocator fragmentation. Answering "what is retained" needs a diff across
one batch, which is what the tooling here produces.

Everything is off by default. `tracemalloc` keeps a traceback for every live
allocation, so it costs memory on containers that already run close to their
limit — see [Overhead](#overhead) before enabling it in production.

## API

Set `API_PROFILE_HEAP=true` (optionally `API_PROFILE_HEAP_FRAMES`, default
15). Tracing starts before the app allocates anything, and a baseline is
captured at that point.

Two routes appear under `/api/debug`. They sit inside `/api/`, so the standard
policy applies — an admin session or the sync token. With profiling off they
return **404**, not 403: when auth is unconfigured (trusted-LAN mode) the env
flag is the only gate, and an absent route is the safer answer.

| Route | Purpose |
| --- | --- |
| `GET /api/debug/heap` | Retained allocations since the baseline, largest first |
| `POST /api/debug/heap/baseline` | Move the comparison point to now |

Query parameters on `GET`:

- `top` (default 25, max 200) — how many entries to return.
- `gc_census` (default false) — adds a count of live gc-tracked objects by
  type. It walks the whole heap, so it pauses the process in proportion to
  heap size. It is also blind to `bytes`/`bytearray` buffers, which the
  collector does not track; read it alongside the tracemalloc entries, never
  instead of them.

### Bracketing one batch

The useful measurement isolates a single batch:

```bash
# 1. Reset the comparison point, then let exactly one sync batch run.
curl -sf -H "x-api-key: $SYNC_TOKEN" -X POST \
  https://inky-display-api.example.com/api/debug/heap/baseline

# 2. After the batch, ask what survived it.
curl -sf -H "x-api-key: $SYNC_TOKEN" \
  'https://inky-display-api.example.com/api/debug/heap?top=40' > heap.json
```

Each entry carries `size_diff_bytes` (growth against the baseline) and the
`traceback` that allocated it. A leak shows as a large positive `size_diff_bytes`
against a stable traceback that repeats every batch.

## Sync worker

The worker has no HTTP surface, so it logs instead. Set `WORKER_PROFILE_HEAP=true`
(plus `WORKER_PROFILE_HEAP_FRAMES`, default 15, and `WORKER_PROFILE_HEAP_TOP`,
default 10).

The report is written **after every claim cycle**, because a cycle — not
wall-clock time — is the unit RSS grows in; a timer-based dump would smear the
step across batches. The baseline stays at process start, so each report shows
cumulative growth and a leak reads as the same traceback climbing cycle after
cycle.

```
heap: rss=612.4MiB traced=488.1MiB peak=501.7MiB baseline=True
heap: +48.20MiB (+1240 blocks)
    File ".../immich/sync_service.py", line 118
      ...
```

## Kubernetes

Both flags go through the chart's existing `extraEnv` — no chart change:

```yaml
api:
  extraEnv:
    - name: API_PROFILE_HEAP
      value: "true"
  resources:
    limits:
      memory: 2Gi   # headroom for the run; see Overhead

sync:
  extraEnv:
    - name: WORKER_PROFILE_HEAP
      value: "true"
  resources:
    limits:
      memory: 2Gi
```

Enabling the flag restarts the pod, which resets RSS — the first batch after
the restart is the one to measure.

## Overhead

`tracemalloc` stores a traceback per live allocation, so the cost scales with
allocation *count* and with the frame depth. Expect tens of MiB on these
services at the default 15 frames.

That matters because the containers default to a 1Gi limit and the leak already
pushes them into it. **Raise the memory limit for the duration of the profiling
run.** Profiling into an OOM kill loses the report and tells you nothing you
did not already know. Drop `*_PROFILE_HEAP_FRAMES` to 5 if headroom is tight —
5 frames still crosses the `asyncio.to_thread` hop in the image-processing
path, though it may stop short of the request handler.

Turn the flag back off, and restore the limit, once the run is done.
