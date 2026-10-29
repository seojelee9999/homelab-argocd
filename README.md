# Homelab Argo CD GitOps

이 저장소는 Homelab Kubernetes 클러스터의 Argo CD Application과
ApplicationSet을 관리한다. 애플리케이션 설정을 `apps/*.json`에 추가하면
ApplicationSet이 Argo CD Application을 생성하고, 각 manifest 저장소의
리소스를 대상 namespace에 배포한다.

AWS 키를 Kubernetes Secret으로 수동 등록하고 ESO로 SSM의 GitHub PAT를
가져오는 절차는 [ESO 설정](docs/external-secrets.md)을 참고한다.

## 배포 구조

```text
Ansible/Helm으로 Argo CD 설치
        |
        v
bootstrap/root-application.yaml
        |
        v
homelab-root Application
        |
        v
argocd/applicationset.yaml
        |
        v
homelab-apps ApplicationSet
        |
        v
apps/*.json
        |
        v
애플리케이션별 Argo CD Application
        |
        v
각 manifest 저장소의 Kubernetes 리소스
```

현재 `diet-app`은 다음 두 저장소 역할로 구성된다.

- ApplicationSet 및 앱 목록: `https://github.com/seojelee9999/homelab-argocd.git`
- 애플리케이션과 Kubernetes manifest: `https://github.com/seojelee9999/diet-app.git`의 `deploy/`

## 저장소 구조

```text
.
├── bootstrap/
│   └── root-application.yaml
├── argocd/
│   └── applicationset.yaml
└── apps/
    └── diet-app.json
```

- `bootstrap/root-application.yaml`: 최초 진입점인 `homelab-root` Application
- `argocd/applicationset.yaml`: `apps/*.json`을 읽는 ApplicationSet
- `apps/*.json`: 생성할 Application별 저장소, revision, path, namespace 설정

## 1. Argo CD 설치 및 GitOps 부트스트랩

Ansible 저장소의 `deploy_argocd.yml`이 Argo CD 설치, PAT 인증 등록,
Root Application 생성을 순서대로 수행한다. 명령은 Ansible 저장소에서 실행한다.

먼저 `deploy-vault.yaml`에 아래 변수를 Ansible Vault로 암호화해 저장한다.
PAT에는 `homelab-argocd`와 읽어야 할 private 앱 저장소의
`Contents: Read-only` 권한을 부여한다.

```yaml
vault_argocd_repository_pat: <GitHub PAT>
```

파일 전체를 암호화해서 관리한다면, 기존 파일이 평문일 때 최초 한 번
`ansible-vault encrypt deploy-vault.yaml`을 실행하고
`ansible-vault edit deploy-vault.yaml`로 변수를 추가한다. 실제 PAT를 평문으로
Git에 커밋하지 않는다. 기존 SSH 키 변수는 이 playbook에서 더 이상 사용하지 않는다.

```bash
ansible-playbook -i inventory.ini deploy_argocd.yml --ask-vault-pass
```

playbook은 다음 작업을 수행한다.

- `argocd` namespace 생성
- Kubernetes worker node label 설정
- Helm으로 Argo CD 설치 또는 업그레이드
- Argo CD 컴포넌트를 worker node에 배치
- Argo CD Server를 NodePort로 노출
- `github-seojelee9999-repo-creds` Secret에 HTTPS + PAT 인증 등록
- `main` 브랜치의 `argocd/`를 감시하는 `homelab-root` Application 생성

PAT가 누락되면 클러스터를 변경하기 전에 중단한다. 아래 2~3절의 수동
등록은 playbook을 실행했다면 별도로 수행할 필요가 없다.

설치 확인:

```bash
kubectl -n argocd get pods
kubectl -n argocd get svc
```

## 2. GitHub PAT 인증 (수동 등록 시)

여러 저장소에서 같은 GitHub 계정의 PAT를 사용하기 위해 개별
`repository` Secret 대신 URL prefix 기반의 `repo-creds` Secret을 사용한다.
모든 Argo CD `repoURL`은 HTTPS 형식으로 통일한다.

```text
https://github.com/seojelee9999/<repository>.git
```

Fine-grained PAT에는 Argo CD가 읽어야 할 private 저장소를 선택하고
`Contents: Read-only` 권한을 부여한다. PAT를 명령 기록에 직접 입력하지
않도록 숨김 입력으로 받는다.

