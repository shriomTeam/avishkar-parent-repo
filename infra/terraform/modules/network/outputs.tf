output "vpc_id" {
  value = google_compute_network.vpc.id
}

output "vpc_name" {
  value = google_compute_network.vpc.name
}

output "private_connection_id" {
  value = google_service_networking_connection.private_services.id
}

output "subnet_id" {
  value = google_compute_subnetwork.subnet.id
}
