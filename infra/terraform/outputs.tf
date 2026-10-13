output "vpc_name" {
  value = module.network.vpc_name
}

output "db_instance_connection_name" {
  description = "Used by the Cloud SQL Auth Proxy and Cloud Run."
  value       = module.cloudsql.connection_name
}

output "db_private_ip" {
  value = module.cloudsql.private_ip
}

output "registry_url" {
  description = "Docker repository for images, e.g. <this>/migrate:<tag>."
  value       = module.registry.url
}

output "migrate_job_name" {
  value = module.migrate_job.name
}
