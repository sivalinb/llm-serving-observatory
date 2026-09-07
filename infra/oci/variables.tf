variable "region" { type = string }
variable "compartment_id" { type = string }
variable "availability_domain" { type = string }
variable "ubuntu_arm_image_id" {
  type        = string
  description = "Region-specific official Ubuntu 24.04 ARM image OCID."
}
variable "ssh_public_key" { type = string }
variable "admin_cidr" {
  type = string
  validation {
    condition     = can(cidrhost(var.admin_cidr, 0)) && endswith(var.admin_cidr, "/32")
    error_message = "Use your single public IPv4 address with /32 for SSH."
  }
}
variable "public_https" {
  type    = bool
  default = false
}
variable "bucket_name" {
  type    = string
  default = "llm-serving-observatory-reports"
}
variable "create_budget" {
  type    = bool
  default = false
}
variable "tenancy_id" {
  type    = string
  default = ""
}
variable "monthly_budget" {
  type    = number
  default = 10
}
variable "budget_email" {
  type    = string
  default = ""
}
