FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制源代码
COPY src/ src/
COPY config/ config/

# 创建数据和日志目录
RUN mkdir -p data logs

# 运行服务
CMD ["python", "-m", "src.main"]
