#!/usr/bin/env bash
# Builds the chosen environment's image on demand and runs Jamie in a fresh container for it.
#
#   ./jamie.sh join <meet-url> [--env NAME] [--personality NAME] [--agent claude|codex|gemini] [--project PATH]
#   ./jamie.sh google-login [NAME]      sign a Google account in for Jamie (watch at localhost:6080)
#   ./jamie.sh agent-login <agent>      sign an agent CLI in with your subscription
#   ./jamie.sh debug <meet-url> [...]   join + dump Meet's DOM to workspace/<env>/meet-dump.html
#   ./jamie.sh shell [--env NAME]       a shell inside the environment
#   ./jamie.sh test                     run the self-checks
#   ./jamie.sh voice-check [--env NAME]  verify ElevenLabs and save a short spoken sample
#   ./jamie.sh e2e                      end-to-end check in a real Meet (Jamie hosts it alone; ~5 min)
#   ./jamie.sh e2e all                  every real-call scenario in turn, with a scoreboard (~25 min)
#   ./jamie.sh judge                    how well the judge reads requests (real model calls, ~30s)
#   ./jamie.sh learned [--env N] [--keep]  shortcuts Jamie taught itself; --keep adds them to the room's controls.json
#   ./jamie.sh files [--env N]          copy what Jamie kept (meeting notes, things it built) to ./files/<room>/
#   ./jamie.sh controller               the API that starts a Jamie per meeting (localhost:7070)
set -e
cd "$(dirname "$0")"
[ -f .env ] || { echo "Copy .env.example to .env first."; exit 1; }
# Opt-in: JAMIE_DOCKER_PLATFORM=linux/amd64 runs Jamie under emulation (slower), for Macs where Xvfb crashes natively
PLATFORM=$(sed -n 's/^JAMIE_DOCKER_PLATFORM=//p' .env)
[ -n "$PLATFORM" ] && export DOCKER_DEFAULT_PLATFORM=$PLATFORM

# --env from the args, else JAMIE_ENV in .env, else default
ENV_NAME=$(sed -n 's/^JAMIE_ENV=//p' .env); ENV_NAME=${ENV_NAME:-default}
args=("$@")
for i in "${!args[@]}"; do [ "${args[$i]}" = --env ] && ENV_NAME=${args[$((i + 1))]}; done
if [[ ! "$ENV_NAME" =~ ^[A-Za-z0-9_-]+$ ]] || [ ! -d "environments/$ENV_NAME" ]; then
  echo "Unknown environment '$ENV_NAME'. Available: $(ls environments | tr '\n' ' ')"; exit 1
fi

image() {
  echo "Building image for $ENV_NAME..." >&2
  docker build -q -t jamie-base . >/dev/null
  if [ -f "environments/$ENV_NAME/Dockerfile" ]; then
    docker build -q -t "jamie-env-$ENV_NAME" "environments/$ENV_NAME" >/dev/null
    echo "jamie-env-$ENV_NAME"
  else
    echo jamie-base
  fi
}

run() {  # run [docker flags...] -- <command...>
  local flags=() img
  while [ "$1" != -- ]; do flags+=("$1"); shift; done; shift
  img=$(image)
  mkdir -p "workspace/$ENV_NAME"
  [ -f "environments/$ENV_NAME/.env" ] && flags+=(--env-file "environments/$ENV_NAME/.env")
  # One Jamie at a time per machine: these ports are fixed.
  [ -t 0 ] && flags+=(-t)
  docker run --rm -i --init --shm-size 2g --name "jamie-$ENV_NAME" \
    -p 127.0.0.1:6080:6080 -p 127.0.0.1:3000:3000 -p 127.0.0.1:5173:5173 -p 127.0.0.1:8000:8000 \
    --env-file .env -e JAMIE_ENV="$ENV_NAME" "${flags[@]}" --label "jamie.google=${JAMIE_GOOGLE:-main}" \
    -v "jamie-google-${JAMIE_GOOGLE:-main}:/data" -v "jamie-learned-$ENV_NAME:/learned" -v "jamie-files-$ENV_NAME:/files" \
    -v jamie-claude:/home/pwuser/.claude -v jamie-codex:/home/pwuser/.codex -v jamie-gemini:/home/pwuser/.gemini \
    -v "$PWD/workspace/$ENV_NAME:/workspace" \
    -v "$PWD/environments/$ENV_NAME:/environment:ro" \
    -v "$PWD/personalities:/personalities:ro" \
    "$img" "$@"
}

