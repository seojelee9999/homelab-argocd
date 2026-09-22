# diet-app Argo CD 정상화 기록

작성일: 2026-09-23 (Asia/Seoul)

이 문서는 `diet-app`이 Argo CD에는 `Synced`로 표시되지만 실제 Pod가
`ImagePullBackOff`로 실행되지 않던 장애의 확인 과정, 판단 근거, 변경 내용과
재검증 절차를 기록한다. 토큰 원문은 명령 기록과 Git에 남기지 않는다.

## 1. 장애 상태와 증거

최초 관찰 결과는 다음과 같았다.

| 대상 | 관찰 결과 | 의미 |
|---|---|---|
| Argo CD Application | `Synced / Degraded` | 선언 상태는 적용했지만 리소스가 정상 동작하지 않음 |
| Deployment | `0/2 Ready` | 실행 가능한 replica가 없음 |
| Pod | `ImagePullBackOff` | 컨테이너 이미지를 가져오지 못함 |
| Deployment 이미지 | `ghcr.io/seojelee9999/diet-app` | 불변 SHA 태그가 적용되지 않음 |
| imagePullSecrets | `argocd` | 앱 네임스페이스에 존재하지 않는 Secret을 참조 |
| `diet-app` Secret | 없음 | private GHCR 인증을 제공할 수 없음 |
| Service/PVC | 없음 | 앱 노출과 SQLite 영속 저장 구성이 적용되지 않음 |
| PV `diet-app-data` | 없음 | PVC를 생성해도 Bound될 대상이 없음 |

사용한 명령:

```bash
kubectl -n argocd get application diet-app \
  -o custom-columns='NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status,REVISION:.status.sync.revision'
kubectl -n diet-app get deployment,pods,service,pvc -o wide
kubectl -n diet-app get deployment diet-app \
  -o jsonpath='image={.spec.template.spec.containers[0].image}{"\n"}pullSecrets={.spec.template.spec.imagePullSecrets[*].name}{"\n"}'
kubectl -n diet-app get secrets
kubectl -n diet-app describe pod <pod-name>
kubectl get pv diet-app-data
```

근거:

- `Synced`는 Git과 live manifest가 같다는 뜻이며 Pod 가용성을 보장하지 않는다.
- 실제 서비스 가능 여부는 Application의 `Healthy`, Deployment의 Ready replica,
  Pod의 `Running/Ready`, 엔드포인트 응답을 함께 확인해야 한다.
- Pod 이벤트의 `FailedToRetrieveImagePullSecret`은 참조한 Secret이 같은
  네임스페이스에 없다는 직접적인 증거다.

## 2. 근본 원인

Argo CD는 `diet-app-menifest` 저장소의 루트를 감시하고 있었지만, CI는 이미지
push 후 `diet-app` 저장소의 `deploy/kustomization.yaml`을 갱신하고 있었다.
즉 이미지 생성과 실제 배포 소스가 서로 달랐다.

확인 명령:

```bash
kubectl -n argocd get application diet-app \
  -o jsonpath='repoURL={.spec.source.repoURL}{"\n"}path={.spec.source.path}{"\n"}'
git -C diet-app show HEAD:deploy/kustomization.yaml
git -C diet-app-menifest show HEAD:deployment.yaml
```

두 저장소의 manifest도 서로 달랐다.

- `diet-app/deploy`: SHA 이미지 태그, Service, PVC, probe, 보안 컨텍스트 포함
- `diet-app-menifest`: 태그 없는 이미지, 잘못된 pull secret, Service/PVC 없음

별도 manifest 저장소를 유지하려면 cross-repository 쓰기 토큰과 동기화 로직이
추가로 필요하다. 이 장애에서는 중복 상태를 제거하기 위해 Argo CD가 CI가 직접
갱신하는 `diet-app/deploy`를 유일한 배포 소스로 사용하도록 변경했다.

## 3. 적용한 변경

`homelab-argocd/apps/diet-app.json`:

```json
{
  "appName": "diet-app",
  "repoURL": "https://github.com/seojelee9999/diet-app.git",
  "targetRevision": "HEAD",
  "manifest_path": "deploy",
  "namespace": "diet-app"
}
```

`diet-app/deploy`에는 다음 리소스를 단일 Kustomize 구성으로 둔다.

- Namespace
- 단일 replica 및 `Recreate` 전략의 Deployment
- `diet-app-data` PVC
- `diet-app` ClusterIP Service
- `akibaha.shop`용 nginx Ingress

SQLite는 동시에 두 writer를 실행하지 않도록 replica 1과 `Recreate` 전략을
사용한다. 이미지는 CI가 push에 성공한 소스 commit SHA로 고정한다.

렌더링 검증:

```bash
kubectl kustomize diet-app/deploy > /tmp/diet-app-rendered.yaml
kubectl apply --dry-run=server -f /tmp/diet-app-rendered.yaml
```

## 4. 스토리지 준비

이 클러스터는 `worker-01`의 로컬 경로를 사용하는 정적 PV 구성이다.

```bash
ssh ubuntu@192.168.55.11 \
  'sudo install -d -o 10001 -g 10001 -m 0750 /var/lib/mealnote'

kubectl apply -f - <<'EOF'
apiVersion: v1
kind: PersistentVolume
metadata:
  name: diet-app-data
spec:
  capacity:
    storage: 1Gi
  volumeMode: Filesystem
  accessModes:
    - ReadWriteOnce
  storageClassName: ""
  persistentVolumeReclaimPolicy: Retain
  claimRef:
    namespace: diet-app
    name: diet-app-data
  local:
    path: /var/lib/mealnote
  nodeAffinity:
    required:
      nodeSelectorTerms:
        - matchExpressions:
            - key: kubernetes.io/hostname
              operator: In
              values: [worker-01]
EOF
```

근거:

- PVC는 `volumeName: diet-app-data`, `storageClassName: ""`을 사용하므로 같은
  이름의 정적 PV가 필요하다.
- local PV는 해당 경로가 존재하는 노드로 Pod를 제한해야 데이터 경로가
  일관된다.
- `Retain` 정책과 Namespace/PVC의 Argo CD 삭제 방지 annotation으로 실수에
  의한 데이터 삭제 가능성을 줄인다.

## 5. private GHCR 인증

이미지의 익명 manifest 요청은 HTTP `401`, 기존 fine-grained PAT로 인증한
manifest 요청은 HTTP `403`이었다. 로그인 성공만으로 image pull 권한이
검증되는 것은 아니며, 실제 manifest 요청 성공 여부가 근거가 된다.

사용자가 cp-01의 `/tmp/diet-ghcr-read-pat`에 저장한 새 PAT(권한 0600)로
GHCR token 발급 후 SHA 이미지 manifest를 요청해 HTTP 200을 확인했다.
인증 검증에는 Python `urllib.request`로 다음 두 URL을 순서대로 호출했다.

- `https://ghcr.io/token?service=ghcr.io&scope=repository%3Aseojelee9999%2Fdiet-app%3Apull` (Basic 인증)
- `https://ghcr.io/v2/seojelee9999/diet-app/manifests/5d03adaba836a5fd712e3ebb9dc5c521b12b8a5c` (발급받은 Bearer token)

아래는 실제 등록과 동일하게 토큰을 파일에서 읽고 Secret JSON을 stdin으로
전달하는 재현 명령이다. cp-01에서 실행하며 원문을 화면이나 프로세스 인자에
출력하지 않는다. PAT는 패키지 접근 권한과 `read:packages` 권한이 필요하다.

```bash
set -o pipefail
python3 - <<'PY' | kubectl apply -f -
import base64, json, pathlib
pat = pathlib.Path('/tmp/diet-ghcr-read-pat').read_text().strip()
auth = base64.b64encode(('seojelee9999:' + pat).encode()).decode()
config = json.dumps({'auths': {'ghcr.io': {'auth': auth}}})
print(json.dumps({
    'apiVersion': 'v1', 'kind': 'Secret',
    'metadata': {'name': 'ghcr-pull', 'namespace': 'diet-app'},
    'type': 'kubernetes.io/dockerconfigjson',
    'data': {'.dockerconfigjson': base64.b64encode(config.encode()).decode()}
}))
PY
```

