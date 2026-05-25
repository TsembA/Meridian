{{/*
_helpers.tpl — Template helper functions for the nexus-app Helm chart.
These are reusable named templates included via `include` in other templates.
*/}}

{{/* Expand the name of the chart */}}
{{- define "nexus-app.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
Truncate at 63 chars — Kubernetes DNS label limit.
*/}}
{{- define "nexus-app.fullname" -}}
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

{{/* Create chart name and version as used by the chart label */}}
{{- define "nexus-app.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels — applied to every resource for consistent filtering in kubectl and Prometheus.
*/}}
{{- define "nexus-app.labels" -}}
helm.sh/chart: {{ include "nexus-app.chart" . }}
{{ include "nexus-app.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: meridian-platform
{{- end }}

{{/*
Selector labels — used in Deployment.spec.selector and Service.spec.selector.
Must be stable across chart upgrades — do not add volatile labels here.
*/}}
{{- define "nexus-app.selectorLabels" -}}
app.kubernetes.io/name: {{ include "nexus-app.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/* Service account name resolution */}}
{{- define "nexus-app.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "nexus-app.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "meridian-app" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Image reference — uses digest when set (production), tag otherwise (dev).
Digest pins the exact image layer; tags are mutable and should never be used alone in prod.
*/}}
{{- define "nexus-app.image" -}}
{{- if .Values.image.digest }}
{{- printf "%s@%s" .Values.image.repository .Values.image.digest }}
{{- else }}
{{- printf "%s:%s" .Values.image.repository .Values.image.tag }}
{{- end }}
{{- end }}
