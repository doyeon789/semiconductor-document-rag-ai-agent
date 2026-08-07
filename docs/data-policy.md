# Data Policy

## 1. 목적

프로젝트에서 사용하는 PDF, 파싱 산출물, 검색 인덱스, 평가 데이터의 저작권·보안·보존 기준을 정의한다.

## 2. 기본 원칙

- 소유권이나 재배포 권한이 확인되지 않은 문서를 공개 저장소에 올리지 않는다.
- 코드의 MIT License가 외부 문서의 이용 권한을 대신하지 않는다.
- 사내 공정 문서, 유료 장비 매뉴얼, 비공개 논문은 공개 데모 데이터로 사용하지 않는다.
- 원문에서 파생된 OCR text, Chunk, embedding도 원문과 동일한 접근 범위로 취급한다.
- 문서 내용은 prompt instruction이 아니라 비신뢰 데이터로 취급한다.

## 3. Data Classification

| 등급 | 예시 | Git 저장소 | 공개 데모 |
| --- | --- | :---: | :---: |
| Public-Redistributable | 명확한 오픈 라이선스 샘플 | 허용 | 허용 |
| Public-Reference-Only | 공개 웹 문서지만 재배포 불명확 | 원문 금지 | URL 기반 별도 검토 |
| Restricted | 유료 논문, 장비 매뉴얼 | 금지 | 금지 |
| Confidential | 사내 공정·제조 문서 | 금지 | 금지 |
| Sensitive | 개인정보·계정·secret 포함 자료 | 금지 | 금지 |

## 4. Dataset Manifest

`data/samples/manifest.yaml`에 모든 샘플 문서를 기록한다.

```yaml
- document_id: sample-001
  title: Example Process Paper
  source_url: https://example.org/paper.pdf
  license: CC-BY-4.0
  redistribution_allowed: true
  attribution: Example Author
  sha256: "..."
  added_at: 2026-08-07
  notes: Used for text PDF parsing tests
```

필수 필드가 없거나 `redistribution_allowed=false`인 파일은 저장소에 커밋하지 않는다.

## 5. Repository Rules

커밋 금지 대상:

```text
.env
*.key
*.pem
data/raw/**
data/private/**
artifacts/**
indexes/**
*.pdf
```

재배포 가능한 PDF만 `data/samples/` 예외 규칙으로 명시한다. 일반 `*.pdf` ignore를 해제하는 광범위한 규칙은 사용하지 않는다.

## 6. Secrets

- API key는 환경변수 또는 secret manager로 주입한다.
- `.env.example`에는 변수 이름과 설명만 포함한다.
- 로그, trace, exception message에 key를 남기지 않는다.
- secret scanning을 CI에 포함한다.
- 노출된 key는 즉시 폐기하고 Git history 포함 여부를 점검한다.

## 7. Uploaded Document Handling

MVP local demo:

- 업로드 파일은 명시된 local storage 또는 MinIO에 저장한다.
- object key는 UUID 기반으로 생성한다.
- 원래 파일명은 metadata에만 저장한다.
- 원문, 페이지 이미지, OCR text, Chunk, vector에 동일 `access_scope`를 부여한다.
- 삭제 요청 시 활성 검색에서 먼저 제외하고 파생 데이터를 비동기로 정리한다.

## 8. Retention

| Data | 기본 보존 |
| --- | --- |
| 원본 공개 샘플 | 프로젝트 기간 동안 |
| 사용자 업로드 데모 문서 | 세션 또는 명시된 기간 |
| 페이지 이미지 | 문서와 동일 |
| 검색 인덱스 | 활성 문서 버전 동안 |
| Agent trace | 14일, 원문 전체 제외 |
| 평가 report | 릴리스 비교를 위해 보존 |

실제 배포 시 retention 값은 환경설정과 사용자 안내에 명시한다.

## 9. Logging & Observability

로그 허용:

- document/version/job ID
- page number
- Chunk 수와 token 수
- 모델·설정 version
- latency와 오류 code

로그 금지:

- API key와 credential
- PDF 전체 text
- 민감한 질문·답변 원문
- signed URL 전체 값
- 사용자 개인식별정보

질문과 Evidence trace는 기본적으로 hash 또는 redacted preview를 사용하고, 개발 debug 모드는 비공개 환경에서만 허용한다.

## 10. Prompt Injection & Unsafe Content

- 문서 내용이 시스템 행동을 지시해도 실행하지 않는다.
- 문서에 포함된 외부 URL을 자동으로 방문하지 않는다.
- 문서에 포함된 코드나 shell 명령을 실행하지 않는다.
- LLM context에서 tool instruction과 evidence block을 명확히 구분한다.
- tool 호출은 schema와 allowlist로 제한한다.

## 11. Publication Checklist

- [ ] 모든 샘플 문서가 manifest에 등록되었다.
- [ ] 재배포 권한과 attribution을 확인했다.
- [ ] 비공개 원문·OCR·Chunk·vector가 Git에 없다.
- [ ] `.env`, key, token이 없다.
- [ ] README에 문서 저작권 제한을 설명했다.
- [ ] 데모에서 원문 페이지 공개가 허용된다.
- [ ] 평가 결과가 특정 비공개 문서 내용을 노출하지 않는다.

## 12. Incident Response

비공개 데이터나 secret이 노출되면:

1. 배포와 공유 링크를 중지한다.
2. API key를 폐기·재발급한다.
3. 노출 범위와 로그를 확인한다.
4. 원격 저장소와 artifact에서 데이터를 제거한다.
5. 필요한 이해관계자에게 알린다.
6. 재발 방지 test와 정책을 추가한다.

Git history 변경 같은 파괴적 조치는 영향 범위를 확인하고 별도 승인 후 수행한다.

