{{/*
Expand the name of the chart.
*/}}
{{- define "inky-image-display.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name, truncated at 63 chars because of
Kubernetes name limits.
*/}}
{{- define "inky-image-display.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Common labels.
*/}}
{{- define "inky-image-display.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Per-component selector labels. Usage:
  {{ include "inky-image-display.selectorLabels" (dict "ctx" . "component" "api") }}
*/}}
{{- define "inky-image-display.selectorLabels" -}}
app.kubernetes.io/name: {{ include "inky-image-display.name" .ctx }}-{{ .component }}
app.kubernetes.io/instance: {{ .ctx.Release.Name }}
{{- end }}

{{/*
Image references — tag falls back to the chart appVersion, which the release
workflow pins to the release tag.
*/}}
{{- define "inky-image-display.apiImage" -}}
{{ .Values.api.image.repository }}:{{ .Values.api.image.tag | default .Chart.AppVersion }}
{{- end }}

{{- define "inky-image-display.syncImage" -}}
{{ .Values.sync.image.repository }}:{{ .Values.sync.image.tag | default .Chart.AppVersion }}
{{- end }}

{{/*
Base URL the sync worker uses to reach the API.
*/}}
{{- define "inky-image-display.syncApiBaseUrl" -}}
{{- if .Values.sync.apiBaseUrl }}
{{- .Values.sync.apiBaseUrl }}
{{- else }}
{{- printf "http://%s-api:%v" (include "inky-image-display.fullname" .) .Values.service.port }}
{{- end }}
{{- end }}

{{/*
S3 writer environment for the sync worker container.
*/}}
{{- define "inky-image-display.syncS3Env" -}}
- name: S3_WRITER_ENDPOINT
  value: {{ required "config.s3.endpoint is required" .Values.config.s3.endpoint | quote }}
- name: S3_WRITER_BUCKET
  value: {{ .Values.config.s3.bucket | quote }}
- name: S3_WRITER_SECURE
  value: {{ .Values.config.s3.secure | quote }}
{{- with .Values.config.s3.region }}
- name: S3_WRITER_REGION
  value: {{ . | quote }}
{{- end }}
- name: S3_WRITER_ACCESS_KEY
  valueFrom:
    secretKeyRef:
      name: {{ required "existingSecrets.s3Writer is required" .Values.existingSecrets.s3Writer }}
      key: access-key-id
- name: S3_WRITER_SECRET_KEY
  valueFrom:
    secretKeyRef:
      name: {{ required "existingSecrets.s3Writer is required" .Values.existingSecrets.s3Writer }}
      key: secret-access-key
{{- end }}

{{/*
Machine token the sync worker presents to the API (x-api-key). Optional in
the Secret: without it the jobs run unauthenticated, which only works while
OIDC auth is disabled on the API.
*/}}
{{- define "inky-image-display.syncApiTokenEnv" -}}
{{- if .Values.existingSecrets.auth }}
- name: DISPLAY_API_TOKEN
  valueFrom:
    secretKeyRef:
      name: {{ .Values.existingSecrets.auth }}
      key: sync-token
      optional: true
{{- end }}
{{- end }}
