# Simplified DNS and Fibonacci application

NYU CSCI-GA.2262-001 Lab 3, Fall 2026.

US resolves `fibonacci.com` through AS using the handout's UDP text protocol, requests its Fibonacci value from FS over HTTP, and returns the result. AS stores authoritative A records in SQLite. Each service has its own complete Docker build context.

| Service | Container port | Endpoint or protocol |
| --- | --- | --- |
| US | 8080 TCP | `GET /fibonacci?hostname=fibonacci.com&fs_port=9090&number=10&as_ip=as&as_port=53533` |
| FS | 9090 TCP | `PUT /register` and `GET /fibonacci?number=10` |
| AS | 53533 UDP | Two-line registration and query datagrams |

## Run with Docker

From this directory:

```sh
docker compose up --build -d
```

Register FS using its address on the shared Docker network. This command runs inside US so that the Docker names `as` and `fs` resolve on that network:

```sh
docker compose exec -T us python - <<'PY'
import json, socket, urllib.request
body = json.dumps({
    'hostname': 'fibonacci.com',
    'ip': socket.gethostbyname('fs'),
    'as_ip': 'as',
    'as_port': '53533',
}).encode()
req = urllib.request.Request('http://fs:9090/register', data=body, method='PUT',
                             headers={'Content-Type': 'application/json'})
with urllib.request.urlopen(req) as r:
    print(r.status, r.read().decode().strip())
PY
```

Expected registration response: `201 registered`. Request the Fibonacci value:

```sh
curl -i 'http://localhost:8080/fibonacci?hostname=fibonacci.com&fs_port=9090&number=10&as_ip=as&as_port=53533'
```

Expected response: HTTP `200`, plain-text body `55` followed by a newline. The example uses service names to locate AS on the container network; numeric IPv4 addresses work as specified in the handout. The application hostname `fibonacci.com` is resolved exclusively by the custom AS.

All three containers share the Compose network. Published local ports bind to loopback. `as-data` is a named Docker volume, so registrations survive AS container restarts. If FS is recreated with a different container address, register it again.

## Protocol and error behavior

FS registration JSON:

```json
{"hostname":"fibonacci.com","ip":"172.18.0.2","as_ip":"172.18.0.3","as_port":"53533"}
```

Replace the example addresses with the real FS and AS addresses. AS registration datagram (each line, including the last, ends in LF):

```text
TYPE=A
NAME=fibonacci.com VALUE=172.18.0.2 TTL=10
```

AS acknowledges successful persistent registration with `OK\n`. The handout does not prescribe the acknowledgement body. FS returns HTTP 201 only after this acknowledgement.

Query and response:

```text
TYPE=A
NAME=fibonacci.com
```

```text
TYPE=A
NAME=fibonacci.com VALUE=172.18.0.2 TTL=10
```

These are the simplified text messages required by the lab, not the binary DNS wire format. Hostnames are matched case-insensitively. A registration replaces an existing record for that name. TTL=10 describes how long a resolver may cache the answer; it does not delete the authoritative record after ten seconds. US performs a fresh AS query for each request and does not cache.

US returns 400 when any of the five required parameters is missing or a hostname/port is malformed. FS returns 400 for missing or noninteger `number` values. The sequence uses F(0)=0, F(1)=1; negative indices are rejected with 400 because the exercise concerns nonnegative sequence positions. A successful response is 200 with a decimal integer body. A malformed registration returns 400. Downstream failures return 502, and an AS receive timeout returns 504. AS responds `ERROR=BAD_REQUEST\n` to malformed datagrams and `ERROR=NOT_FOUND\n` for an unknown A record. These error datagrams extend the handout only where it leaves behavior unspecified.

## Verify real services

The tests use only Python's standard library. From a host with access to the published ports:

```sh
FS_ID=$(docker compose ps -q fs)
FS_IP=$(docker inspect "$FS_ID" --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')
REGISTER_IP="$FS_IP" python3 tests/verify.py
```

The script verifies 39 cases including the full US-to-AS-to-FS flow, all missing US parameters, malformed registration, numeric edge cases, unknown names and record replacement. It emits JSON and exits with a nonzero status if an assertion fails.

To check persistence without re-registering, restart AS and query through US again:

```sh
docker compose restart as
curl --retry 5 --retry-all-errors 'http://localhost:8080/fibonacci?hostname=fibonacci.com&fs_port=9090&number=10&as_ip=as&as_port=53533'
```

