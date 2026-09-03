---
name: weather
description: Get current weather and forecasts from an external source. Use when the user asks for weather data that must be fetched rather than guessed.
metadata: {"nanobot":{"requires":{"bins":["curl"]}}}
---

# Weather

Free weather via wttr.in (no API key):

\```bash
# 简洁格式
curl --fail --silent --show-error --connect-timeout 5 --max-time 15 \
  "https://wttr.in/CityName?format=3"

# 详细格式
curl --fail --silent --show-error --connect-timeout 5 --max-time 15 \
  "https://wttr.in/CityName?format=%l:+%c+%t+%h+%w"
\```

Accept only a city/location value, URL-encode it, and never splice raw user text into a shell command. If curl fails or times out, report that no weather result was obtained; do not invent one.