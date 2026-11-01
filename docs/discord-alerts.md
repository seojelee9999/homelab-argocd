# Discord 모니터링 알림

Prometheus 규칙에서 발생한 알림을 Alertmanager가 묶어서 Discord 채널의
웹훅으로 전송한다. 해결된 알림도 전송한다. 계속 발생하도록 설계된
`Watchdog` 알림은 Discord로 보내지 않는다. 기본 알림 그룹화와 중복 억제
설정은 kube-prometheus-stack의 기본값을 사용한다.

## 웹훅 등록

1. Discord 채널 설정에서 웹훅을 만들고 URL을 복사한다.
2. AWS Systems Manager Parameter Store 서울 리전(`ap-northeast-2`)에
   `/homelab/monitoring/DISCORD_WEBHOOK_URL` 이름의 `SecureString`으로
   등록한다. URL은 Git이나 명령 기록에 남기지 않는다.
3. External Secrets가 값을 `monitoring/alertmanager-discord` Secret으로
   동기화한다. 기존 `aws-parameter-store` 접근 자격에 해당 SSM 파라미터
   조회 및 KMS 복호화 권한이 필요하다.

```sh
kubectl -n monitoring get externalsecret alertmanager-discord
kubectl -n monitoring describe externalsecret alertmanager-discord
kubectl -n monitoring get alertmanager monitoring-kube-prometheus-alertmanager
kubectl -n monitoring get pods -l app.kubernetes.io/name=alertmanager
```

ExternalSecret의 `Ready=True`와 Alertmanager Pod의 준비 상태를 확인한다.
URL을 바꾸면 Parameter Store 값을 갱신한다. ExternalSecret은 한 시간마다
새 값을 반영한다. 알림이 오지 않으면 Alertmanager 로그의 전송 오류,
웹훅 유효성, Discord 채널 권한과 클러스터의 외부 HTTPS 연결을 확인한다.
로그나 Secret 내용을 공유할 때 웹훅 URL이 노출되지 않게 주의한다.
