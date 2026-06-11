// 🟡 Dummy data. Atlas (asset/VM/region/access surfaces) has no customer API or
// DocType specced yet — ADR 0004 frames it as a sibling of the team console that
// shares the capability IAM. These screens render against the fixtures below;
// swap each `ref(MOCK_*)` for a useList/useCall when Atlas ships real endpoints.

export const MOCK_VMS = [
  { name: 'vm-web-01', resource_id: 'res_a1b2', cluster: 'mumbai', plan: 'Standard', vcpu: 2, ram_gb: 4, status: 'running', ip: '10.0.1.11', created: '2026-04-02' },
  { name: 'vm-web-02', resource_id: 'res_c3d4', cluster: 'mumbai', plan: 'Standard', vcpu: 2, ram_gb: 4, status: 'running', ip: '10.0.1.12', created: '2026-04-02' },
  { name: 'vm-batch-01', resource_id: 'res_e5f6', cluster: 'singapore', plan: 'Pro', vcpu: 8, ram_gb: 32, status: 'stopped', ip: '10.1.4.9', created: '2026-05-18' },
  { name: 'vm-old-01', resource_id: 'res_x9y8', cluster: 'mumbai', plan: 'Standard', vcpu: 2, ram_gb: 4, status: 'terminated', ip: null, created: '2026-01-10' },
]

export const MOCK_CLUSTERS = [
  { slug: 'mumbai', label: 'Mumbai (ap-south-1)', status: 'active', allowed: true, resources: 3 },
  { slug: 'singapore', label: 'Singapore (ap-se-1)', status: 'active', allowed: true, resources: 1 },
  { slug: 'frankfurt', label: 'Frankfurt (eu-central-1)', status: 'available', allowed: false, resources: 0 },
]

export const MOCK_ACCESS_REQUESTS = [
  { cluster: 'frankfurt', cluster_label: 'Frankfurt (eu-central-1)', reason: 'GDPR data residency', status: 'pending', requested: '2026-06-08' },
  { cluster: 'singapore', cluster_label: 'Singapore (ap-se-1)', reason: 'Batch workloads', status: 'approved', requested: '2026-05-15' },
  { cluster: 'frankfurt', cluster_label: 'Frankfurt (eu-central-1)', reason: 'Early test', status: 'declined', requested: '2026-04-30', note: 'tier too low' },
]

// The resource's immutable event stream (keyed on resource_id), shown in the VM
// detail Activity tab. 🟡 dummy until the Agent exposes a customer event feed.
export const MOCK_EVENTS = {
  res_a1b2: [
    { at: '2026-04-02', event: 'subscribed', detail: 'Standard · Mumbai' },
    { at: '2026-04-02', event: 'started', detail: 'res_a1b2' },
  ],
  res_e5f6: [
    { at: '2026-05-18', event: 'subscribed', detail: 'Pro · Singapore' },
    { at: '2026-05-18', event: 'started', detail: 'res_e5f6' },
    { at: '2026-06-01', event: 'stopped', detail: 'res_e5f6' },
  ],
}

export const clusterLabel = (slug) =>
  MOCK_CLUSTERS.find((c) => c.slug === slug)?.label || slug