```bash
read -rsp 'GitHub PAT: ' GITHUB_PAT
echo

kubectl -n argocd create secret generic github-seojelee9999-repo-creds \
  --from-literal=type=git \
  --from-literal=url='https://github.com/seojelee9999/' \
  --from-literal=username='seojelee9999' \
  --from-literal=password="$GITHUB_PAT" \
  --dry-run=client -o yaml |
kubectl label --local -f - \
  argocd.argoproj.io/secret-type=repo-creds \
  -o yaml |
kubectl apply -f -

unset GITHUB_PAT
```

Secret 확인:

```bash
kubectl -n argocd get secret github-seojelee9999-repo-creds \
  --show-labels
```

`deploy_argocd.yml`은 같은 이름의 Secret을 생성하거나 갱신하며, PAT는
`deploy-vault.yaml`의 `vault_argocd_repository_pat`에서 공급한다.
기존에 수동 등록한 Secret도 playbook 실행 시 해당 값으로 갱신된다.

동일 URL prefix의 `repo-creds` Secret을 두 개 이상 만들지 않는다. 중복
Secret에 만료되거나 잘못된 토큰이 있으면 Argo CD가 해당 토큰을 선택해
`Invalid username or token` 오류가 발생할 수 있다.

```bash
kubectl -n argocd get secret \
  -l argocd.argoproj.io/secret-type=repo-creds \
  -o name
```

기존 Secret을 보존하면서 Argo CD 대상에서 제외하려면 label만 제거한다.

```bash
kubectl -n argocd label secret <old-secret-name> \
  argocd.argoproj.io/secret-type-
```

## 3. Root Application 부트스트랩 (수동 등록 시)

playbook을 사용하지 않는 경우 이 저장소에서 최초 한 번
`homelab-root` Application을 등록한다.

```bash
kubectl apply -f bootstrap/root-application.yaml
```

`homelab-root`는 이 저장소의 `argocd/` 경로를 감시하며 자동 sync,
prune 및 self-heal을 수행한다.

```bash
kubectl -n argocd get application homelab-root
```

## 4. ApplicationSet 동작

`homelab-apps` ApplicationSet은 Git files generator로 `apps/*.json`을
읽는다.

```yaml
generators:
  - git:
      repoURL: https://github.com/seojelee9999/homelab-argocd.git
      revision: HEAD
      files:
        - path: apps/*.json
```

각 JSON의 값은 Application 템플릿에 전달된다.

```yaml
source:
  repoURL: "{{repoURL}}"
  targetRevision: "{{targetRevision}}"
  path: "{{manifest_path}}"
destination:
  namespace: "{{namespace}}"
```

자동 sync 정책:

```yaml
syncPolicy:
  automated:
    prune: true
    selfHeal: true
  syncOptions:
    - CreateNamespace=true
```

클러스터에서 직접 수정한 리소스는 self-heal로 원복될 수 있으므로 지속할
변경은 반드시 Git에 반영한다.

## 5. 애플리케이션 추가

`apps/` 아래에 JSON 파일을 추가한다. `diet-app`의 예시는 다음과 같다.

```json
{
  "appName": "diet-app",
  "repoURL": "https://github.com/seojelee9999/diet-app.git",
  "targetRevision": "HEAD",
  "manifest_path": "deploy",
  "namespace": "diet-app"
}
```

`manifest_path`는 `argocd/applicationset.yaml`의 템플릿 변수 이름과 정확히
일치해야 한다. 예를 들어 `manifestpath`처럼 작성하면 변수가 치환되지
않아 다음 오류가 발생한다.

```text
{{manifest_path}}: app path does not exist
```

변경사항을 commit하고 push하면 ApplicationSet이 Application을 생성한다.

```bash
git add apps/diet-app.json
git commit -m "Add diet-app application"
git push
```

즉시 다시 읽게 하려면 다음 annotation을 사용한다.

```bash
kubectl -n argocd annotate applicationset homelab-apps \
  argocd.argoproj.io/application-set-refresh=true --overwrite
```

## 6. 상태 확인

전체 Application 확인:

```bash
kubectl -n argocd get applications
```

ApplicationSet 상태 확인:

