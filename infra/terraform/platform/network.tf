# The cloud floor's network half: VCN, gateway, route table, subnet, NSG.
# No Kubernetes anything -- that boundary is PLAN.md section 3 and it holds here.

resource "oci_core_vcn" "main" {
  compartment_id = var.compartment_ocid
  display_name   = "signalbox"
  cidr_blocks    = ["10.0.0.0/16"]
  dns_label      = "signalbox"
}

resource "oci_core_internet_gateway" "main" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.main.id
  display_name   = "signalbox-igw"
  enabled        = true
}

resource "oci_core_route_table" "public" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.main.id
  display_name   = "signalbox-public"

  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_internet_gateway.main.id
  }
}

# One public subnet. A private subnet would need a NAT gateway, which is not in
# the Always Free allowance, and there is one node -- so there is nothing for a
# second subnet to separate it from.
resource "oci_core_subnet" "public" {
  compartment_id             = var.compartment_ocid
  vcn_id                     = oci_core_vcn.main.id
  display_name               = "signalbox-public"
  cidr_block                 = "10.0.1.0/24"
  route_table_id             = oci_core_route_table.public.id
  dns_label                  = "public"
  prohibit_public_ip_on_vnic = false
}

# NSG rather than a security list: rules attach to the VNIC, so they travel with
# the instance rather than with everything that happens to share a subnet.
resource "oci_core_network_security_group" "node" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.main.id
  display_name   = "signalbox-node"
}

resource "oci_core_network_security_group_security_rule" "ssh_in" {
  network_security_group_id = oci_core_network_security_group.node.id
  direction                 = "INGRESS"
  protocol                  = "6" # TCP
  source                    = var.ssh_ingress_cidr
  source_type               = "CIDR_BLOCK"
  description               = "SSH from the operator only. Not 0.0.0.0/0 -- see ADR 0008."

  tcp_options {
    destination_port_range {
      min = 22
      max = 22
    }
  }
}

# Egress is open. The node pulls container images, k3s and upstream transit
# feeds; every one of those is CDN-fronted with moving addresses, so a CIDR
# allow-list here would be a list of lies that breaks silently. PLAN.md section
# 7 Gate 8 makes the same argument about NetworkPolicy egress.
resource "oci_core_network_security_group_security_rule" "all_out" {
  network_security_group_id = oci_core_network_security_group.node.id
  direction                 = "EGRESS"
  protocol                  = "all"
  destination               = "0.0.0.0/0"
  destination_type          = "CIDR_BLOCK"
  description               = "All egress. Upstream feeds and registries are CDN-fronted."
}
