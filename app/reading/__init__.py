"""서류 읽기 구성요소: 표 인식 → 열 역할 → 값 대응 → 표 검증.

기존 엔진 참조(복원, 2026-11-20): 기존 엔진의 app/reading·app/domain/{document,tables}.py를
판정과 무관한 서류 읽기 기반으로 그대로 되살렸다. 읽은 값은 판정에 바로 쓰지 않고 검수 대기
후보로만 저장한다(app/interview/documents.py).

설계: docs/design/test-report-table-extraction.md
"""
