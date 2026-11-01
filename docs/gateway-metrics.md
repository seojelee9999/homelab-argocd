# Envoy Proxy 메트릭 수집

`cluster-resources/envoy-proxy-monitor.yaml`은 Prometheus Operator가
`envoy-gateway-system`의 `gateway-system/tunnel-gateway` 프록시 Pod에서
`metrics` 포트의 `/stats/prometheus`를 30초마다 수집하도록 설정한다.
`release: monitoring`은 kube-prometheus-stack의 기본 PodMonitor 선택에
맞추기 위한 레이블이다.

이 메트릭은 게이트웨이를 통과하는 요청과 Envoy의 업스트림 상태를
관찰한다. 애플리케이션 내부 작업 대기열이나 DB 처리 시간은 별도
계측이 필요하다. 수집 설정은 알림 규칙을 자동으로 만들지 않는다.

배포 후 Prometheus Targets에서 `podMonitor/monitoring/envoy-proxy`가
`UP`인지 확인하고, 테스트 요청을 보낸 뒤 요청량·응답 코드·응답 시간과
업스트림 대기 지표의 실제 이름 및 레이블을 확인한다.

```sh
kubectl -n monitoring get podmonitor envoy-proxy
kubectl -n monitoring get prometheus monitoring-kube-prometheus-prometheus
```

참고: https://gateway.envoyproxy.io/v1.9/tasks/observability/proxy-metric/
