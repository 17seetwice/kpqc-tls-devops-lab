# AWS deployment experiment setup

[한국어](aws-setup.md) | **English**

Configure a GitHub OIDC provider and an IAM role that trusts only this repository's main branch.
The role permits starting and stopping the two lab instances in Seoul, adding and removing ingress rules for their two security groups, and querying instance state. Creating or terminating EC2 instances is not required.

## Actions secrets

| Name | Value |
| --- | --- |
| `KPQC_AWS_ROLE_ARN` | IAM role ARN for OIDC authentication |
| `KPQC_SERVER_INSTANCE_ID`, `KPQC_CLIENT_INSTANCE_ID` | Existing lab EC2 instance IDs |
| `KPQC_SERVER_SG_ID`, `KPQC_CLIENT_SG_ID` | Security group IDs attached to each instance |
| `KPQC_SSH_KEY` | Lab SSH private key |
| `KPQC_KNOWN_HOSTS` | Independently verified host keys, using aliases `kpqc-server` and `kpqc-client` |

Both instances must have Docker installed. Allow server TCP port 4433 only from the client security group.
The workflow temporarily allows SSH from the GitHub runner's single IPv4 address and removes that rule during cleanup.
If either instance is already running, the startup stage aborts to avoid interfering with other work.

Forced cancellation or AWS API failures can prevent cleanup. Check the final `cleanup_complete` value. If cleanup fails, inspect EC2 instance states and temporary `kpqc-actions-*` SSH rules in the AWS console.

Do not register a self-hosted runner for this public repository. The AWS workflow does not run on pull requests; manually dispatch it on main using a GitHub-hosted runner.

[GitHub documentation: OIDC in AWS](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws)
