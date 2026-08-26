# inky-image-display Helm chart

Deploys the API (which serves the operator UI and `/media` proxy), the
persistent volume for its SQLite database, an Ingress, and one long-running
sync worker Deployment. Per-job cadence is a cron schedule set in the web
UI; the API wakes the worker over MQTT when jobs are due (with a slow
safety poll as fallback), so there are no CronJob schedules to tune.

The chart is published on every GitHub release, version-locked to the
container images built from the same tag:

```bash
helm install inky-image-display \
  oci://ghcr.io/stkr22/charts/inky-image-display \
  --namespace inky-image-display \
  --values my-values.yaml
```

## Secrets

The chart creates no Secrets — create them separately in the release
namespace and point `existingSecrets.*` at their names:

| Value | Keys | Needed for |
|-------|------|------------|
| `existingSecrets.s3Writer` | `access-key-id`, `secret-access-key` | always |
| `existingSecrets.s3Reader` | `access-key-id`, `secret-access-key` | always |
| `existingSecrets.immich` | `apiKey` | Immich sync + browse proxy |
| `existingSecrets.gemini` | `gemini-api-key` | GenAI generation, display jobs (MOTD), gemini sync |

The Gemini reference is `optional: true` on the API deployment: without the
Secret the GenAI/display-job endpoints return 503 and everything else works.

## Example values

```yaml
config:
  s3:
    endpoint: s3.example.com
    secure: true
  mqtt:
    host: mosquitto.mqtt.svc.cluster.local
  # Broker address handed to the display controllers — usually the public
  # one, e.g. MQTT-over-websockets through an HTTPS ingress.
  deviceMqtt:
    host: mqtt.example.com
    port: 443
    tls: true
    transport: websockets
  immich:
    baseUrl: https://immich.example.com
  # Calibre-Web serving the OPDS catalogue for the bookshelf source. Only the
  # sync worker calls it, so the in-cluster service address is usually right.
  calibre:
    baseUrl: http://calibre-web.calibre-web.svc.cluster.local

existingSecrets:
  s3Writer: my-s3-writer
  s3Reader: my-s3-reader
  immich: my-immich-credentials
  gemini: my-gemini-credentials

ingress:
  hosts:
    - inky-display.example.com

# Gateway API instead of (or alongside) the Ingress. hostnames defaults to
# ingress.hosts, so a migration does not mean retyping them.
httpRoute:
  enabled: true
  parentRefs:
    - name: home
      namespace: cilium-gateway
      sectionName: https

sync:
  gemini:
    enabled: true   # billed per generated image — opt-in
  calibre:
    enabled: true   # bookshelf images; needs config.calibre.baseUrl + the Gemini secret
```

## Notes

- The API must stay a singleton (SQLite on RWO storage, in-process
  scheduler); the chart pins `replicas: 1` with a `Recreate` strategy.
- The PVC carries `helm.sh/resource-policy: keep`, so `helm uninstall`
  leaves the database intact. Reuse it later via
  `persistence.existingClaim`.
- The sync worker reaches the API through the in-cluster service by default;
  set `sync.apiBaseUrl` to route through the ingress instead (e.g. when
  network policies restrict pod-to-pod traffic).
- Pods run as the image's non-root user (uid/gid 1001); `fsGroup` keeps
  volume data writable if it was created under a different uid.
- `ingress` and `httpRoute` are independent: enable both during a migration
  to Gateway API, then turn the Ingress off. Both route every hostname's `/`
  to the API service, which serves the SPA, `/api/*` and `/media/*`.
- The bookshelf source pages the whole Calibre library in and caches it for
  `sync.calibre.cacheTtlSeconds` (6h), so a newly added book can take that
  long to become eligible.
