# Set common variables for the environment. This is automatically pulled in in the root terragrunt.hcl configuration to
# feed forward to the child modules.

locals {
  environment = "DevOps"
  account_name   = "naxadevelopers"
  aws_region = "ap-southeast-1"
  aws_state_region = "ap-south-1"
  aws_account = "685797548389"
  application = "tasking-manager-ns"
  team  = "NAXA-NISCHAL-DELETE-ME"
  creator = "NAXA-NISCHAL-DELETE-ME"
  owner = "NAXA-NISCHAL-DELETE-ME"

  project_name="tm"
  vpc_name="vpc"
  vpc_cidr_block = "10.0.0.0/23"
  vpc_private_subnets = ["10.0.0.0/24", "10.0.1.0/24"]
  vpc_public_subnets = ["10.0.2.0/24", "10.0.3.0/24"]
  availability_zones = ["ap-south-1a", "ap-south-1b", "ap-south-1c"]
  ecr_names = ["tm_backend"]
  public_ec2_instance_ami = "ami-0f5ee92e2d63afc18"
  ecs_cluster_name = "tm-prod-ecs-cluster"
  ecs_loadbalancer_name = "tm-prod-load-balancer"
  ecs_task_role_name = "tm-ecsTaskExecutionRole"
  s3_bucket_name = "tm-s3"
  postgresql_root_username = "tm_db_admin"
  postgresql_root_password = "yiTGasnBfCCcV6Ek8dcDY"

  postgres_engine_version = "14.6-R1"
  postgres_instance_class = "db.t3.micro"
  postgres_db_name = "tm_backend"

  tm_backend_image = "naxa/tasking-manager:v2"
  domain = "naxa.com.np"
  tm_backend_subdomain = "tm-ecs"

  lb_logs_identifier_no = "114774131450"
  # Here Change identifier "114774131450" on basis of loadbalancer region
  # We're using 114774131450 as our loadbalancer is on region ap-southeast-1
  SSL_certificate_arn = "ssl_arn"
}