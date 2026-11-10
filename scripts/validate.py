#!/usr/bin/env python3
"""Render and validate everything Argo CD deploys from this repo.

Run by CI on every pull request and push, and locally (needs helm, kubeconform
and PyYAML):

    python3 scripts/validate.py

For every Argo CD Application in bootstrap/:
  - chart sources: `helm template` with the chart, version and value files the
    Application uses ($values/... = this repo), then kubeconform
  - directory sources (path: ...): kubeconform on the manifests
For the `apps` ApplicationSet: every apps/<name>/values.yaml rendered with the
chart it declares. The Application/ApplicationSet files themselves are checked too.

Charts ignore value keys they don't know (a typo like `ingres:` renders fine and
silently drops the ingress), so every top-level key of our value files must
also exist in the chart's own values or in one of its subcharts' values.
"""
import glob
import os
import subprocess
import sys
import tempfile

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
K8S_VERSION = os.environ.get("K8S_VERSION", "1.36.0")
CRD_SCHEMAS = ("https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/"
               "{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json")
failures = []
CHART_CACHE = tempfile.mkdtemp(prefix="validate-charts-")


def kubeconform(label, data=None, paths=()):
    cmd = ["kubeconform", "-strict", "-summary", "-kubernetes-version", K8S_VERSION,
           "-schema-location", "default", "-schema-location", CRD_SCHEMAS,
           # chart CRDs and operator resources without a published schema
           "-ignore-missing-schemas", *paths]
    if data is not None:
        cmd.append("-")
    r = subprocess.run(cmd, input=data, capture_output=True, text=True)
    status = "ok  " if r.returncode == 0 else "FAIL"
    summary = (r.stdout.strip().splitlines() or [""])[-1]
    print(f"{status} {label}: {summary}")
    if r.returncode != 0:
        print("\n".join("     " + line for line in (r.stdout + r.stderr).splitlines()[:20]))
        failures.append(label)


def chart_ref(source):
    repo, chart = source["repoURL"], source["chart"]
    if repo.startswith("oci://") or not repo.startswith("http"):
        return ["oci://" + repo.removeprefix("oci://").rstrip("/") + "/" + chart]
    return [chart, "--repo", repo]


def known_keys(source):
    """Top-level value keys the chart understands: its values.yaml, its
    subcharts' values.yaml (library charts like app-template's `common` read
    them at the top level) and the subchart names themselves."""
    dest = os.path.join(CHART_CACHE, f"{source['chart']}-{source['targetRevision']}")
    if not os.path.isdir(dest):
        subprocess.run(["helm", "pull", *chart_ref(source), "--version",
                        str(source["targetRevision"]), "--untar", "--untardir", dest],
                       check=True, capture_output=True, text=True)
    keys = {"global"}
    for values in glob.glob(os.path.join(dest, "*", "values.yaml")) + \
            glob.glob(os.path.join(dest, "*", "charts", "*", "values.yaml")):
        keys |= set((yaml.safe_load(open(values)) or {}).keys())
    keys |= {os.path.basename(c) for c in glob.glob(os.path.join(dest, "*", "charts", "*"))}
    return keys


def check_keys(label, source, files):
    known = known_keys(source)
    for f in files:
        unknown = sorted(set((yaml.safe_load(open(f)) or {}).keys()) - known)
        if unknown:
            print(f"FAIL {label}: {os.path.relpath(f, ROOT)}: unknown top-level key(s) "
                  f"{unknown} for chart {source['chart']} {source['targetRevision']}")
            failures.append(label)


def helm_template(label, source, release, namespace, value_files):
    chart, version = source["chart"], source["targetRevision"]
    check_keys(label, source, value_files)
    ref = chart_ref(source)
    cmd = ["helm", "template", release, *ref, "--version", str(version),
           "--namespace", namespace]
    for f in value_files:
        cmd += ["-f", f]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"FAIL {label}: helm template\n     " + r.stderr.strip().replace("\n", "\n     "))
        failures.append(label)
        return
    kubeconform(f"{label} ({chart} {version})", data=r.stdout)


def value_files(source, base_path=None):
    files = []
    for f in source.get("helm", {}).get("valueFiles", []):
        if base_path is not None:
            f = f.replace("{{ .path.path }}", base_path)
        files.append(os.path.join(ROOT, f.removeprefix("$values/")))
    missing = [f for f in files if not os.path.exists(f)]
    if missing:
        raise FileNotFoundError(", ".join(os.path.relpath(m, ROOT) for m in missing))
    return files


def check_application(app, path):
    spec, name = app["spec"], app["metadata"]["name"]
    namespace = spec["destination"].get("namespace", "default")
    for src in spec.get("sources", [spec.get("source")]):
        if not src or src.get("ref"):
            continue
        if "chart" in src:
            release = src.get("helm", {}).get("releaseName", name)
            helm_template(f"app {name}", src, release, namespace, value_files(src))
        elif "path" in src:
            manifests = sorted(glob.glob(os.path.join(ROOT, src["path"], "*.y*ml")))
            kubeconform(f"app {name} ({src['path']})", paths=manifests)


def check_applicationset(appset):
    template = appset["spec"]["template"]["spec"]
    for gen in appset["spec"]["generators"]:
        for d in gen.get("git", {}).get("directories", []):
            for app_dir in sorted(glob.glob(os.path.join(ROOT, d["path"]))):
                if not os.path.isdir(app_dir):
                    continue
                rel, base = os.path.relpath(app_dir, ROOT), os.path.basename(app_dir)
                for src in template.get("sources", [template.get("source")]):
                    if src and "chart" in src:
                        helm_template(f"{appset['metadata']['name']}/{base}", src, base, base,
                                      value_files(src, base_path=rel))


def main():
    bootstrap = sorted(glob.glob(os.path.join(ROOT, "bootstrap", "*.y*ml")))
    kubeconform("bootstrap/ (Argo CD resources)", paths=bootstrap)
    for path in bootstrap:
        for doc in yaml.safe_load_all(open(path)):
            if not doc:
                continue
            try:
                if doc["kind"] == "Application":
                    check_application(doc, path)
                elif doc["kind"] == "ApplicationSet":
                    check_applicationset(doc)
            except FileNotFoundError as e:
                print(f"FAIL {os.path.relpath(path, ROOT)}: missing value file {e}")
                failures.append(path)
    if failures:
        print(f"\n{len(failures)} check(s) failed")
        sys.exit(1)
    print("\nall checks passed")


if __name__ == "__main__":
    main()
