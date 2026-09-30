#!/usr/bin/env bash
# A guided tour of the API's guarantees, against any running instance.
#
#   Local:  make demo && make tour
#   Live:   API=https://ledger.example.com VIEWER_KEY=... LP_KEY=... WRITE_KEY=... scripts/tour.sh
#
# VIEWER_KEY and LP_KEY must belong to the same fund. WRITE_KEY needs OPERATOR or higher on
# a fund of its own (locally the demo fund, live the sandbox). Needs curl and python3.
set -euo pipefail

# Keys passed in the environment win; otherwise use the ones `make demo` saved.
if [[ -z "${VIEWER_KEY:-}${LP_KEY:-}${WRITE_KEY:-}" && -f .demo-keys.env ]]; then
  # shellcheck disable=SC1091
  source .demo-keys.env
fi
API="${API:-http://localhost:8000}"
: "${VIEWER_KEY:?set VIEWER_KEY (run make demo first)}"
: "${LP_KEY:?set LP_KEY}"
: "${WRITE_KEY:?set WRITE_KEY}"

passed=0
failed=0
green=$'\e[32m' red=$'\e[31m' bold=$'\e[1m' reset=$'\e[0m'

section() { printf '\n%s%s%s\n' "$bold" "$1" "$reset"; }
check() { # name, expected, actual
  if [[ "$3" == "$2" ]]; then
    printf '  %sPASS%s  %-58s %s\n' "$green" "$reset" "$1" "$3"
    passed=$((passed + 1))
  else
    printf '  %sFAIL%s  %-58s got %s, expected %s\n' "$red" "$reset" "$1" "$3" "$2"
    failed=$((failed + 1))
  fi
}
status() { curl -s -o /dev/null -w '%{http_code}' "$@"; }      # HTTP status only
fetch() { curl -sf "$@"; }                                      # body only
as() { printf 'Authorization: Bearer %s' "$1"; }
json() { python3 -c "import json, sys; d = json.load(sys.stdin); print($1)"; }
v1="$API/api/v1"

if ! curl -fsS -o /dev/null "$API/healthz"; then
  echo "Can't reach $API/healthz. Is the API running? (make demo)" >&2
  exit 1
fi

# Discover everything from the API itself: which fund, which LP, which period.
FUND=$(fetch -H "$(as "$VIEWER_KEY")" "$v1/me/" | json 'd["memberships"][0]["fund"]')
MY_LP=$(fetch -H "$(as "$LP_KEY")" "$v1/me/" | json 'd["memberships"][0]["lp"]')
OTHER_LP=$(fetch -H "$(as "$VIEWER_KEY")" "$v1/funds/$FUND/accounts/" |
  json "next(a['owner_lp'] for a in d if a['owner_lp'] not in (None, '$MY_LP'))")
PERIOD=$(fetch -H "$(as "$LP_KEY")" "$v1/funds/$FUND/periods/" | json 'd[0]["id"]')
WFUND=$(fetch -H "$(as "$WRITE_KEY")" "$v1/me/" | json 'd["memberships"][0]["fund"]')
DAY=$(fetch -H "$(as "$WRITE_KEY")" "$v1/funds/$WFUND/periods/" |
  json 'next(p["start_date"] for p in d if p["status"] == "OPEN")')
echo "API $API"
echo "fund $FUND, write fund $WFUND"

section "Authentication"
check "no key -> 401" 401 "$(status "$v1/me/")"
check "made-up key -> 401" 401 "$(status -H "$(as fl_000000000000.not-a-real-key)" "$v1/me/")"

section "Authorization"
call='{"total_amount": "100.00", "notice_date": "'"$DAY"'", "due_date": "'"$DAY"'"}'
check "VIEWER reads the fund's accounts -> 200" 200 \
  "$(status -H "$(as "$VIEWER_KEY")" "$v1/funds/$FUND/accounts/")"
check "VIEWER posts a capital call -> 403" 403 \
  "$(status -X POST -H "$(as "$VIEWER_KEY")" -H "Idempotency-Key: tour-viewer" \
    -H "Content-Type: application/json" -d "$call" "$v1/funds/$FUND/capital-calls/")"
check "LP reads their own statement -> 200" 200 \
  "$(status -H "$(as "$LP_KEY")" "$v1/funds/$FUND/lps/$MY_LP/statement/?period=$PERIOD")"
check "LP reads another LP's statement -> 404 (not 403)" 404 \
  "$(status -H "$(as "$LP_KEY")" "$v1/funds/$FUND/lps/$OTHER_LP/statement/?period=$PERIOD")"
check "LP lists the fund's accounts -> 403" 403 \
  "$(status -H "$(as "$LP_KEY")" "$v1/funds/$FUND/accounts/")"
check "a fund you're not a member of -> 404" 404 \
  "$(status -H "$(as "$VIEWER_KEY")" "$v1/funds/00000000-0000-4000-8000-000000000000/accounts/")"

section "Exactly-once money movement"
key="tour-$(date +%s)-$RANDOM"
post() { # idempotency key, body -> "status body"
  curl -s -w '\n%{http_code}' -X POST -H "$(as "$WRITE_KEY")" -H "Idempotency-Key: $1" \
    -H "Content-Type: application/json" -d "$2" "$v1/funds/$WFUND/capital-calls/"
}
first=$(post "$key" "$call")
again=$(post "$key" "$call")
check "capital call -> 201" 201 "${first##*$'\n'}"
check "same key, same body -> 200 (a replay)" 200 "${again##*$'\n'}"
check "the replay returns the identical capital call" same \
  "$([[ "${first%$'\n'*}" == "${again%$'\n'*}" ]] && echo same || echo different)"
check "same key, different body -> 422" 422 \
  "$(post "$key" "${call/100.00/200.00}" | tail -n1)"
check "no Idempotency-Key -> 400" 400 \
  "$(status -X POST -H "$(as "$WRITE_KEY")" -H "Content-Type: application/json" -d "$call" \
    "$v1/funds/$WFUND/capital-calls/")"

section "The books balance"
check "reconciliation of the write fund" True \
  "$(fetch -H "$(as "$WRITE_KEY")" "$v1/funds/$WFUND/reconciliation/" | json 'd["balanced"]')"

printf '\n%d passed, %d failed\n' "$passed" "$failed"
[[ $failed -eq 0 ]]
