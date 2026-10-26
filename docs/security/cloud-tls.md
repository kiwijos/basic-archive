# Real TLS in the cloud (a stretch, documented and not built)

On Docker Desktop the Ingress serves a self-signed certificate for `localhost` (see ADR 0010). On a cloud cluster with a public name, [cert-manager](https://cert-manager.io) obtains and renews a certificate from Let's Encrypt, and nothing in the services changes: only the Ingress and one new resource.

1. Install cert-manager (once per cluster): `helm install cert-manager jetstack/cert-manager --namespace cert-manager --create-namespace --set crds.enabled=true`.
2. Create an issuer. Start with Let's Encrypt's staging server, which has generous rate limits, and switch to production once it works:

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory   # staging: https://acme-staging-v02.api.letsencrypt.org/directory
    email: you@example.org
    privateKeySecretRef:
      name: letsencrypt-account-key
    solvers:
      - http01:
          ingress:
            ingressClassName: traefik
```

3. Name the host in both Ingresses and ask for the certificate. cert-manager sees the annotation, completes the challenge through Traefik, and writes the Secret the Ingress already points at, `ship-archive-tls`:

```yaml
metadata:
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt
spec:
  tls:
    - hosts: [archive.example.org]
      secretName: ship-archive-tls
  rules:
    - host: archive.example.org
```

4. Redirect plain HTTP, which this repository does not do locally (see ADR 0010): a Traefik `redirectScheme` Middleware to `https`, attached to the Ingress with `traefik.ingress.kubernetes.io/router.middlewares`.

What has to be true first: the name resolves to the cluster's public address, ports 80 and 443 are reachable from the internet (the HTTP-01 challenge needs 80), and `scripts/create-secrets.sh` must not create its self-signed `ship-archive-tls` on that cluster, or cert-manager and the script would fight over the Secret. The NetworkPolicies need one addition for the challenge: cert-manager's solver pod is a new pod in this namespace, so it needs an allow rule from the Ingress controller like the four public services have.
