ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}
WORKDIR /srv
# Laya is opt-in: build with INSTALL_LAYA=1 to bake the `laya` package into the image.
ARG INSTALL_LAYA=0
ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PIP_INDEX_URL=${PIP_INDEX_URL} PIP_DEFAULT_TIMEOUT=60 PIP_RETRIES=10
COPY requirements.txt requirements-laya.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
 && if [ "$INSTALL_LAYA" = "1" ]; then pip install --no-cache-dir -r requirements-laya.txt; fi
COPY app ./app
EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
