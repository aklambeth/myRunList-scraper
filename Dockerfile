FROM mcr.microsoft.com/devcontainers/python:1-3.12-bullseye

COPY . /workspace
COPY docker/.bashrc /root/.bashrc

WORKDIR /workspace

RUN pip install -r requirements.txt

CMD ["sleep", "infinity"]