```bash
kubectl -n argocd get applicationset homelab-apps
```

`diet-app`이 사용하는 manifest 경로 확인:

```bash
kubectl -n argocd get app diet-app \
  -o jsonpath='{.spec.source.path}'; echo
```

정상 결과:

```text
.
```

Application을 강제로 다시 비교하려면 다음 명령을 사용한다.

```bash
kubectl -n argocd annotate application diet-app \
  argocd.argoproj.io/refresh=hard --overwrite
```

## 7. GHCR 이미지 배포

Argo CD의 Git PAT 인증과 Kubernetes의 GHCR 이미지 pull 인증은 서로
별개다. GitHub Actions는 다음 순서로 동작해야 한다.

```text
애플리케이션 코드 push
        |
        v
컨테이너 이미지 build
        |
        v
ghcr.io/seojelee9999/<image>:<commit-sha> push
        |
        v
diet-app/deploy/kustomization.yaml의 image tag 갱신 및 push
        |
        v
Argo CD 자동 sync 및 rollout
```

manifest에 placeholder 이미지를 남기지 않는다.

```yaml
containers:
  - name: diet-app
    image: ghcr.io/seojelee9999/<image>:<commit-sha>
```

private GHCR package를 사용하는 경우 Deployment에 pull Secret을 지정한다.

```yaml
imagePullSecrets:
  - name: ghcr-pull
```

Ansible 저장소에서 GHCR pull Secret을 생성한다.

```bash
ansible-playbook -i inventory.ini register_diet_ghcr.yml
```

`latest` 고정보다는 commit SHA와 같은 불변 태그를 권장한다. 이미지가
변경될 때 manifest도 변경되므로 Argo CD가 새 배포를 명확하게 감지할 수
있다.

## 8. Envoy Gateway 설치 (Argo CD + Helm)

Gateway API를 사용하려면 리소스 타입을 등록하는 **CRD**와 실제 프록시를
관리하는 **컨트롤러**가 모두 필요하다. Helm은 필수는 아니지만, 이 저장소는
`argocd/envoy-gateway.yaml`에서 공식 OCI Helm 차트를 Argo CD로 관리한다.
로컬에서 별도로 `helm install`을 실행할 필요는 없다.

- 차트: `oci://docker.io/envoyproxy/gateway-helm`, 버전: `v1.6.7`
- 설치 namespace: `envoy-gateway-system`
- Gateway API 및 Envoy Gateway CRD를 함께 설치한다.
- 큰 CRD의 annotation 크기 제한을 피하도록 `ServerSideApply=true`를 사용한다.
- `homelab-root`가 감시하는 `argocd/`에 있으므로 Git 반영 후 자동 배포된다.

