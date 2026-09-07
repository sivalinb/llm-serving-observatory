terraform {
  required_version = ">= 1.6.0"
  required_providers {
    oci = { source = "oracle/oci", version = "~> 6.0" }
  }
}
provider "oci" {
  region = var.region
}
resource "oci_core_vcn" "lab" {
  compartment_id = var.compartment_id
  display_name   = "serving-observatory"
  cidr_blocks    = ["10.42.0.0/16"]
  dns_label      = "observatory"
}
resource "oci_core_internet_gateway" "lab" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.lab.id
  display_name   = "observatory-internet"
  enabled        = true
}
resource "oci_core_route_table" "lab" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.lab.id
  route_rules {
    network_entity_id = oci_core_internet_gateway.lab.id
    destination       = "0.0.0.0/0"
  }
}
resource "oci_core_security_list" "lab" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.lab.id
  ingress_security_rules {
    protocol = "6"
    source   = var.admin_cidr
    tcp_options {
      min = 22
      max = 22
    }
  }
  dynamic "ingress_security_rules" {
    for_each = var.public_https ? [80, 443] : []
    content {
      protocol = "6"
      source   = "0.0.0.0/0"
      tcp_options {
        min = ingress_security_rules.value
        max = ingress_security_rules.value
      }
    }
  }
  ingress_security_rules {
    protocol = "1"
    source   = "0.0.0.0/0"
    icmp_options {
      type = 3
      code = 4
    }
  }
  egress_security_rules {
    protocol    = "all"
    destination = "0.0.0.0/0"
  }
}
resource "oci_core_subnet" "lab" {
  compartment_id    = var.compartment_id
  vcn_id            = oci_core_vcn.lab.id
  cidr_block        = "10.42.1.0/24"
  route_table_id    = oci_core_route_table.lab.id
  security_list_ids = [oci_core_security_list.lab.id]
  dns_label         = "lab"
}
resource "oci_core_instance" "lab" {
  compartment_id      = var.compartment_id
  availability_domain = var.availability_domain
  display_name        = "llm-serving-observatory"
  shape               = "VM.Standard.A1.Flex"
  shape_config {
    ocpus         = 2
    memory_in_gbs = 12
  }
  source_details {
    source_type             = "image"
    source_id               = var.ubuntu_arm_image_id
    boot_volume_size_in_gbs = 50
  }
  create_vnic_details {
    subnet_id        = oci_core_subnet.lab.id
    assign_public_ip = true
    hostname_label   = "observatory"
  }
  metadata = {
    ssh_authorized_keys = var.ssh_public_key
    user_data           = base64encode(file("${path.module}/cloud-init.yaml"))
  }
  freeform_tags = { project = "llm-serving-observatory", environment = "learning" }
}
data "oci_objectstorage_namespace" "account" {
  compartment_id = var.compartment_id
}
resource "oci_objectstorage_bucket" "reports" {
  compartment_id = var.compartment_id
  namespace      = data.oci_objectstorage_namespace.account.namespace
  name           = var.bucket_name
  access_type    = "NoPublicAccess"
  storage_tier   = "Standard"
}
resource "oci_budget_budget" "lab" {
  count          = var.create_budget ? 1 : 0
  compartment_id = var.tenancy_id
  amount         = var.monthly_budget
  reset_period   = "MONTHLY"
  target_type    = "COMPARTMENT"
  targets        = [var.compartment_id]
  display_name   = "observatory-budget"
}
resource "oci_budget_alert_rule" "lab" {
  count          = var.create_budget ? 1 : 0
  budget_id      = oci_budget_budget.lab[0].id
  type           = "ACTUAL"
  threshold      = 80
  threshold_type = "PERCENTAGE"
  recipients     = var.budget_email
  description    = "Observatory budget threshold; advisory, not a spending cap."
}
