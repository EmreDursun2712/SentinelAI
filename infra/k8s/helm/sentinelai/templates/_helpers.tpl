{{/* Common name/label helpers. */}}

{{- define "sentinelai.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "sentinelai.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name (include "sentinelai.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "sentinelai.labels" -}}
app.kubernetes.io/name: {{ include "sentinelai.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end -}}

{{- define "sentinelai.selectorLabels" -}}
app.kubernetes.io/name: {{ include "sentinelai.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/* Backend/worker image ref (shared image); tag falls back to AppVersion. */}}
{{- define "sentinelai.backendImage" -}}
{{- $tag := .Values.image.backend.tag | default .Chart.AppVersion -}}
{{- printf "%s:%s" .Values.image.backend.repository $tag -}}
{{- end -}}

{{- define "sentinelai.frontendImage" -}}
{{- $tag := .Values.image.frontend.tag | default .Chart.AppVersion -}}
{{- printf "%s:%s" .Values.image.frontend.repository $tag -}}
{{- end -}}

{{/* Name of the Secret to read env from (existing or chart-managed). */}}
{{- define "sentinelai.secretName" -}}
{{- if .Values.existingSecret -}}
{{- .Values.existingSecret -}}
{{- else -}}
{{- printf "%s-secrets" (include "sentinelai.fullname" .) -}}
{{- end -}}
{{- end -}}
