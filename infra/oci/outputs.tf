output "public_ip" { value = oci_core_instance.lab.public_ip }
output "bucket_name" { value = oci_objectstorage_bucket.reports.name }
output "namespace" { value = data.oci_objectstorage_namespace.account.namespace }
output "ssh_tunnel" {
  value = "ssh -L 8000:127.0.0.1:8000 -L 3000:127.0.0.1:3000 ubuntu@${oci_core_instance.lab.public_ip}"
}