Secret 원문을 출력하지 않는 검증:

```bash
kubectl -n diet-app get secret ghcr-pull \
  -o jsonpath='type={.type}{"\n"}'
```

정상 결과는 `type=kubernetes.io/dockerconfigjson`이다. 토큰은 Git에 commit하지
않고 Ansible Vault 또는 secret manager로 관리한다.

## 6. Argo CD 반영 및 정상 판정

ApplicationSet 변경 후 hard refresh를 요청한다.

```bash
kubectl -n argocd annotate applicationset homelab-apps \
  argocd.argoproj.io/refresh=hard --overwrite
kubectl -n argocd annotate application diet-app \
  argocd.argoproj.io/refresh=hard --overwrite
```

이번 전환에서는 기존 Deployment가 `RollingUpdate`로 만든 실패 ReplicaSet 2개를
그대로 유지해 새 `Recreate` ReplicaSet 생성이 진행되지 않았다. 기존 Pod는 각각
placeholder 이미지 또는 태그 없는 이미지를 사용했고 Ready가 된 적이 없으며
PVC도 마운트하지 않았다. 다음 명령으로 해당 실패 ReplicaSet만 0으로 축소했다.

```bash
kubectl -n diet-app scale replicaset \
  diet-app-c8f5fd757 diet-app-db95dbf7f --replicas=0
```

그 결과 Deployment controller가 SHA 이미지의 새 ReplicaSet
`diet-app-586f6f55cf`를 생성했다. 일반적인 정상 rollout에서는 이 명령이 필요
없다. 실행 전 반드시 `kubectl -n diet-app get rs -o wide`와 owner reference로
대상이 현재 Deployment의 이전 ReplicaSet인지 확인한다.

아래 순서로 상태를 확인한다.

```bash
kubectl -n argocd get application diet-app -w
kubectl -n diet-app get pvc,pods,service,ingress -o wide
kubectl -n diet-app rollout status deployment/diet-app --timeout=180s
kubectl -n diet-app get endpointslice \
  -l kubernetes.io/service-name=diet-app
kubectl -n diet-app run diet-app-smoke --rm -i --restart=Never \
  --image=curlimages/curl -- curl --fail --silent http://diet-app/healthz
```

정상 판정 기준:

1. Application이 `Synced / Healthy`
2. Deployment가 `1/1 Ready`
3. Pod가 `Running`이며 readiness가 `1/1`
4. PVC가 `Bound`
5. Service에 ready EndpointSlice가 존재
6. 클러스터 내부 `/healthz` 응답이 `{"status": "ok"}`

## 7. 2026-09-23 적용 결과

GitOps 소스 전환 뒤 실제 관찰 결과:

| 항목 | 결과 |
|---|---|
| Argo CD source | `https://github.com/seojelee9999/diet-app.git`, path `deploy` |
| Sync | `Synced`, revision `be1effa5e62efc5323ff8f6ddb8b2f6d4dbca0b9` |
| 이미지 | `ghcr.io/seojelee9999/diet-app:5d03adaba836a5fd712e3ebb9dc5c521b12b8a5c` |
| Deployment | replica 1, strategy `Recreate`, pull secret `ghcr-pull` |
| PVC/PV | `diet-app-data` / `diet-app-data`, `Bound` |
| Service | `diet-app`, ClusterIP, port 80 |
| Ingress | `diet-app`, class `nginx`, host `akibaha.shop` |
| 인증 | 새 PAT manifest HTTP 200 확인 후 `ghcr-pull` 생성 완료 |
| 최종 상태 | `Synced / Healthy`, Deployment `1/1`, Pod `1/1 Running` |

