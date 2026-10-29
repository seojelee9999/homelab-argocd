# diet-app PostgreSQL + Longhorn

`diet-app`의 두 앱 Pod는 `diet-app-postgres.diet-app.svc.cluster.local:5432`의
PostgreSQL 17 서버 하나에 연결한다. DB/앱 사용자 이름은 `diet_app`이다.
앱 사용자는 superuser가 아니며 해당 DB와 스키마만 소유한다.

## 저장소 역할

- 이 저장소 `cluster-resources/longhorn-database.yaml`: Longhorn StorageClass.
- `diet-app-menifest/deploy/postgres.yaml`: Service, 10Gi PVC, 초기 사용자 설정,
  PostgreSQL StatefulSet 1개.
- `diet-app-menifest/deploy/postgres-secret.yaml`: SSM → DB 인증 Secret.
- `diet-app-menifest/deploy/deployment.yaml`: 앱의 PostgreSQL 연결 환경변수와 readiness probe.
- `diet-app` 소스 저장소: psycopg 드라이버, PostgreSQL 지원 및 통합 테스트.

`cluster-resources/`는 클러스터에 등록된 Argo CD Application이 감시한다.
앱 manifest는 `apps/diet-app.json`이 지정한 별도 저장소의 `deploy/`에서 배포한다.

## 인증 정보 준비

서울 리전 SSM의 다음 SecureString 두 개를 사용한다.

- `/homelab/diet-app/DB_PASSWORD`: 앱 계정 비밀번호.
- `/homelab/diet-app/POSTGRES_ADMIN_PASSWORD`: PostgreSQL 관리자 비밀번호.

`scripts/register_db_parameters.py`는 누락된 비밀번호를 무작위로 생성한다.
기존 값은 덮어쓰지 않으며 비밀값을 출력하지 않는다. boto3와 AWS 프로필이 있는
컨트롤 플레인에서 다음과 같이 실행한다. 스크립트를 먼저 해당 호스트에 복사한다.

```bash
AWS_SHARED_CREDENTIALS_FILE=/home/ubuntu/.aws/credentials \
  python3 register_db_parameters.py --create
```

등록 계정에는 해당 경로의 `ssm:GetParameter`, `ssm:PutParameter` 권한이 필요하다.
ESO 인증 계정에는 해당 두 파라미터를 읽고 복호화할 권한이 필요하다.
사용자 관리 KMS 키를 선택하는 경우 해당 키의 복호화 권한도 부여한다.

## 배포 및 확인

StorageClass와 DB 리소스를 먼저 반영하고, ESO 및 DB가 Ready가 된 후
PostgreSQL 지원 앱 이미지를 빌드해 배포한다. 앱의 `DATABASE_BACKEND=postgres`와
`PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, Secret 참조 `PGPASSWORD`가 필요하다.
Service의 `targetPort: http`와 앱 컨테이너의 `ports[].name: http`가 일치해야 한다.

```bash
kubectl -n diet-app get externalsecret diet-app-db
kubectl -n diet-app get pvc diet-app-postgres-data
kubectl -n diet-app rollout status statefulset/diet-app-postgres
kubectl -n diet-app rollout status deployment/diet-app
kubectl -n longhorn-system get volumes.longhorn.io
```

앱의 기존 SQLite 데이터는 자동 이전하지 않는다. 이번 전환은 빈 DB로 시작한다.
기존 `diet-app-data` PVC는 사용하지 않으며 자동 삭제하지 않는다.

## 운영

- 두 워커에 Longhorn 복제본 2개를 유지한다. DB 서버는 1개이므로 DB Pod 장애 시
  재시작/볼륨 재연결 동안 서비스 중단이 있을 수 있다.
- PVC에는 Argo CD prune/delete 방지, StorageClass에는 `Retain`을 설정했다.
- Longhorn 복제는 DB 백업을 대체하지 않는다. 별도 저장소로의 `pg_dump` 또는
  PostgreSQL 백업 구성은 아직 포함하지 않았다.
- 초기화 스크립트와 `POSTGRES_PASSWORD`는 빈 볼륨에서만 초기 계정을 설정한다.
  SSM 값만 바꿔도 기존 DB 사용자의 비밀번호는 바뀌지 않는다. 비밀번호 교체 시
  DB 역할의 비밀번호 변경과 SSM/ESO 갱신, 앱 재시작을 함께 수행한다.
- PostgreSQL 메이저 버전은 데이터 이전 절차 없이 변경하지 않는다.
