"""테스트 경로 설정.

배포 zip 은 각 도메인 디렉터리의 내용을 평면으로 담으므로(공통은 common/ 패키지로 동봉),
런타임 모듈은 도메인-로컬 절대 import(`from service`, `from keys` 등)를 쓴다.
repo 루트에서 도는 테스트(`from domains.<name>.service`)가 그 평면 내부 import 를 해석하도록
각 domains/<name> 를 sys.path 에 추가한다 — `domains.<name>.*` 절대 import 도 그대로 동작.
"""
import sys
from pathlib import Path

_DOMAINS = Path(__file__).parent / "domains"
for _d in sorted(_DOMAINS.iterdir()):
    if _d.is_dir():
        sys.path.insert(0, str(_d))
