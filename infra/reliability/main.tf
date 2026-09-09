terraform {
  required_version = ">= 1.5.7, < 2.0.0"
  required_providers {
    oci = { source = "oracle/oci", version = "= 6.37.0" }
  }
}

provider "oci" { region = "us-phoenix-1" }

variable "tenancy_id" { type = string }
variable "existing_instance_id" {
  type = string
  validation {
    condition     = can(regex("^ocid1.instance.oc1.phx\\.", var.existing_instance_id))
    error_message = "Select the already-approved Phoenix instance."
  }
}
variable "bucket_suffix" {
  type = string
  validation {
    condition     = can(regex("^[a-z0-9-]{3,24}$", var.bucket_suffix))
    error_message = "Use a non-sensitive, 3–24 character lower-case suffix."
  }
}
variable "notification_email" {
  type      = string
  sensitive = true
  validation {
    condition     = can(regex("^[^@ ]+@[^@ ]+\\.[^@ ]+$", var.notification_email))
    error_message = "Supply the operator-confirmed notification address privately."
  }
}

locals {
  tags   = { project = "llm-serving-observatory", component = "reliability", environment = "learning" }
  bucket = "observatory-reliability-${var.bucket_suffix}"
}

resource "oci_identity_compartment" "lab" {
  compartment_id = var.tenancy_id
  name           = "observatory-reliability"
  description    = "Dedicated bounded reliability support; existing compute remains outside this stack"
  enable_delete  = false
  freeform_tags  = local.tags
  lifecycle { prevent_destroy = true }
}

data "oci_objectstorage_namespace" "account" { compartment_id = var.tenancy_id }

resource "oci_objectstorage_bucket" "backups" {
  compartment_id = oci_identity_compartment.lab.id
  namespace      = data.oci_objectstorage_namespace.account.namespace
  name           = local.bucket
  access_type    = "NoPublicAccess"
  storage_tier   = "Standard"
  versioning     = "Disabled"
  freeform_tags  = local.tags
  lifecycle { prevent_destroy = true }
}

# Seven-day expiry is part of the reviewed plan. The VM cannot delete objects.
# Retain historical Vault key versions for at least the full backup retention window.
resource "oci_objectstorage_object_lifecycle_policy" "backups" {
  depends_on = [oci_identity_policy.expiry]
  namespace  = data.oci_objectstorage_namespace.account.namespace
  bucket     = oci_objectstorage_bucket.backups.name
  rules {
    name        = "expire-learning-backups-after-seven-days"
    action      = "DELETE"
    is_enabled  = true
    time_amount = 7
    time_unit   = "DAYS"
    object_name_filter { inclusion_prefixes = ["backups/"] }
  }
}

# Oracle's lifecycle service needs its own delete permission. This is not a VM grant.
resource "oci_identity_policy" "expiry" {
  compartment_id = var.tenancy_id
  name           = "observatory-reliability-expiry"
  description    = "Phoenix Object Storage may expire only the dedicated learning backups"
  statements = [
    "Allow service objectstorage-us-phoenix-1 to manage object-family in compartment id ${oci_identity_compartment.lab.id} where any {request.permission='BUCKET_INSPECT', request.permission='BUCKET_READ', request.permission='OBJECT_INSPECT', request.permission='OBJECT_DELETE'}",
  ]
  freeform_tags = local.tags
}

resource "oci_kms_vault" "lab" {
  compartment_id = oci_identity_compartment.lab.id
  display_name   = "observatory-reliability"
  vault_type     = "DEFAULT" # Never VIRTUAL_PRIVATE (paid).
  freeform_tags  = local.tags
  lifecycle { prevent_destroy = true }
}

resource "oci_kms_key" "secrets" {
  compartment_id      = oci_identity_compartment.lab.id
  display_name        = "observatory-secret-encryption"
  management_endpoint = oci_kms_vault.lab.management_endpoint
  protection_mode     = "SOFTWARE"
  key_shape {
    algorithm = "AES"
    length    = 32
  }
  freeform_tags = local.tags
  lifecycle { prevent_destroy = true }
}

resource "oci_apm_apm_domain" "lab" {
  compartment_id = oci_identity_compartment.lab.id
  display_name   = "observatory-reliability"
  description    = "Sampled sanitized serving traces; explicitly Always Free"
  is_free_tier   = true
  freeform_tags  = local.tags
  lifecycle { prevent_destroy = true }
}

resource "oci_ons_notification_topic" "operator" {
  compartment_id = oci_identity_compartment.lab.id
  name           = "observatory-reliability"
  description    = "Private operator health and recovery notifications"
  freeform_tags  = local.tags
}

