# Action EV Parallel Profile

Generated: 2026-07-03

- game: zzz
- character: zzz_starlight_billy
- probability_model: zzz_default
- current: examples/zzz_billy_current.yaml
- horizon: 1
- action_limit: 4

## Results

### workers=1

- total_seconds: 2.0151
- errors: 0

| strategy | set | position | seconds | value_len | error |
| --- | --- | --- | ---: | ---: | --- |
| 随机位置 | 云岿如我 | random | 2.007852 | 8 | - |
| 固定位置 | 云岿如我 | 1 | 0.001493 | 8 | - |
| 固定位置 | 云岿如我 | 2 | 0.002285 | 8 | - |
| 固定位置 | 云岿如我 | 3 | 0.003435 | 8 | - |

### workers=2

- total_seconds: 2.2838
- errors: 0

| strategy | set | position | seconds | value_len | error |
| --- | --- | --- | ---: | ---: | --- |
| 随机位置 | 云岿如我 | random | 2.099908 | 8 | - |
| 固定位置 | 云岿如我 | 1 | 0.087747 | 8 | - |
| 固定位置 | 云岿如我 | 2 | 0.091928 | 8 | - |
| 固定位置 | 云岿如我 | 3 | 0.090133 | 8 | - |

## Interpretation

This profile verifies process-pool execution from a real module entrypoint, which is required on Windows spawn.
Parallel execution remains optional until larger state-DP profiles show a clear win over process startup and serialization overhead.