cmd=$1; shift || true
case "$cmd" in
  join)
    bot=() flags=()
    while [ $# -gt 0 ]; do  # --project PATH: mount that folder, live, at /workspace/project
      if [ "$1" = --project ]; then
        [ -d "${2:-}" ] || { echo "--project needs an existing folder"; exit 1; }
        # Jamie runs as another user: share the folder's group with it, as the controller does
        chmod -R g+rwX "$2" 2>/dev/null || true; find "$2" -type d -exec chmod g+s {} + 2>/dev/null || true
        flags+=(-v "$(cd "$2" && pwd):/workspace/project" --group-add "$(ls -nd "$2" | awk '{print $4}')"); shift 2
      else bot+=("$1"); shift; fi
    done
    run "${flags[@]}" -- python3 /app/bot.py "${bot[@]}" ;;
  debug) run -e JAMIE_DEBUG=1 -- python3 /app/bot.py "$@" ;;
  google-login)
    [[ "${1:-main}" =~ ^[A-Za-z0-9_-]+$ ]] || { echo "Name: letters, digits, - and _ only"; exit 1; }
    JAMIE_GOOGLE=${1:-main} run -- python3 /app/bot.py --login ;;
  agent-login)
    case "$1" in
      claude) run -- claude ;;                       # then /login; or use CLAUDE_CODE_OAUTH_TOKEN in .env
      codex)  run -- codex login --device-auth ;;
      gemini) run -- gemini ;;                       # pick "Login with Google"; or GEMINI_API_KEY in .env
      *)      echo "usage: ./jamie.sh agent-login claude|codex|gemini"; exit 1 ;;
    esac ;;
  shell) run -- bash ;;
  voice-check)
    img=$(image)
    voice_flags=(--env-file .env)
    [ -f "environments/$ENV_NAME/.env" ] && voice_flags+=(--env-file "environments/$ENV_NAME/.env")
    docker run --rm "${voice_flags[@]}" -v "jamie-files-$ENV_NAME:/files" \
      --entrypoint python3 "$img" /app/voice.py --check --output /files/jamie-voice-check.mp3 ;;
  test)  run -- bash -c "cd /app && python3 test_env.py && python3 test_hearing.py && python3 test_voice.py && python3 test_speech.py && python3 test_notes.py && python3 test_show.py && python3 test_avatar.py"
         (cd controller && JAMIE_ROOT=.. python3 test_server.py) ;;
  e2e)
    if [ "$1" = all ]; then
      results=()
      for s in "" learn vibe open cancel "--env fun" "--env study" "--env work"; do
        # shellcheck disable=SC2086
        if "$0" e2e $s > "/tmp/jamie-e2e-${s// /}.log" 2>&1; then line="ok  ${s:-main}"; else line="NO  ${s:-main}  (log: /tmp/jamie-e2e-${s// /}.log)"; fi
        results+=("$line")  # (no ${results[-1]}: macOS ships bash 3.2)
        echo "$line"
      done
      printf '\n%s\n' "${results[@]}" | grep -q "^NO" && exit 1 || { echo "all real-call scenarios passed"; exit 0; }
    fi
    run -- python3 /app/e2e.py "$@" ;;
  judge) run -- bash -c "cd /app && python3 judge_eval.py" ;;
  files)
    mkdir -p "files/$ENV_NAME"
    docker run --rm -u root -v "jamie-files-$ENV_NAME:/files:ro" -v "$PWD/files/$ENV_NAME:/out" --entrypoint cp jamie-base -r /files/. /out/
    find "files/$ENV_NAME" -maxdepth 2 | sort | sed 's/^/  /' ;;
  learned)
    json=$(docker run --rm -v "jamie-learned-$ENV_NAME:/learned" --entrypoint cat jamie-base /learned/controls.json 2>/dev/null || echo "{}")
    echo "$json"
    if [[ " $* " == *" --keep "* ]]; then
      python3 -c 'import json, sys; p = sys.argv[1]
