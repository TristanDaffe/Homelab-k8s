# Homelab-k8S

Kubernetes workloads for the homelab k3s cluster, deployed by Argo CD from this
repository. The cluster itself (VMs, k3s install, Argo CD bootstrap) lives in
`Homelab-infra`.

## Layout

| Path | Contents |
|---|---|
| `bootstrap/` | Synced by the `root` Application, which Ansible creates once (`Homelab-infra`: `ansible/configure/argocd.yaml`). `argocd.yaml` = Argo CD managing itself; `apps.yaml` = ApplicationSet turning every `apps/<name>/` folder into an app |
| `infrastructure/argocd/` | Argo CD Helm values |
| `infrastructure/kube-vip/` | kube-vip (Services mode, ARP) values |
| `infrastructure/traefik/` | HelmChartConfig for the k3s Traefik (floating IP annotation) |
| `infrastructure/cert-manager/`, `cert-manager-webhook-ovh/` | cert-manager + OVH DNS-01 webhook; ClusterIssuers `letsencrypt-staging` / `letsencrypt-prod` (OVH keys: Secret `cert-manager/ovh-credentials`, from Infisical) |
| `infrastructure/external-secrets/`, `external-secrets-config/` | External Secrets Operator + ClusterSecretStore `infisical` (project `homelab-k8s`, env `prod`, one folder per consumer); ExternalSecrets for add-ons, e.g. `cert-manager/ovh-credentials` ← `/cert-manager/*` |
| `infrastructure/longhorn/` | Longhorn 1.13 on each node's data disk (`/var/lib/longhorn`); UI via `kubectl -n longhorn-system port-forward svc/longhorn-frontend 8081:80` (no ingress: the UI has no login) |
| `infrastructure/storage/` | StorageClass `longhorn-single` (1 replica) and `local-path` set non-default |
| `infrastructure/certificates/` | Wildcard `*.kube.autostack.ovh` certificate, served by Traefik as its default certificate (`TLSStore default`) — apps need no TLS config |
| `infrastructure/` (planned) | Cluster add-ons, synced in this order: kube-vip (ingress floating IP for `*.autostack.ovh`) → Longhorn → cert-manager + OVH DNS-01 webhook → External Secrets (Infisical) → monitoring |
| `apps/<name>/values.yaml` | One app per folder, deployed with the bjw-s `app-template` chart (version set in `bootstrap/apps.yaml`) into namespace `<name>` |

Argo CD reads this repo over SSH with a read-only **deploy key** (`argocd@k3s`); its private half is in the `Homelab-infra` SOPS secrets.

Apps are published under `*.kube.autostack.ovh` (OVH wildcard → **192.168.129.139**, the ingress floating IP that kube-vip holds on one node and moves to the other if it fails; Traefik's Service gets it through `infrastructure/traefik`). Argo CD UI: `http://argocd.kube.autostack.ovh`, user `admin`:

```bash
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d
```

## Conventions

- **Storage:** `longhorn` is the default StorageClass (2 replicas, best-effort locality, **Retain** — a pruned PVC keeps its data; delete released PVs by hand); `longhorn-single` (1 replica) for Prometheus/Loki; `local-path` for caches. SQLite apps keep SQLite on Longhorn.
- **Databases:** apps that already use PostgreSQL connect to the Patroni cluster on the floating IP `192.168.129.140:5432` (one database and role per app).
- **Secrets:** values live in Infisical (`https://pass.autostack.ovh`, project `homelab-k8s`, env `prod`, folder per app); an `ExternalSecret` (`secretStoreRef: ClusterSecretStore/infisical`, absolute keys like `/myapp/KEY`) turns them into a Kubernetes Secret. Nothing secret is committed here. The only bootstrap secret, the Infisical machine identity, is created by Ansible from Homelab-infra SOPS.
- **CI:** `helm template` + `kubeconform` on pull requests; Argo CD does the deploying.
