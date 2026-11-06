# Schedule: https://akibaha.shop/plan/

`apps/schedule.json`을 기존 `homelab-apps` ApplicationSet이 읽어
`homelab-schedule` 저장소의 `main/deploy`를 `schedule` 네임스페이스에 배포한다.
Deployment, Service, PostgreSQL StatefulSet, 10Gi PVC, ExternalSecret,
HTTPRoute는 앱 저장소에서 함께 관리한다.

`diet-app-menifest/deploy`의 Kustomize, PostgreSQL 17, `longhorn-database`,
AWS Parameter Store/ESO 및 Namespace/PVC 보존 구성을 참고한다.
앱 CI가 같은 저장소의 이미지 SHA를 갱신하므로 배포 리소스를 이 저장소에
복사하거나 같은 HTTPRoute를 `gateway-resources/`에 중복 등록하지 않는다.

## 경로

- `https://akibaha.shop/plan` → 302 → `https://akibaha.shop/plan/`
- `/plan/…` → 접두사 제거 → `schedule/schedule:8080`의 `/…`
- 기존 `gateway-system/tunnel-gateway`의 `http` listener 사용
- 세션 쿠키: `DAYSESSION`, `Path=/plan`, `Secure`, `SameSite=lax`

앱의 상대 정적 파일/API URL과 쿠키 경로를 함께 유지해야 CSRF 세션이 동작한다.
Cloudflare에서 TLS를 종료하며 리다이렉트에는 HTTPS와 443을 명시한다.

앱의 CSRF 토큰은 각 Pod의 세션에 저장된다. `gateway-resources/schedule-session.yaml`의
BackendTrafficPolicy가 `PLAN_AFFINITY` 쿠키로 같은 브라우저 요청을 같은 Pod에
전달하여 2개 복제본에서 간헐적으로 발생하는 403을 방지한다.
이 정책은 `gateway-routes` Application이 관리하고 schedule HTTPRoute에만 적용한다.
쿠키는 `/plan` 범위, Secure/HttpOnly/SameSite=Lax, 유효기간 24시간이다.
Pod 교체나 쿠키 만료로 세션이 바뀌면 페이지를 새로고침해 CSRF 토큰을 다시 받는다.
설정 근거: [Envoy Gateway v1.6 쿠키 기반 부하 분산](https://gateway.envoyproxy.io/v1.6/tasks/traffic/load-balancing/#cookie).

## 배포 전 준비

기존 ESO의 `aws-parameter-store` ClusterSecretStore와
`longhorn-database` StorageClass를 사용한다. 다음 SSM 값을 준비한다.
실제 비밀값은 Git에 저장하지 않는다.

- `/homelab/schedule/DB_PASSWORD`
- `/homelab/schedule/POSTGRES_ADMIN_PASSWORD`
- `/homelab/schedule/DISCORD_WEBHOOK_URL`
- 기존 `/homelab/ghcr/GHCR_USERNAME`, `/homelab/ghcr/GHCR_TOKEN`

Argo CD Git 인증에는 `homelab-schedule` 읽기 권한이 필요하다.
먼저 앱 저장소의 `/plan` 변경을 반영하고 CI가 실제 GHCR 이미지 SHA와
`replicas=2`를 `deploy/kustomization.yaml`에 기록했는지 확인한다.
초기 `bootstrap` 이미지는 게시된 이미지가 아니며 앱 복제 수는 0이다.
그다음 이 저장소의 `apps/schedule.json`을 commit/push하여 자동 배포한다.

## 확인

```bash
kubectl kustomize ~/schedule/deploy
kubectl -n argocd get application schedule
kubectl -n schedule get externalsecrets,pvc,pods,svc
kubectl -n schedule rollout status statefulset/schedule-postgres
kubectl -n schedule rollout status deployment/schedule
kubectl -n schedule describe httproute schedule
curl -I https://akibaha.shop/plan
curl -I https://akibaha.shop/plan/
```

실제 배포 후 Route의 `Accepted`/`ResolvedRefs`, 앱의 readiness,
브라우저의 `/plan/` 정적 파일·API·일정 CRUD를 확인한다.