try: room = json.load(open(p))
except FileNotFoundError: room = {}
learned = json.loads(sys.argv[2]); json.dump({**learned, **room}, open(p, "w"), indent=2); print(f"Kept {len(learned)} in {p}")' \
        "environments/$ENV_NAME/controls.json" "$json"
    fi ;;
  controller)
    # .env.example ships an empty token line: replace it rather than adding a second one
    if ! grep -q '^JAMIE_CONTROLLER_TOKEN=.' .env; then
      sed -i.bak '/^JAMIE_CONTROLLER_TOKEN=/d' .env && rm .env.bak
      echo "JAMIE_CONTROLLER_TOKEN=$(openssl rand -hex 24)" >> .env
    fi
    docker build -q -t jamie-controller controller >/dev/null
    # Projects (the extension's Project dropdown): every folder in the projects folder, where "Add from
    # GitHub" also clones to, plus JAMIE_PROJECTS=name=/path,name2=/path2 for folders that live elsewhere
    home=$(sed -n 's/^JAMIE_PROJECTS_HOME=//p' .env); home=${home:-$HOME/jamie-projects}
    mkdir -p "$home"; home=$(cd "$home" && pwd)
    shown=$home  # in Windows Explorer, a WSL folder is at \\wsl.localhost\<distro>\...
    [ -n "${WSL_DISTRO_NAME:-}" ] && shown="\\\\wsl.localhost\\$WSL_DISTRO_NAME${home//\//\\}"
    echo "Projects folder: $shown"
    projects=(-v "$home:/projects" -e JAMIE_PROJECTS_SHOWN="$shown")
    # What the controller can't see from its container: this computer's OS, and the user folders people may
    # link folders from (-P: as Docker names them, e.g. /var/home/you when /home is a link)
    os=linux homes=$(cd ~ && pwd -P) drives=""
    [ "$(uname -s)" = Darwin ] && os=mac
    if [ -n "${WSL_DISTRO_NAME:-}" ]; then  # WSL: also the Windows user folder, as WSL mounts it
      os=wsl
      # Where WSL mounts drives (wsl.conf's automount root, /mnt by default). Not wslpath: once Docker Desktop
      # has mounted a Windows folder, wslpath names it by Docker's internal mount instead of /mnt/c/...
      drives=$(sed -n 's/^[[:space:]]*root[[:space:]]*=[[:space:]]*//p' /etc/wsl.conf 2>/dev/null | tail -n1 | tr -d '"')
      drives=${drives:-/mnt}; drives=${drives%/}
      win=$(cmd.exe /c 'echo %USERPROFILE%' 2>/dev/null | tr -d '\r') || true
      if [[ "$win" =~ ^([A-Za-z]):\\(.*)$ ]]; then
        rest=${BASH_REMATCH[2]}
        homes="$homes:$drives/$(printf %s "${BASH_REMATCH[1]}" | tr A-Z a-z)/${rest//\\//}"
      fi
    fi
    projects+=(-e JAMIE_HOST_OS="$os" -e JAMIE_HOST_HOMES="$homes" -e JAMIE_WSL_DRIVES="$drives")
    IFS=, read -ra entries <<< "$(sed -n 's/^JAMIE_PROJECTS=//p' .env)"
    for e in "${entries[@]}"; do
      name=${e%%=*} path=${e#*=}
      [[ "$name" =~ ^[A-Za-z0-9_-]+$ && -d "$path" ]] || { echo "JAMIE_PROJECTS: '$e' should be name=/existing/folder"; exit 1; }
      projects+=(-v "$(cd "$path" && pwd):/linked/$name")
      echo "Project $name: $path"
    done
    # shortcut: the repo is mounted, not baked in, so edits apply without a rebuild; COPY it in for the homelab
    docker run --rm --init --name jamie-controller -p 127.0.0.1:7070:7070 \
      -e JAMIE_CONTROLLER_TOKEN="$(sed -n 's/^JAMIE_CONTROLLER_TOKEN=//p' .env | tail -n1)" \
      ${PLATFORM:+-e DOCKER_DEFAULT_PLATFORM=$PLATFORM} \
      -v /var/run/docker.sock:/var/run/docker.sock -v "$PWD:/jamie:ro" "${projects[@]}" \
      -v jamie-claude:/logins/claude:ro \
      -v jamie-codex:/logins/codex:ro -v jamie-gemini:/logins/gemini:ro \
      jamie-controller ;;
  *)     sed -n '4,15p' "$0" | sed 's/^# //' ;;
esac
