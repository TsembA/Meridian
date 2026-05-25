{{/*
_helpers.tpl — Template helper functions for the nexus-mcp Helm chart.
*/}}

{{- define "nexus-mcp.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "nexus-mcp.fullname" -}}
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

{{- define "nexus-mcp.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "nexus-mcp.labels" -}}
helm.sh/chart: {{ include "nexus-mcp.chart" . }}
{{ include "nexus-mcp.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: meridian-platform
{{- end }}

{{- define "nexus-mcp.selectorLabels" -}}
app.kubernetes.io/name: {{ include "nexus-mcp.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "nexus-mcp.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "nexus-mcp.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "meridian-mcp" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "nexus-mcp.image" -}}
{{- if .Values.image.digest }}
{{- printf "%s@%s" .Values.image.repository .Values.image.digest }}
{{- else }}
{{- printf "%s:%s" .Values.image.repository .Values.image.tag }}
{{- end }}
{{- end }}
