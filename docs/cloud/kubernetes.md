# Kubernetes (reference, optional)

`infrastructure/k8s/` holds a reference deployment: namespace, API
deployment + service, worker deployment, scheduler deployment, frontend,
HPA (queue-depth/custom metric ready), PDB, config + secret references.
No credentials are hard-coded; images are digest-pinnable. Kubernetes is
an operational choice — self-hosting works fine on plain Docker Compose.
