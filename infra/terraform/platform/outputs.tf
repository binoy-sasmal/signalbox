output "node_public_ip" {
  description = "Public address of the node. Gate 2's verification SSHes to this."
  value       = oci_core_instance.node.public_ip
}

output "ssh_command" {
  description = "The exact command Gate 2 is verified with."
  value       = "ssh ubuntu@${oci_core_instance.node.public_ip}"
}

output "block_volume_id" {
  description = "OCID of the data volume. Gate 3 mounts it; recorded so that step is not guesswork."
  value       = oci_core_volume.data.id
}
