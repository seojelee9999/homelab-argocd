# Cloudflare Tunnel 경로 라우팅

`akibaha.shop/diet-app`은 `/diet-app/`으로 이동한 뒤 경로 접두사를
제거하여 `diet-app/diet-app:80`에 전달한다. 다른 앱은 자체 HTTPRoute를
추가해 `/stock`처럼 별도 경로를 사용할 수 있다.

## 배포 순서

1. 식단 앱 저장소의 현재 이미지 소스 `45cc09f`에
   `diet-app-subpath.patch`를 적용하고 CI를 통해 이미지를 빌드·배포한다.
   정적 파일과 API URL을 문서 경로에 상대적으로 바꾸는 변경이다.
2. 이 저장소의 `argocd/`와 `gateway-resources/` 변경을 Git에 반영한다.
   `homelab-root`가 Envoy Gateway와 라우팅 Application을 생성한다.
3. Gateway와 Route의 `Accepted`, `Programmed`, `ResolvedRefs` 상태를
   확인한다. Gateway의 Envoy Service는 클러스터 내부 전용이다.
4. Cloudflare 대시보드에서 `akibaha.shop` 공개 호스트 이름의 서비스
   URL을 아래 명령으로 조회한 Envoy Service의 클러스터 DNS 이름과
   HTTP 포트 80으로 지정한다. DNS와 터널 공개 호스트 설정은 별도다.

```sh
kubectl -n gateway-system get gateway tunnel-gateway
kubectl -n diet-app describe httproute diet-app
kubectl -n envoy-gateway-system get svc \
  -l gateway.envoyproxy.io/owning-gateway-namespace=gateway-system,gateway.envoyproxy.io/owning-gateway-name=tunnel-gateway
```

예를 들어 조회된 서비스가 `envoy-example`이면 Tunnel origin은
`http://envoy-example.envoy-gateway-system.svc.cluster.local:80`이다.
Cloudflare에서 기존 origin을 전환하기 전에 앱과 Gateway가 준비됐는지
확인한다. TLS는 브라우저와 Cloudflare 사이에서 종료하며, 터널에서
클러스터 내부 Gateway까지는 HTTP를 사용한다.

관리 화면은 `/grafana/`와 `/argocd/`로 접근한다. Grafana의 하위 경로는
monitoring Helm values에서 설정한다. Argo CD는 `argocd-cmd-params-cm`의
`server.rootpath`, `server.basehref`, `server.insecure`를 사용하며,
설정을 바꾼 후 `argocd-server` Deployment를 재시작해야 한다. Argo CD
Helm 재설치 또는 업그레이드 시에도 이 값을 유지해야 한다. 서버 자체의
TLS가 꺼져 있으므로 기존 NodePort의 443도 더 이상 HTTPS가 아니다.
