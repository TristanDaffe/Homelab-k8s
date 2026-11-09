# Homelab-k8S

Kubernetes workloads for the homelab k3s cluster, deployed by Argo CD from this
repository. The cluster itself (VMs, k3s install, Argo CD bootstrap) lives in
`Homelab-infra`.

## Planned layout

| Path | Contents |
|---|---|
| `bootstrap/` | Root Argo CD Application (app-of-apps), applied once by Ansible from `Homelab-infra`; Argo CD then manages itself |
| `infrastructure/` | Cluster add-ons, synced in this order: kube-vip (ingress floating IP for `*.autostack.ovh`) → Longhorn → cert-manager + OVH DNS-01 webhook → External Secrets (Infisical) → monitoring |
| `apps/` | One folder per application; most use the bjw-s `app-template` Helm chart with a values file |

## Conventions

- **Storage:** Longhorn by default (`longhorn`, 2 replicas); `longhorn-single` (1 replica) for Prometheus/Loki; `local-path` for caches. SQLite apps keep SQLite on Longhorn.
- **Databases:** apps that already use PostgreSQL connect to the Patroni cluster on the floating IP `192.168.129.140:5432` (one database and role per app).
- **Secrets:** External Secrets Operator reading from Infisical. Nothing secret is committed here.
- **CI:** `helm template` + `kubeconform` on pull requests; Argo CD does the deploying.
