# Homelab-k8S

Kubernetes workloads for the homelab k3s cluster, deployed by Argo CD from this
repository. The cluster itself (VMs, k3s install, Argo CD bootstrap) lives in
`Homelab-infra`.

## Layout

| Path | Contents |
|---|---|
| `bootstrap/` | Synced by the `root` Application, which Ansible creates once (`Homelab-infra`: `ansible/configure/argocd.yaml`). `argocd.yaml` = Argo CD managing itself; `apps.yaml` = ApplicationSet turning every `apps/<name>/` folder into an app |
| `infrastructure/argocd/` | Argo CD Helm values |
| `infrastructure/` (planned) | Cluster add-ons, synced in this order: kube-vip (ingress floating IP for `*.autostack.ovh`) → Longhorn → cert-manager + OVH DNS-01 webhook → External Secrets (Infisical) → monitoring |
| `apps/<name>/values.yaml` | One app per folder, deployed with the bjw-s `app-template` chart (version set in `bootstrap/apps.yaml`) into namespace `<name>` |

Argo CD reads this repo over SSH with a read-only **deploy key** (`argocd@k3s`); its private half is in the `Homelab-infra` SOPS secrets. Until an ingress with TLS exists, open the UI with:

```bash
kubectl -n argocd port-forward svc/argocd-server 8080:80   # http://localhost:8080, user admin
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d
```

## Conventions

- **Storage:** Longhorn by default (`longhorn`, 2 replicas); `longhorn-single` (1 replica) for Prometheus/Loki; `local-path` for caches. SQLite apps keep SQLite on Longhorn.
- **Databases:** apps that already use PostgreSQL connect to the Patroni cluster on the floating IP `192.168.129.140:5432` (one database and role per app).
- **Secrets:** External Secrets Operator reading from Infisical. Nothing secret is committed here.
- **CI:** `helm template` + `kubeconform` on pull requests; Argo CD does the deploying.
