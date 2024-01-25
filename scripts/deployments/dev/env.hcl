# Set common variables for the environment. This is automatically pulled in in the root terragrunt.hcl configuration to
# feed forward to the child modules.

#Example
# tm_backend_tasks_min = 2
# tm_backend_tasks_max = 5

locals {
  environment = "dev"
  account_name   = "naxadevelopers"
  aws_region = "ap-southeast-1"
  aws_account = "685797548389"
  application = "tasking-manager"
  team  = "NAXA-TM-NS"
  creator = "NAXA-TM-NS"
  owner = "NAXA-TM-NS"
  

  project_name="tm"
  vpc_name="vpc"
  vpc_cidr_block = "173.0.0.0/16"
  vpc_private_subnets = ["173.0.1.0/24", "173.0.2.0/24", "173.0.3.0/24"]
  vpc_public_subnets = ["173.0.4.0/24", "173.0.5.0/24", "173.0.6.0/24"]
  availability_zones = ["ap-southeast-1a", "ap-southeast-1b", "ap-southeast-1c"]
  ecr_names = ["tm_backend", "tm_frontend"]
  public_ec2_instance_ami = "ami-0fa377108253bf620"
  ecs_cluster_name = "tm-prod-ecs-cluster"
  ecs_loadbalancer_name = "tm-prod-load-balancer"
  ecs_task_role_name = "tm-ecsTaskExecutionRole"
  s3_bucket_name = "tm-s3"
  postgresql_root_username = "tm_db_admin"
  postgresql_root_password = "yiTGasnBfCCcV6Ek8dcDY"

  postgres_engine_version = "14.6"
  postgres_instance_class = "db.t3.micro"
  postgres_db_name = "tm_backend"

  tm_backend_image = "685797548389.dkr.ecr.ap-southeast-1.amazonaws.com/tm_backend:latest"
  tm_frontend_image = "685797548389.dkr.ecr.ap-southeast-1.amazonaws.com/tm_frontend:latest"

  domain = "naxa.com.np"
  tm_backend_subdomain = "tmtf"

  lb_logs_identifier_no = "114774131450"

  # We're using 114774131450 as our loadbalancer is on region ap-southeast-1
  SSL_certificate_arn = "arn:aws:acm:ap-southeast-1:685797548389:certificate/88f36688-db23-4878-af25-58be06d34181"
}