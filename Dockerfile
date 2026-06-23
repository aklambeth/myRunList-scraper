FROM mcr.microsoft.com/devcontainers/python:1-3.12-bullseye

RUN git clone https://github.com/aklambeth/myRunList-scraper.git /workspace

WORKDIR /workspace

RUN pip install -r requirements.txt

CMD ["sleep", "infinity"]
