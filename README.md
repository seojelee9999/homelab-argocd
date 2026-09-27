# Homelab Argo CD GitOps

이 저장소는 Homelab Kubernetes 클러스터의 Argo CD Application과
ApplicationSet을 관리한다. 애플리케이션 설정을 `apps/*.json`에 추가하면
ApplicationSet이 Argo CD Application을 생성하고, 각 manifest 저장소의
리소스를 대상 namespace에 배포한다.

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
