# Portfolio: https://akibaha.shop/portfolio/

`apps/portfolio.json`을 기존 `homelab-apps` ApplicationSet이 읽어
`homelab-portfolio` 저장소의 `main/deploy`를 `portfolio` 네임스페이스에 배포한다.
Schedule과 같은 방식으로 앱 저장소의 Kustomize 구성을 사용한다.

BookStack Deployment, MariaDB StatefulSet, Service, PVC, ExternalSecret,
초기화 ConfigMap, HTTPRoute는 앱 저장소에서 함께 관리한다.
이 저장소에는 ApplicationSet 등록 정보만 추가하며, 앱 리소스나 HTTPRoute를
`gateway-resources/`에 중복 등록하지 않는다.

## 경로와 저장소

- `https://akibaha.shop/portfolio` → 302 → `https://akibaha.shop/portfolio/`
- `/portfolio/…` → 접두사 제거 → `portfolio/portfolio-bookstack:80`의 `/…`
- 기존 `gateway-system/tunnel-gateway`의 `http` listener 사용
- 앱의 `APP_URL`: `https://akibaha.shop/portfolio`
- BookStack 1개 복제본, Recreate 배포, 앱/첨부파일 PVC 5Gi
- MariaDB 전용 StatefulSet, DB PVC 10Gi
- 두 PVC는 `longhorn-database` 사용, Namespace/PVC는 prune·delete 보호

앱은 고정 버전의 upstream 이미지를 사용한다. Schedule의 앱 이미지 빌드 및
GHCR pull Secret 설정이나 세션 고정용 BackendTrafficPolicy는 필요하지 않다.

## 배포 전 준비

기존 ESO의 `aws-parameter-store` ClusterSecretStore와
`longhorn-database` StorageClass를 사용한다. 다음 SSM 값을 준비하고
ESO가 읽기·복호화할 수 있는지 확인한다. 실제 비밀값은 Git에 저장하지 않는다.

- `/homelab/portfolio/APP_KEY`
- `/homelab/portfolio/DB_PASSWORD`
- `/homelab/portfolio/MARIADB_ROOT_PASSWORD`
- `/homelab/portfolio/INITIAL_ADMIN_EMAIL`
- `/homelab/portfolio/INITIAL_ADMIN_PASSWORD`

최초 Secret 생성은 앱 저장소의 `scripts/bootstrap_secrets.py`와 README를
참고한다. 기존 데이터가 있다면 APP_KEY나 DB 비밀번호를 임의로 재생성하지 않는다.
DB와 첨부파일, APP_KEY는 함께 백업한다.

Argo CD Git 인증에는 `homelab-portfolio` 읽기 권한이 필요하다.
앱 저장소의 `main`에 배포 파일이 게시되고 CI가 통과했는지 확인한 다음,
이 저장소의 `apps/portfolio.json`을 commit/push하여 자동 배포한다.
ApplicationSet의 기존 auto-sync/prune/selfHeal 설정이 그대로 적용된다.

## 확인

로컬 매니페스트 검증:

```bash
python3 ~/portfolio/scripts/validate.py
kubectl kustomize ~/portfolio/deploy
```

Git 반영 및 실제 배포 후 확인:

```bash
kubectl -n argocd get application portfolio
kubectl -n portfolio get externalsecrets,pvc,pods,svc
kubectl -n portfolio rollout status statefulset/portfolio-mariadb
kubectl -n portfolio rollout status deployment/portfolio-bookstack
kubectl -n portfolio describe httproute portfolio
curl -I https://akibaha.shop/portfolio
curl -I https://akibaha.shop/portfolio/
python3 ~/portfolio/scripts/smoke.py
```

Argo CD의 Healthy/Synced, ExternalSecret의 Ready, PVC의 Bound,
Route의 Accepted/ResolvedRefs를 확인한다. 앱 초기화 완료 후 readiness가
통과해야 하며, 브라우저에서 공개 문서 열람·검색, 관리자 로그인,
정적 파일과 첨부파일 경로를 확인한다.