인증 등록 전 새 Pod의 이벤트는 익명 GHCR token 요청에 대한 `401 Unauthorized`와
`FailedToRetrieveImagePullSecret (ghcr-pull)`이었다. 이는 GitOps와 스토리지는
정상 적용됐고 private registry 자격 증명만 남았다는 직접적인 근거다.

Secret 등록 후 기존 Pod의 backoff 대기를 줄이기 위해 실행하지 못한 Pod만
삭제했다. ReplicaSet이 새 Pod를 만들었고 이미지를 6.56초에 가져왔다.
PVC나 데이터는 삭제하지 않았다.

```bash
kubectl -n diet-app delete pod diet-app-586f6f55cf-2l7r4
kubectl -n diet-app rollout status deployment/diet-app --timeout=50s
kubectl -n diet-app get pods,pvc,svc,ingress -o wide
kubectl -n argocd get application diet-app
kubectl -n diet-app get endpointslice -l kubernetes.io/service-name=diet-app
```

결과: rollout 성공, 새 Pod `diet-app-586f6f55cf-7g4c8`가 worker-01에서
`1/1 Running`, endpoint `172.16.171.21:8080`, Application `Synced / Healthy`.

cp-01에서 실제 사용한 HTTP 검증 명령:

```bash
# Service 라우팅 및 DB health 검증
curl -fsS --max-time 10 http://10.111.10.243/healthz
# nginx host 라우팅 검증
curl -fsS --max-time 10 -H 'Host: akibaha.shop' http://192.168.55.10:31208/healthz
# 메인 화면 제공 검증
curl -fsS --max-time 10 -H 'Host: akibaha.shop' http://192.168.55.10:31208/ | head -c 160
# Pod 내부에서 클러스터 DNS 및 Service 접근 검증
kubectl -n diet-app exec deployment/diet-app -- python -c \
  'import urllib.request; print(urllib.request.urlopen("http://diet-app.diet-app.svc.cluster.local/healthz",timeout=10).read().decode())'
```

세 health 요청 모두 `{"status": "ok"}`를 반환했고 메인 화면은 HTML을 반환했다.
외부 인터넷의 DNS/NAT/TLS 및 브라우저 상호작용은 이 검증에 포함되지 않는다.
브라우저로 로컬 확인하려면 cp-01에서
`kubectl -n diet-app port-forward --address=127.0.0.1 service/diet-app 8080:80`을
실행하고 사용자 PC에서
`ssh -L 18080:127.0.0.1:8080 ubuntu@192.168.55.10`으로 연결한 뒤
`http://localhost:18080`을 연다.

## 8. 재발 시 트러블슈팅 명령과 선택 근거

```bash
# Git 선언 상태와 실제 리소스 health를 분리해 확인한다.
kubectl -n argocd get application diet-app
kubectl -n argocd describe application diet-app

# 스케줄링, pull, mount, probe 실패를 Pod 이벤트에서 확인한다.
kubectl -n diet-app get pods -o wide
kubectl -n diet-app describe pod <pod-name>
kubectl -n diet-app get events --sort-by=.lastTimestamp

# 실제 적용된 이미지와 pull secret을 Git의 기대값과 비교한다.
kubectl -n diet-app get deployment diet-app \
  -o jsonpath='image={.spec.template.spec.containers[0].image}{"\n"}pullSecrets={.spec.template.spec.imagePullSecrets[*].name}{"\n"}'

# PVC/PV binding 및 local PV의 node affinity를 확인한다.
kubectl -n diet-app get pvc
kubectl get pv diet-app-data -o yaml

# 컨테이너가 시작된 뒤 probe 실패 원인을 로그와 직접 요청으로 구분한다.
kubectl -n diet-app logs deployment/diet-app --tail=100
kubectl -n diet-app port-forward service/diet-app 8080:80
curl --fail http://127.0.0.1:8080/healthz
```

각 단계는 앞 단계보다 애플리케이션에 가까운 계층을 검사한다. Argo CD 선언,
Kubernetes rollout, Pod 런타임, 스토리지, Service endpoint, HTTP 응답 순서로
확인하면 장애 범위를 빠르게 좁힐 수 있다.
