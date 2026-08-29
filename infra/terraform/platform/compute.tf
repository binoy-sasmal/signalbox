data "oci_identity_availability_domains" "ads" {
  compartment_id = var.compartment_ocid
}

# 2 OCPU / 12 GB is not a choice, it is the entire Always Free allowance:
# 1,500 OCPU-hours / 730 = 2.05 and 9,000 GB-hours / 730 = 12.3. Anything
# larger leaves the free tier; anything smaller wastes it. Arithmetic in
# docs/metrics.md, re-verified against Oracle on 2026-08-29.
resource "oci_core_instance" "node" {
  compartment_id      = var.compartment_ocid
  availability_domain = data.oci_identity_availability_domains.ads.availability_domains[var.availability_domain_index].name
  display_name        = "signalbox-node"
  shape               = "VM.Standard.A1.Flex"

  shape_config {
    ocpus         = 2
    memory_in_gbs = 12
  }

  source_details {
    source_type             = "image"
    source_id               = var.node_image_ocid
    boot_volume_size_in_gbs = 50
  }

  create_vnic_details {
    subnet_id        = oci_core_subnet.public.id
    nsg_ids          = [oci_core_network_security_group.node.id]
    assign_public_ip = true
    hostname_label   = "node"
  }

  metadata = {
    # The PUBLIC half only, read from a path outside the repo. No key material
    # is committed, and nothing here needs SOPS as a result.
    ssh_authorized_keys = file(pathexpand(var.ssh_public_key_path))
  }
}

# 50 GB block volume, separate from the 50 GB boot volume. 100 GB of the 200 GB
# Always Free total, leaving headroom for the five allowed backups.
#
# Separate from boot on purpose: Postgres data outliving a node rebuild is what
# makes Gate 9's drill a rebuild rather than a data loss event.
resource "oci_core_volume" "data" {
  compartment_id      = var.compartment_ocid
  availability_domain = data.oci_identity_availability_domains.ads.availability_domains[var.availability_domain_index].name
  display_name        = "signalbox-data"
  size_in_gbs         = 50
}

resource "oci_core_volume_attachment" "data" {
  attachment_type = "paravirtualized"
  instance_id     = oci_core_instance.node.id
  volume_id       = oci_core_volume.data.id
}
