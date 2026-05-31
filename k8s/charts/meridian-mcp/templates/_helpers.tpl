{{/*
_helpers.tpl — Template helper functions for the meridian-mcp Helm chart.
*/}}

{{- define "meridian-mcp.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "meridian-mcp.fullname" -}}
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

{{- define "meridian-mcp.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "meridian-mcp.labels" -}}
helm.sh/chart: {{ include "meridian-mcp.chart" . }}
{{ include "meridian-mcp.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: meridian-platform
{{- end }}

{{- define "meridian-mcp.selectorLabels" -}}
app.kubernetes.io/name: {{ include "meridian-mcp.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "meridian-mcp.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "meridian-mcp.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "meridian-mcp" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "meridian-mcp.image" -}}
{{- if .Values.image.digest }}
{{- printf "%s@%s" .Values.image.repository .Values.image.digest }}
{{- else }}
{{- printf "%s:%s" .Values.image.repository .Values.image.tag }}
{{- end }}
{{- end }}