resource "oci_ons_subscription" "operator" {
  compartment_id = oci_identity_compartment.lab.id
  topic_id       = oci_ons_notification_topic.operator.id
  protocol       = "EMAIL"
  endpoint       = var.notification_email
  freeform_tags  = local.tags
}

resource "oci_identity_dynamic_group" "runner" {
  compartment_id = var.tenancy_id
  name           = "observatory-reliability-runner"
  description    = "Only the existing approved shared VM; not all instances in a compartment"
  matching_rule  = "instance.id = '${var.existing_instance_id}'"
  freeform_tags  = local.tags
}

resource "oci_identity_policy" "runner" {
  compartment_id = oci_identity_compartment.lab.id
  name           = "observatory-reliability-runner"
  description    = "Create/read backups; read dedicated secrets; publish own metric namespace"
  statements = [
    "Allow dynamic-group ${oci_identity_dynamic_group.runner.name} to manage objects in compartment id ${oci_identity_compartment.lab.id} where all {target.bucket.name='${local.bucket}', any {request.permission='OBJECT_CREATE', request.permission='OBJECT_READ', request.permission='OBJECT_INSPECT'}}",
    "Allow dynamic-group ${oci_identity_dynamic_group.runner.name} to read secret-bundles in compartment id ${oci_identity_compartment.lab.id}",
    "Allow dynamic-group ${oci_identity_dynamic_group.runner.name} to use metrics in compartment id ${oci_identity_compartment.lab.id} where target.metrics.namespace='observatory_reliability'",
  ]
  freeform_tags = local.tags
}

locals {
  alarms = {
    service_unhealthy = { query = "ServiceHealthy[5m]{service = \"servingops\", source = \"measured\"}.min() < 1", pending = "PT1M", severity = "CRITICAL", detail = "Gateway liveness failed. Inspect private health; do not restart unrelated services." }
    engine_scrape     = { query = "EngineScrapeHealthy[5m]{service = \"servingops\", source = \"measured\"}.min() < 1", pending = "PT1M", severity = "WARNING", detail = "Prometheus cannot confirm its model scrape. This is not an end-to-end model answer test." }
    backup_missing    = { query = "BackupVerified[5m]{service = \"servingops\", source = \"measured\"}.min() < 1", pending = "PT1M", severity = "CRITICAL", detail = "No locally recorded verified upload-and-restore exists. Check the backup worker and private storage." }
    backup_stale      = { query = "BackupAgeSeconds[5m]{service = \"servingops\", source = \"measured\"}.max() > 93600", pending = "PT1M", severity = "WARNING", detail = "Latest verified snapshot is older than 26 hours. This age is not a contractual RPO." }
    worker_missing    = { query = "ServiceHealthy[5m]{service = \"servingops\", source = \"measured\"}.absent()", pending = "PT10M", severity = "CRITICAL", detail = "Reliability heartbeat missing. Check the worker, VM and OCI export path; absent is not healthy." }
    safe_drill        = { query = "ReliabilityDrill[1m]{service = \"servingops\", source = \"drill\"}.max() > 0", pending = "PT1M", severity = "INFO", detail = "Labeled reliability exercise. No application outage or model request was injected." }
  }
}

resource "oci_monitoring_alarm" "lab" {
  for_each              = local.alarms
  compartment_id        = oci_identity_compartment.lab.id
  metric_compartment_id = oci_identity_compartment.lab.id
  display_name          = "observatory-${each.key}"
  namespace             = "observatory_reliability"
  query                 = each.value.query
  severity              = each.value.severity
  pending_duration      = each.value.pending
  is_enabled            = true
  destinations          = [oci_ons_notification_topic.operator.id]
  body                  = each.value.detail
  resolution            = "1m"
  message_format        = "PRETTY_JSON"
  freeform_tags         = local.tags
}

output "support" {
  value = {
    region          = "us-phoenix-1"
    compartment_id  = oci_identity_compartment.lab.id
    namespace       = data.oci_objectstorage_namespace.account.namespace
    bucket          = oci_objectstorage_bucket.backups.name
    vault_id        = oci_kms_vault.lab.id
    vault_key_id    = oci_kms_key.secrets.id
    apm_domain_id   = oci_apm_apm_domain.lab.id
    apm_endpoint    = oci_apm_apm_domain.lab.data_upload_endpoint
    topic_id        = oci_ons_notification_topic.operator.id
    subscription_id = oci_ons_subscription.operator.id
    alarm_ids       = { for name, alarm in oci_monitoring_alarm.lab : name => alarm.id }
  }
}
