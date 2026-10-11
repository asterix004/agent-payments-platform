{{- define "payments.labels" -}}
app.kubernetes.io/name: payments
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "payments.selector" -}}
app.kubernetes.io/name: payments
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "payments.image" -}}
{{- if .Values.image.digest -}}
{{ .Values.image.repository }}@{{ .Values.image.digest }}
{{- else -}}
{{ .Values.image.repository }}:{{ .Values.image.tag }}
{{- end -}}
{{- end -}}
