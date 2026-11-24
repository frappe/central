---
title: How VM prices compare
description: The plans, prices, and method behind the VM price comparison on the pricing page.
---

# How VM prices compare

The [Frappe Cloud pricing page](https://frappe.io/cloud/new/pricing) compares the monthly price of a Frappe Cloud server with similar plans from Hetzner, DigitalOcean, and AWS. This page lists the plans in that comparison and how each price was worked out.

::: info
Prices were verified on 24 November 2026. They are a point-in-time comparison in USD and can change. Check each provider's pricing page for current rates.
:::

## Monthly prices

| Size | Frappe Cloud | DigitalOcean | Hetzner | AWS |
| --- | --- | --- | --- | --- |
| 1 vCPU · 4 GB | $20 | $24 | $30.99 | $33.43 |
| 2 vCPU · 8 GB | $40 | $48 | $57.99 | $66.14 |
| 4 vCPU · 16 GB | $80 | $96 | $109.99 | $131.55 |

Each price is the monthly cost of the server alone. It does not include tax, public IPv4, backups, or outbound transfer.

## Plans compared

The size is the Frappe Cloud plan. For each other provider, the comparison uses the smallest listed shared or burstable plan that has at least that CPU and memory.

### 1 vCPU · 4 GB

| Provider | Plan | Region | vCPU | Memory | Disk | Price / mo |
| --- | --- | --- | --- | --- | --- | --- |
| Frappe Cloud | VM | Mumbai | 1 | 4 GB | 50 GB SSD | $20 |
| Hetzner Cloud | CPX22 | Singapore | 2 | 4 GB | 80 GB NVMe | $30.99 |
| DigitalOcean | Basic Regular | Bangalore (BLR1) | 2 | 4 GiB | 80 GiB SSD | $24 |
| AWS EC2 | t3.medium | Mumbai | 2 | 4 GiB | 8 GiB gp3 | $33.43 |

### 2 vCPU · 8 GB

| Provider | Plan | Region | vCPU | Memory | Disk | Price / mo |
| --- | --- | --- | --- | --- | --- | --- |
| Frappe Cloud | VM | Mumbai | 2 | 8 GB | 100 GB SSD | $40 |
| Hetzner Cloud | CPX32 | Singapore | 4 | 8 GB | 160 GB NVMe | $57.99 |
| DigitalOcean | Basic Regular | Bangalore (BLR1) | 4 | 8 GiB | 160 GiB SSD | $48 |
| AWS EC2 | t3.large | Mumbai | 2 | 8 GiB | 8 GiB gp3 | $66.14 |

### 4 vCPU · 16 GB

| Provider | Plan | Region | vCPU | Memory | Disk | Price / mo |
| --- | --- | --- | --- | --- | --- | --- |
| Frappe Cloud | VM | Mumbai | 4 | 16 GB | 200 GB SSD | $80 |
| Hetzner Cloud | CPX42 | Singapore | 8 | 16 GB | 320 GB NVMe | $109.99 |
| DigitalOcean | Basic Regular | Bangalore (BLR1) | 8 | 16 GiB | 320 GiB SSD | $96 |
| AWS EC2 | t3.xlarge | Mumbai | 4 | 16 GiB | 8 GiB gp3 | $131.55 |

## How we compared

### Pricing basis

All plans are Linux x86 plans at on-demand prices, with no commitments, promotional credits, or taxes.

Regions differ. Frappe Cloud and AWS use Mumbai, DigitalOcean uses Bangalore, and Hetzner uses Singapore.

### CPU

CPU counts are nominal allocations, not performance equivalents.

- Hetzner CPX and DigitalOcean Basic use shared CPUs.
- AWS T3 uses CPU credits and may incur Unlimited surplus-credit charges, which are excluded.
- Frappe Cloud fractional plans share CPU capacity. The comparison uses plans with at least 1 vCPU.

### Storage

Storage is not normalised. Frappe Cloud, Hetzner, and DigitalOcean include the disk shown. AWS includes an 8 GiB Linux boot disk, not an equivalent data disk. Mumbai gp3 costs $0.0912 per GiB-month, with baseline IOPS and throughput. Increase it for your workload.

GB and GiB follow each provider's published units.

### Monthly price

Hetzner and DigitalOcean prices are their monthly caps. AWS compute uses 730 hours a month.

Some providers include IPv4 and transfer in the base price. No separate IPv4, backup, or transfer charges are added for any provider. Hetzner prices are published rates and do not guarantee current stock.

### AWS estimates

| Size | Instance | Hourly rate | Compute (× 730 hours) | 8 GiB gp3 boot disk | Total / mo |
| --- | --- | --- | --- | --- | --- |
| 1 vCPU · 4 GB | t3.medium | $0.0448 | $32.70 | $0.73 | $33.43 |
| 2 vCPU · 8 GB | t3.large | $0.0896 | $65.41 | $0.73 | $66.14 |
| 4 vCPU · 16 GB | t3.xlarge | $0.1792 | $130.82 | $0.73 | $131.55 |

The boot disk is 8 GiB × $0.0912 = $0.7296 a month.

## Sources

- [Frappe Cloud pricing](https://frappe.io/cloud/new/pricing)
- [Hetzner Cloud plans](https://www.hetzner.com/cloud/regular-performance/)
- [Hetzner regional USD rates](https://www.hetzner.com/_resources/app/data/bench/cloud_data.json)
- [DigitalOcean Droplet pricing](https://www.digitalocean.com/pricing/droplets)
- [AWS EC2 on-demand pricing](https://aws.amazon.com/ec2/pricing/on-demand/)
- [AWS EBS pricing](https://aws.amazon.com/ebs/pricing/)