현재 클러스터는 **Kubernetes v1.30.14 + Calico**이며, Kubernetes
1.30~1.33과 호환되는 Envoy Gateway v1.6.7로 고정했다. Calico를 교체할
필요는 없다. 다만 v1.6 계열은 **2026-05-13에 지원 종료(EOL)**되었으므로
장기 운영에는 Kubernetes를 업그레이드하고 유지보수 중인 Envoy Gateway로
전환하는 것을 권장한다. v1.9 계열은 Kubernetes 1.33~1.36이 대상이다.
[호환성 표](https://gateway.envoyproxy.io/news/releases/matrix/)를 확인한다.
기존 CRD가 없는 클러스터를 기준으로 구성했다.
이미 다른 도구가 Gateway API CRD를 관리한다면 중복 소유하지 않도록
[공식 설치 지침](https://gateway.envoyproxy.io/docs/install/install-helm/)에
따라 CRD 관리를 분리한다. v1.6 차트에서는 `helm.skipCrds: true`로
번들 CRD 설치를 제외하고 필요한 CRD를 별도로 관리할 수 있다.

수동으로 Application을 먼저 등록하려면:

```bash
kubectl apply -f argocd/envoy-gateway.yaml
kubectl -n argocd get application envoy-gateway
```

Argo CD sync로 Deployment가 생성된 뒤 컨트롤러와 CRD 준비를 확인한다.

```bash
kubectl -n envoy-gateway-system rollout status deployment/envoy-gateway --timeout=300s
kubectl wait --for=condition=Established --timeout=120s \
  crd/gatewayclasses.gateway.networking.k8s.io \
  crd/gateways.gateway.networking.k8s.io \
  crd/httproutes.gateway.networking.k8s.io
```

### Gateway와 앱 라우팅

`cluster-resources/gateway-system.yaml`은 `envoy` GatewayClass와
`gateway-system/envoy-gateway` Gateway를 정의한다.
`soulin.xyz/diet-app` 요청은 `diet-app` namespace의 `diet-app:80`
Service로 전달된다. `/diet-app` 경로는 그대로 전달하므로 앱에서도 해당
경로를 지원해야 한다. `diet-app` namespace와 Service는 앱 배포로 먼저
준비되어 있어야 한다.

HTTPS listener는 `gateway-system` namespace의 `soulin-xyz-tls` Secret을
참조한다. `soulin.xyz`에 유효한 인증서와 키로 먼저 생성하거나 cert-manager로
같은 이름의 Secret을 발급한다. 인증서와 개인키는 Git에 저장하지 않는다.

```bash
kubectl create namespace gateway-system --dry-run=client -o yaml | kubectl apply -f -
kubectl -n gateway-system create secret tls soulin-xyz-tls \
  --cert=/path/to/fullchain.pem --key=/path/to/privkey.pem
kubectl apply -f cluster-resources/gateway-system.yaml
kubectl get gatewayclass envoy
kubectl -n gateway-system get gateway envoy-gateway
kubectl -n diet-app describe httproute diet-app-route
kubectl -n envoy-gateway-system get svc
```

`cluster-resources/`는 현재 Root Application의 감시 대상이 아니므로 위
Gateway 파일은 컨트롤러 설치 후 별도로 적용한다. 기존 `cilium-gateway`가
클러스터에 있다면 새 Gateway 적용만으로 삭제되지는 않는다. Envoy의
접속을 확인하고 DNS/포트포워딩을 전환한 다음 기존 Gateway를 정리한다.

Envoy가 만드는 트래픽용 Service는 기본적으로 `LoadBalancer`를 사용한다.
현재 Calico 홈랩에는 MetalLB 등의 외부 IP 할당 및 L2/BGP 광고 구성이
필요하다. IP가 `Pending`이면 해당
구성을 확인한다. 공유기 환경에서는 외부 80/443 포트를 이 IP로 전달하고
`soulin.xyz` DNS를 진입점에 연결한다. 컨트롤러 설치만으로 공인 IP나 DNS,
인증서가 자동 생성되지는 않는다.

참고: [Envoy Gateway Argo CD 설치](https://gateway.envoyproxy.io/docs/install/install-argocd/),
[빠른 시작](https://gateway.envoyproxy.io/docs/tasks/quickstart/).

## 문제 해결

### Invalid username or token

```bash
kubectl -n argocd get secret \
  -l argocd.argoproj.io/secret-type=repo-creds \
  -o name
```

- 동일 URL prefix의 중복 `repo-creds`가 없는지 확인한다.
- PAT 만료 여부를 확인한다.
- PAT에 대상 저장소와 `Contents: Read-only` 권한이 있는지 확인한다.
- Application과 ApplicationSet의 `repoURL`이 HTTPS인지 확인한다.

### app path does not exist

- Application의 path를 확인한다.

  ```bash
  kubectl -n argocd get app diet-app \
    -o jsonpath='{.spec.source.path}'; echo
  ```

- `apps/*.json`의 `manifest_path` 키와 ApplicationSet의
  `{{manifest_path}}` 변수가 일치하는지 확인한다.

### ImagePullBackOff

```bash
kubectl -n diet-app get pods
kubectl -n diet-app get events --sort-by=.lastTimestamp
```

- 이미지가 `ghcr.io/your-username/temp` 같은 placeholder가 아닌지 확인한다.
- GHCR에 해당 tag가 실제로 존재하는지 확인한다.
- private package이면 `ghcr-pull` Secret과 `imagePullSecrets`를 확인한다.

## 보안 주의사항

- PAT, SSH private key, GitHub password를 Git에 commit하지 않는다.
- PAT는 필요한 저장소와 최소 읽기 권한만 부여한다.
- Kubernetes Secret을 평문 YAML로 저장소에 추가하지 않는다.
- 자동화에 필요한 비밀값은 Ansible Vault 또는 별도의 secret manager로
  관리한다.
