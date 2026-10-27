# The controller: Python + the Docker CLI, talking to the host's Docker through the mounted socket
FROM python:3.12-slim
# git: "Add from GitHub" in the extension clones into the projects folder
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=docker:27-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker:27-cli /usr/local/libexec/docker/cli-plugins/docker-buildx /usr/local/libexec/docker/cli-plugins/docker-buildx
COPY server.py test_server.py /controller/
WORKDIR /controller
CMD ["python3", "server.py"]
