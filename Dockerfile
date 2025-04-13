# Python 기반 이미지 사용
FROM python:3.10-slim

# 작업 디렉터리 생성
WORKDIR /app

# 필요 파일 복사
COPY . /app

# 필요한 패키지 설치
RUN pip install --no-cache-dir -r requirements.txt

# Gunicorn으로 실행 (Flask 개발 서버 X)
CMD ["gunicorn", "-b", "0.0.0.0:8080", "main:app"]
