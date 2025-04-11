# 기본 Python 이미지
FROM python:3.10-slim

# 작업 디렉토리 설정
WORKDIR /app

# 종속성 파일 복사 및 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 앱 소스 복사
COPY . .

# 포트 노출 (기본 Flask 8080)
EXPOSE 8080

# 실행 명령
CMD ["python", "main.py"]