## Deploy to a cloud Kubernetes cluster

The public images support both `linux/amd64` and `linux/arm64`:

- [leonchai/dcn-lab3-as:1.0](https://hub.docker.com/r/leonchai/dcn-lab3-as)
- [leonchai/dcn-lab3-fs:1.0](https://hub.docker.com/r/leonchai/dcn-lab3-fs)
- [leonchai/dcn-lab3-us:1.0](https://hub.docker.com/r/leonchai/dcn-lab3-us)

To rebuild and publish with an account that has write access to those repositories, run this from `dns_app`:

```sh
docker buildx bake -f compose.yaml --set '*.platform=linux/amd64,linux/arm64' --push
```

The cluster needs a default StorageClass (K3s supplies `local-path`), permission to provision a 1 Gi PVC, and access to the published images. The manifest contains the namespace, all three Deployments and NodePort Services, the AS PVC, and a one-time registration Job.

```sh
kubectl apply -f deploy_dns.yml
kubectl -n dcn-lab3 rollout status deployment/as
kubectl -n dcn-lab3 rollout status deployment/fs
kubectl -n dcn-lab3 rollout status deployment/us
kubectl -n dcn-lab3 wait --for=condition=complete job/register-fibonacci --timeout=300s
kubectl -n dcn-lab3 get deployments,pods,services,pvc
```

| Service | Service/container port | Required NodePort |
| --- | --- | --- |
| AS | 53533 UDP | 30001 UDP |
| FS | 9090 TCP | 30002 TCP |
| US | 8080 TCP | 30003 TCP |

Allow those NodePorts through the cloud firewall for the lab client. The application has no administrative credentials. The AS registration and FS registration endpoints intentionally implement the unauthenticated lab protocol; this is an educational deployment.

The Job registers the stable FS Service ClusterIP, so a replaced FS Pod does not invalidate the registration. With `NODE_IP` set to the node's reachable IPv4 address:

```sh
curl -i "http://${NODE_IP}:30002/fibonacci?number=10"
curl -i "http://${NODE_IP}:30003/fibonacci?hostname=fibonacci.com&fs_port=9090&number=10&as_ip=as&as_port=53533"
```

The second request enters through US NodePort 30003; US communicates internally with AS port 53533 and FS port 9090. External clients can also send a query directly to AS NodePort 30001. The registration Job runs once for an initial deployment; if the FS Service is deleted and recreated with another ClusterIP, rerun the registration or recreate the Job.

### Verified cloud run

On September 30, 2026 (America/New_York), this manifest was deployed to an AWS EC2 Ubuntu 24.04 instance in `us-east-2` running K3s `v1.36.4+k3s1`. All three Deployments reached `1/1` ready, the 1 Gi AS PVC was bound, and the registration Job completed. The same 39 integration checks passed both on the node and from an external client through the public NodePorts. Restarting the AS Deployment preserved the registered record and the end-to-end result `55` without re-registration.

The test client can target another cloud run with:

```sh
US_URL="http://${NODE_IP}:30003" FS_URL="http://${NODE_IP}:30002" \
AS_HOST="$NODE_IP" AS_PORT=30001 REGISTER_IP="$FS_CLUSTER_IP" \
REGISTER_AS=as REGISTER_AS_PORT=53533 FS_PORT=9090 python3 tests/verify.py
```

Set `FS_CLUSTER_IP` to `kubectl -n dcn-lab3 get svc fs -o jsonpath='{.spec.clusterIP}'`. Keep the instance's assigned public IP in your own run records; stopping and starting an instance may change it.

## Course references

- Lab3ApplicationLayer.pdf, Problem 2, pages 10-13: endpoints, ports, exact text messages and submission layout.
- Session2-ApplicationLayer-v3.pdf, slides 2-58 to 2-61: HTTP message and status-code semantics.
- Slides 2-161 to 2-166: UDP client/server sockets (`SOCK_DGRAM`, `sendto`, `recvfrom`).
- Slides 2-186 to 2-200: hostname resolution, authoritative servers, A records and TTL.
- https://kubernetes.io/docs/concepts/workloads/controllers/deployment/
- https://kubernetes.io/docs/concepts/services-networking/service/#type-nodeport
- https://docs.k3s.io/quick-start
