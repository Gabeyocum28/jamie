#!/usr/bin/env bash
# Builds the chosen environment's image on demand and runs Jamie in a fresh container for it.
#
#   ./jamie.sh join <meet-url> [--env NAME] [--personality NAME] [--agent claude|codex|gemini]
#   ./jamie.sh google-login [NAME]      sign a Google account in for Jamie (watch at localhost:6080)
#   ./jamie.sh agent-login <agent>      sign an agent CLI in with your subscription
#   ./jamie.sh debug <meet-url> [...]   join + dump Meet's DOM to workspace/<env>/meet-dump.html
#   ./jamie.sh shell [--env NAME]       a shell inside the environment
#   ./jamie.sh test                     run the self-checks
#   ./jamie.sh e2e                      end-to-end check in a real Meet (Jamie hosts it alone; ~3 min)
#   ./jamie.sh judge                    how well the judge reads requests (real model calls, ~30s)
#   ./jamie.sh learned [--env N] [--keep]  shortcuts Jamie taught itself; --keep adds them to the room's controls.json
#   ./jamie.sh controller               the API that starts a Jamie per meeting (localhost:7070)
set -e
cd "$(dirname "$0")"
[ -f .env ] || { echo "Copy .env.example to .env first."; exit 1; }

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
    -v "jamie-google-${JAMIE_GOOGLE:-main}:/data" -v "jamie-learned-$ENV_NAME:/learned" \
    -v jamie-claude:/home/pwuser/.claude -v jamie-codex:/home/pwuser/.codex -v jamie-gemini:/home/pwuser/.gemini \
    -v "$PWD/workspace/$ENV_NAME:/workspace" \
    -v "$PWD/environments/$ENV_NAME:/environment:ro" \
    -v "$PWD/personalities:/personalities:ro" \
    "$img" "$@"
}

cmd=$1; shift || true
case "$cmd" in
  join)  run -- python3 /app/bot.py "$@" ;;
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
  test)  run -- bash -c "cd /app && python3 test_env.py && python3 test_hearing.py && python3 test_voice.py && python3 test_notes.py && python3 test_show.py && python3 test_avatar.py"
         (cd controller && JAMIE_ROOT=.. python3 test_server.py) ;;
  e2e)   run -- python3 /app/e2e.py "$@" ;;
  judge) run -- bash -c "cd /app && python3 judge_eval.py" ;;
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
    grep -q '^JAMIE_CONTROLLER_TOKEN=.' .env || echo "JAMIE_CONTROLLER_TOKEN=$(openssl rand -hex 24)" >> .env
    docker build -q -t jamie-controller controller >/dev/null
    # shortcut: the repo is mounted, not baked in, so edits apply without a rebuild; COPY it in for the homelab
    docker run --rm --init --name jamie-controller -p 127.0.0.1:7070:7070 \
      -e JAMIE_CONTROLLER_TOKEN="$(sed -n 's/^JAMIE_CONTROLLER_TOKEN=//p' .env)" \
      -v /var/run/docker.sock:/var/run/docker.sock -v "$PWD:/jamie:ro" \
      -v jamie-claude:/logins/claude:ro \
      -v jamie-codex:/logins/codex:ro -v jamie-gemini:/logins/gemini:ro \
      jamie-controller ;;
  *)     sed -n '4,13p' "$0" | sed 's/^# //' ;;
esac
