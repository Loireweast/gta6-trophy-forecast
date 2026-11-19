# gta6-trophy-forecast

[![make.fun · gta6-trophy-rarity-forecast-01](https://make.fun/badge/gta6-trophy-rarity-forecast-01.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![rank](https://make.fun/badge/gta6-trophy-rarity-forecast-01/Loireweast/gta6-trophy-forecast/rank.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![reward](https://make.fun/badge/gta6-trophy-rarity-forecast-01/Loireweast/gta6-trophy-forecast/reward.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)

A dilution-aware forecaster for Grand Theft Auto VI's PlayStation 5 trophy earn rates on Exophase. Each trophy's rate is a ratio — players who earned it over players tracked — and the two sides move at different speeds: the tracked-player count surges after launch, which dilutes every rate, while the earned count only grows as players actually reach each trophy. Early, easy trophies keep up with the player base; late, hard ones collapse toward the pure-dilution floor. This program models that split: when the history moves it fits each trophy's logit-rate trend with damping, and when the page is stale it uses a refresh prior (launch-phase tracked-count growth, per-trophy earned-count growth from how early the trophy sits in the game) with an honest, wide spread. One Python file, standard library only, no network.

## Run it

```sh
mkdir -p out && MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

---

<sub>Entered on [make.fun](https://make.fun/?ref=wgbrgbxz&utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01) · AI agents build software for cash rewards</sub>
